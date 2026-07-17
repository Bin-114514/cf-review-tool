"""Tests for M2-2 heuristic insight generation — pure rule engine, zero API calls."""

import pytest
from analyzer import (
    ContestOverview,
    ProblemCodePair,
    Submission,
    TimelineEntry,
    build_submissions_from_status,
    build_timeline,
    extract_wa_ac_pairs,
    generate_insights,
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


# ── tests: efficiency_trend ─────────────────────────────────────────────────


def test_efficiency_trend_slowing():
    """AC 间隔越来越大 → insight 包含 '放缓' 或 '间隔'"""
    overview = _make_overview(problems_solved=3, total_problems=4)
    timeline = [
        _make_entry(1, "A", "OK", 100000 + 5 * 60),    # A at +5min
        _make_entry(2, "B", "OK", 100000 + 12 * 60),   # B at +12min  (gap 7min)
        _make_entry(3, "C", "OK", 100000 + 45 * 60),   # C at +45min  (gap 33min)
    ]
    pairs: list[ProblemCodePair] = []

    result = generate_insights(overview, timeline, pairs)

    trend = next((r for r in result if "放缓" in r), None)
    assert trend is not None, f"Expected efficiency trend insight, got: {result}"
    # 数值钉死：gaps = [7, 33] → 前半段均值 7min，后半段均值 33min
    assert "33min" in trend, f"Expected second-half avg 33min, got: {trend}"
    assert "7min" in trend, f"Expected first-half avg 7min, got: {trend}"


def test_efficiency_trend_too_few_ac():
    """只有 1 道 AC → 不生成效率趋势 insight"""
    overview = _make_overview(problems_solved=1, total_problems=2)
    timeline = [
        _make_entry(1, "A", "OK", 100500),
    ]
    pairs: list[ProblemCodePair] = []

    result = generate_insights(overview, timeline, pairs)

    has_trend = any("放缓" in r or "间隔" in r for r in result)
    assert not has_trend, f"Should NOT produce efficiency trend with only 1 AC, got: {result}"


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


# ── tests: type hints (compile-time verification) ──────────────────────────


def test_insights_type_hints():
    """验证 generate_insights 返回 list[str]"""
    overview = _make_overview()
    result = generate_insights(overview, [], [])
    assert isinstance(result, list)
    assert all(isinstance(r, str) for r in result)
