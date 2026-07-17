"""Tests for M2-2 heuristic insight generation — pure rule engine, zero API calls."""

import math

import pytest
from analyzer import (
    ContestOverview,
    ProblemCodePair,
    Submission,
    TimelineEntry,
    build_submissions_from_status,
    build_timeline,
    expected_solve_probability,
    extract_wa_ac_pairs,
    generate_insights,
    per_problem_probability,
)

# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def contest_start() -> int:
    return 100000  # 比赛开始时间戳


def _make_entry(
    id: int,
    problem_index: str = "A",
    verdict: str = "OK",
    creation_time: int = 100,
) -> TimelineEntry:
    """快捷构造一条 TimelineEntry"""
    return TimelineEntry(
        id=id,
        problem_index=problem_index,
        problem_name=f"Problem {problem_index}",
        verdict=verdict,
        language="C++17",
        memory_bytes=262144,
        time_millis=15,
        creation_time=creation_time,
        solved=(verdict == "OK"),
    )


def _make_pair(
    problem_index: str,
    problem_name: str,
    wa_ids: list[int],
    ac_id: int,
    wa_times: list[int] | None = None,
    ac_time: int = 500,
) -> ProblemCodePair:
    """快捷构造一个 WA→AC 对比对"""
    base = 100 + (ord(problem_index) - ord("A")) * 1000
    wa_subs = [
        _make_entry(wid, problem_index, "WRONG_ANSWER", wa_times[i] if wa_times else base + i * 100)
        for i, wid in enumerate(wa_ids)
    ]
    ac_sub = _make_entry(ac_id, problem_index, "OK", ac_time)
    return ProblemCodePair(
        problem_index=problem_index,
        problem_name=problem_name,
        wa_submissions=wa_subs,
        ac_submission=ac_sub,
        failed_attempts=len(wa_ids),
    )


def _make_overview(
    handle: str = "tourist",
    rank: int = 42,
    problems_solved: int = 4,
    total_problems: int = 6,
) -> ContestOverview:
    return ContestOverview(
        handle=handle,
        contest_name="CF Round #1",
        rank=rank,
        old_rating=1500,
        new_rating=1600,
        rating_delta=100,
        problems_solved=problems_solved,
        total_problems=total_problems,
    )


# ── tests: generate_insights top-level ──────────────────────────────────────


def test_generate_insights_empty_data():
    """空数据返回空列表，不崩溃"""
    overview = _make_overview(problems_solved=0, total_problems=0)
    result = generate_insights(overview, [], [])
    assert result == []


def test_generate_insights_all_ac():
    """全部一血 AC → 无罚时分析，但有一血表扬 + 速度分析"""
    overview = _make_overview(problems_solved=3, total_problems=3)
    timeline = [
        _make_entry(1, "A", "OK", 100000 + 5 * 60),   # +5min
        _make_entry(2, "B", "OK", 100000 + 12 * 60),  # +12min
        _make_entry(3, "C", "OK", 100000 + 25 * 60),  # +25min
    ]
    pairs: list[ProblemCodePair] = []

    result = generate_insights(overview, timeline, pairs)

    assert len(result) >= 1
    # 应有 AC 表扬相关的 insight
    any_ac = any("一次通过" in r or "干净" in r for r in result)
    assert any_ac, f"Expected first-blood-style praise in: {result}"


# ── tests: heaviest_penalty ─────────────────────────────────────────────────


def test_heaviest_penalty_dominates():
    """D 题 3 次 WA → 罚时数值和占比精确断言（分母含一发 AC 的 B 题）"""
    overview = _make_overview(problems_solved=4, total_problems=6)
    pairs = [
        _make_pair("D", "DP on Tree", [10, 11, 12], 13,
                   wa_times=[100200, 100800, 101400], ac_time=102820),  # 3 WA, AC at +2820s
        _make_pair("A", "Water", [1], 2,
                   wa_times=[100060], ac_time=100180),  # 1 WA, AC at +180s
    ]
    # Contest start = 100000（CF 罚时 = AC 距开赛秒数 + WA×600s）
    # D: 2820 + 3*600 = 4620s = 77min
    # A: 180 + 600 = 780s = 13min
    # B: 一发 AC at +600s → 600s（无 WA，不进 per_problem 但计入分母）
    # 总罚时 = 4620 + 780 + 600 = 6000s；D 占比 = 4620/6000 = 77%
    timeline = [
        _make_entry(1, "A", "WRONG_ANSWER", 100060),
        _make_entry(2, "A", "OK", 100180),
        _make_entry(20, "B", "OK", 100600),  # clean AC：钉死分母含全部已解题
        _make_entry(10, "D", "WRONG_ANSWER", 100200),
        _make_entry(11, "D", "WRONG_ANSWER", 100800),
        _make_entry(12, "D", "WRONG_ANSWER", 101400),
        _make_entry(13, "D", "OK", 102820),
    ]
    result = generate_insights(overview, timeline, pairs, contest_start=100000)

    penalty = next((r for r in result if "罚时" in r and "最重" in r), None)
    assert penalty is not None, f"Expected heaviest-penalty insight, got: {result}"
    # 数值钉死：题号、WA 次数、罚时分钟、占比百分数
    assert "D" in penalty
    assert "3 次 WA" in penalty
    assert "77min" in penalty, f"Expected 77min (4620s//60), got: {penalty}"
    assert "77%" in penalty, f"Expected 77% (4620/6000), got: {penalty}"


# ── tests: speed_tier ───────────────────────────────────────────────────────


def test_speed_tier_fast_start():
    """前 30min 内 AC 2 题 → insight 含 '前30min' 和 '2'"""
    overview = _make_overview(problems_solved=2, total_problems=4)
    timeline = [
        _make_entry(1, "A", "OK", 100000 + 8 * 60),   # +8min
        _make_entry(2, "B", "OK", 100000 + 22 * 60),  # +22min
    ]
    pairs: list[ProblemCodePair] = []

    result = generate_insights(overview, timeline, pairs, contest_start=100000)

    has_speed = any("前 30min" in r and "2" in r for r in result)
    assert has_speed, f"Expected speed insight with '前 30min' and '2', got: {result}"


def test_speed_tier_anchored_to_contest_start():
    """C1/I2 修复验证：首提交在 +40min，AC 在 +45min → 不应触发'前 30min'表扬"""
    overview = _make_overview(problems_solved=1, total_problems=4)
    timeline = [
        _make_entry(1, "A", "WRONG_ANSWER", 100000 + 40 * 60),  # 首提交 +40min
        _make_entry(2, "A", "OK", 100000 + 45 * 60),            # AC +45min
    ]
    pairs: list[ProblemCodePair] = []

    result = generate_insights(overview, timeline, pairs, contest_start=100000)

    has_speed = any("前 30min" in r for r in result)
    assert not has_speed, f"AC at +45min should NOT trigger fast-start praise, got: {result}"


# ── tests: wa_density ───────────────────────────────────────────────────────


def test_wa_density_warning():
    """C 题 4 次 WA → insight 含 'C' 和 '建议' / '复盘'"""
    overview = _make_overview(problems_solved=3, total_problems=5)
    pairs = [
        _make_pair("C", "Graph", [20, 21, 22, 23], 24,
                   wa_times=[100100, 100200, 100300, 100400], ac_time=100500),
    ]
    timeline = [
        _make_entry(20, "C", "WRONG_ANSWER", 100100),
        _make_entry(21, "C", "WRONG_ANSWER", 100200),
        _make_entry(22, "C", "WRONG_ANSWER", 100300),
        _make_entry(23, "C", "WRONG_ANSWER", 100400),
        _make_entry(24, "C", "OK", 100500),
    ]
    result = generate_insights(overview, timeline, pairs)
    has_density = any("C" in r and ("建议" in r or "复盘" in r) for r in result)
    assert has_density, f"Expected density warning mentioning 'C', got: {result}"


# ── tests: first_blood_praise ───────────────────────────────────────────────


def test_first_blood_praise():
    """A 题只有 1 条 AC 提交，B 题 1 条 AC → insight 包含 '一次通过' 或 '干净'"""
    overview = _make_overview(problems_solved=2, total_problems=2)
    timeline = [
        _make_entry(1, "A", "OK", 100300),
        _make_entry(2, "B", "OK", 100800),
    ]
    pairs: list[ProblemCodePair] = []

    result = generate_insights(overview, timeline, pairs)

    assert len(result) >= 1
    any_praise = any("一次通过" in r or "干净" in r for r in result)
    assert any_praise, f"Expected first-blood praise, got: {result}"


# ── tests: unsolved_warning ─────────────────────────────────────────────────


def test_unsolved_warning():
    """E 题有 2 次提交但 0 AC → insight 含 'E' 和 '未AC'"""
    overview = _make_overview(problems_solved=3, total_problems=5)
    timeline = [
        _make_entry(1, "A", "OK", 100200),
        _make_entry(2, "B", "OK", 100500),
        _make_entry(3, "C", "OK", 101000),
        _make_entry(30, "E", "WRONG_ANSWER", 101500),
        _make_entry(31, "E", "TIME_LIMIT_EXCEEDED", 102000),
    ]
    pairs: list[ProblemCodePair] = []

    result = generate_insights(overview, timeline, pairs)

    has_warning = any("E" in r and ("未AC" in r or "未通过" in r) for r in result)
    assert has_warning, f"Expected unsolved warning mentioning 'E', got: {result}"


# ── tests: solve_probability ──────────────────────────────────────────────────


def test_expected_solve_probability_basic():
    """验证 Elo 公式的基准值"""
    # 等 rating → 50%
    assert abs(expected_solve_probability(1500, 1500) - 0.5) < 0.01
    # 高 200 → ~76%
    assert abs(expected_solve_probability(1700, 1500) - 0.76) < 0.02
    # 低 200 → ~24%
    assert abs(expected_solve_probability(1500, 1700) - 0.24) < 0.02
    # 高 400 → ~91%
    assert abs(expected_solve_probability(1900, 1500) - 0.91) < 0.02


def test_solve_probability_above_expectation():
    """rating 1900 的题，选手 1850 (P≈43%)，AC 了 → 超出预期"""
    overview = _make_overview(rank=10, problems_solved=3, total_problems=5)
    overview = ContestOverview(
        handle="tourist",
        contest_name="CF Round #1",
        rank=10,
        old_rating=1500,   # 赛前 rating（概率用这个）
        new_rating=1530,
        rating_delta=30,
        problems_solved=3,
        total_problems=5,
    )
    timeline = [
        _make_entry(1, "D", "WRONG_ANSWER", 100200),
        _make_entry(2, "D", "OK", 100800),
    ]
    pairs = [
        _make_pair("D", "Hard Problem", [1], 2,
                   wa_times=[100200], ac_time=100800),
    ]
    # 题 D rating 2100 vs 选手 1500 → P = 1/(1+10^((2100-1500)/400)) = 1/(1+10^1.5) ≈ 3%
    problem_ratings = {"D": 2100, "A": 1200, "B": 1300}

    result = generate_insights(overview, timeline, pairs, problem_ratings=problem_ratings)

    prob_line = next((r for r in result if "超出预期" in r), None)
    assert prob_line is not None, f"Expected above-expectation insight for D, got: {result}"
    assert "3%" in prob_line or "4%" in prob_line, f"Expected ~3% probability (1500 vs 2100), got: {prob_line}"


def test_solve_probability_below_expectation():
    """rating 1300 的题，选手 1800 (P≈95%)，没 AC 只有 WA → 低于预期"""
    overview = _make_overview(problems_solved=2, total_problems=4)
    overview = ContestOverview(
        handle="tourist",
        contest_name="CF Round #1",
        rank=50,
        old_rating=2100,
        new_rating=2080,
        rating_delta=-20,
        problems_solved=2,
        total_problems=4,
    )
    timeline = [
        _make_entry(1, "A", "OK", 100300),
        _make_entry(2, "B", "OK", 100800),
        _make_entry(3, "C", "WRONG_ANSWER", 101500),  # 简单题 WA，没 AC
        _make_entry(4, "C", "WRONG_ANSWER", 102000),
    ]
    pairs: list[ProblemCodePair] = []
    # C rating 1300 vs 选手 2100 → P ≈ 99%
    problem_ratings = {"A": 1200, "B": 1250, "C": 1300, "D": 2300}

    result = generate_insights(overview, timeline, pairs, problem_ratings=problem_ratings)

    prob_line = next((r for r in result if "低于预期" in r), None)
    assert prob_line is not None, f"Expected below-expectation insight, got: {result}"
    assert "C" in prob_line, f"Expected C mentioned, got: {prob_line}"
    assert "99%" in prob_line or "98%" in prob_line, f"Expected ~99% probability for C (2100 vs 1300), got: {prob_line}"


def test_solve_probability_skips_missing_rating():
    """题目没有 rating 时跳过该题"""
    overview = _make_overview(rank=10, problems_solved=3, total_problems=5)
    overview = ContestOverview(
        handle="tourist",
        contest_name="CF Round #1",
        rank=10,
        old_rating=1850,
        new_rating=1880,
        rating_delta=30,
        problems_solved=3,
        total_problems=5,
    )
    # D 在 problem_ratings 中不存在 (无 rating)
    timeline = [
        _make_entry(1, "D", "OK", 100800),
    ]
    pairs: list[ProblemCodePair] = []
    problem_ratings: dict[str, int] = {}

    result = generate_insights(overview, timeline, pairs, problem_ratings=problem_ratings)

    # D 无 rating → 不应产生概率 insight
    prob_lines = [r for r in result if "预期通过率" in r]
    assert prob_lines == [], f"No rating → no probability insight, got: {prob_lines}"


def test_solve_probability_only_when_interesting():
    """close probability（40%~60%）不产生 insight —— 不值得提"""
    overview = _make_overview(rank=10, problems_solved=2, total_problems=4)
    overview = ContestOverview(
        handle="tourist",
        contest_name="CF Round #1",
        rank=10,
        old_rating=1400,
        new_rating=1420,
        rating_delta=20,
        problems_solved=2,
        total_problems=4,
    )
    timeline = [
        _make_entry(1, "A", "WRONG_ANSWER", 100200),
        _make_entry(2, "A", "OK", 100800),
        _make_entry(3, "B", "OK", 101200),
    ]
    pairs = [
        _make_pair("A", "Med Problem", [1], 2,
                   wa_times=[100200], ac_time=100800),
    ]
    # P ≈ 50% (1400 vs 1400) — too close to call, not insightful
    problem_ratings = {"A": 1400, "B": 1300}

    result = generate_insights(overview, timeline, pairs, problem_ratings=problem_ratings)

    prob_lines = [r for r in result if "预期通过率" in r]
    assert prob_lines == [], f"P≈50% is uninteresting, should skip, got: {prob_lines}"


# ── tests: importance ordering ─────────────────────────────────────────────


def test_insights_importance_order():
    """洞察按重要性排序：罚时 > 速度 > 一发 AC（UI 截断 [:6] 依赖此顺序）"""
    overview = _make_overview(problems_solved=3, total_problems=5)
    # 构造同时触发罚时、速度、一发 AC 三条规则的数据：
    # A: 开赛 +3min 一发 AC（速度 + 一发 AC）
    # B: 1 WA 后 AC（罚时）
    timeline = [
        _make_entry(1, "A", "OK", 100000 + 3 * 60),
        _make_entry(2, "B", "WRONG_ANSWER", 100000 + 10 * 60),
        _make_entry(3, "B", "OK", 100000 + 20 * 60),
    ]
    pairs = [
        _make_pair("B", "Problem B", [2], 3,
                   wa_times=[100000 + 10 * 60], ac_time=100000 + 20 * 60),
    ]

    result = generate_insights(overview, timeline, pairs, contest_start=100000)

    idx_penalty = next((i for i, r in enumerate(result) if "罚时" in r), None)
    idx_speed = next((i for i, r in enumerate(result) if "前 30min" in r), None)
    idx_oneshot = next((i for i, r in enumerate(result) if "一次通过" in r), None)
    assert idx_penalty is not None, f"Missing penalty insight: {result}"
    assert idx_speed is not None, f"Missing speed insight: {result}"
    assert idx_oneshot is not None, f"Missing one-shot insight: {result}"
    assert idx_penalty < idx_speed < idx_oneshot, (
        f"Wrong order: penalty@{idx_penalty}, speed@{idx_speed}, oneshot@{idx_oneshot}: {result}"
    )
    # 如有概率洞察（超出/低于预期），它应插在 speed 和 one-shot 之间
    for i, r in enumerate(result):
        if "超出预期" in r or "低于预期" in r:
            assert idx_speed < i < idx_oneshot, (
                f"Probability insight at #{i} should be between speed(#{idx_speed}) and oneshot(#{idx_oneshot}): {result}"
            )
            break


# ── tests: per_problem_probability ─────────────────────────────────────────


def test_per_problem_probability_all_rated():
    """3 道有 rating 的题，用户 rating 1850，断言每道概率"""
    overview = ContestOverview(
        handle="tourist",
        contest_name="CF Round #1",
        rank=10,
        old_rating=1850,
        new_rating=1880,
        rating_delta=30,
        problems_solved=3,
        total_problems=4,
    )
    problem_ratings: dict[str, int] = {"A": 1200, "B": 1600, "C": 2000}
    # 人工验算：
    # A: 1/(1+10^((1200-1850)/400)) = 1/(1+10^(-650/400)) = 1/(1+10^-1.625) ≈ 1/(1+0.0237) ≈ 0.977
    # B: 1/(1+10^((1600-1850)/400)) = 1/(1+10^-0.625) ≈ 1/(1+0.237) ≈ 0.808
    # C: 1/(1+10^((2000-1850)/400)) = 1/(1+10^0.375) ≈ 1/(1+2.37) ≈ 0.297
    result = per_problem_probability(overview, problem_ratings)
    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    assert abs(result["A"] - 0.977) < 0.01, f"A prob expected ~0.977, got {result['A']}"
    assert abs(result["B"] - 0.808) < 0.01, f"B prob expected ~0.808, got {result['B']}"
    assert abs(result["C"] - 0.297) < 0.01, f"C prob expected ~0.297, got {result['C']}"


def test_per_problem_probability_empty():
    """空 problem_ratings 返回 {}"""
    overview = _make_overview()
    result = per_problem_probability(overview, {})
    assert result == {}


def test_per_problem_probability_boundary():
    """problem_rating == user_rating 时 P ≈ 0.5"""
    overview = ContestOverview(
        handle="test",
        contest_name="CF Round",
        rank=50,
        old_rating=1500,
        new_rating=1520,
        rating_delta=20,
        problems_solved=1,
        total_problems=2,
    )
    problem_ratings = {"A": 1500, "B": 1400}
    result = per_problem_probability(overview, problem_ratings)
    assert abs(result["A"] - 0.5) < 0.01, f"Equal rating should give 0.5, got {result['A']}"
    assert abs(result["B"] - 0.640) < 0.01, f"1400 vs 1500 should be ~0.64, got {result['B']}"


def test_per_problem_probability_skip_unrated():
    """部分题有 rating 部分没有 → 只返回有 rating 的"""
    overview = ContestOverview(
        handle="test",
        contest_name="CF Round",
        rank=50,
        old_rating=1500,
        new_rating=1520,
        rating_delta=20,
        problems_solved=2,
        total_problems=3,
    )
    problem_ratings: dict[str, int] = {"A": 1400, "C": 1700}  # B 无 rating
    result = per_problem_probability(overview, problem_ratings)
    assert set(result.keys()) == {"A", "C"}, f"Should skip B (no rating), got keys: {result.keys()}"


def test_per_problem_probability_unrated_user():
    """赛前 rating=0（unrated 选手首场）→ 返回 {}"""
    overview = ContestOverview(
        handle="newbie",
        contest_name="CF Round",
        rank=100,
        old_rating=0,
        new_rating=1200,
        rating_delta=1200,
        problems_solved=1,
        total_problems=2,
    )
    problem_ratings = {"A": 1200}
    result = per_problem_probability(overview, problem_ratings)
    assert result == {}, f"Unrated user should get empty, got {result}"


# ── tests: type hints (compile-time verification) ──────────────────────────


def test_insights_type_hints():
    """验证 generate_insights 返回 list[str]"""
    overview = _make_overview()
    result = generate_insights(overview, [], [])
    assert isinstance(result, list)
    assert all(isinstance(r, str) for r in result)
