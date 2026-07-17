from typing import Any

import pytest
from analyzer import (
    ContestOverview,
    ProblemCodePair,
    Submission,
    TimelineEntry,
    build_submissions_from_status,
    build_timeline,
    calculate_contest_start,
    extract_overview,
    extract_wa_ac_pairs,
)


# ── fixtures ──────────────────────────────────────────────────────────────────


def make_submission(
    id: int,
    problem_index: str = "A",
    verdict: str = "OK",
    creation_time: int = 100,
) -> Submission:
    """快捷构造一条提交"""
    return Submission(
        id=id,
        problem_index=problem_index,
        problem_name=f"Problem {problem_index}",
        verdict=verdict,
        language="C++17 (GCC 7-32)",
        memory_bytes=262144,
        time_millis=15,
        creation_time=creation_time,
    )


# ── tests: build_timeline ─────────────────────────────────────────────────────


def test_build_timeline():
    """3 条提交 (A-WA, A-WA, A-AC) → 按时间排序，长度=3"""
    submissions = [
        make_submission(1, "A", "WRONG_ANSWER", 200),
        make_submission(2, "A", "WRONG_ANSWER", 100),
        make_submission(3, "A", "OK", 300),
    ]
    problems = [{"index": "A", "name": "Problem A"}]

    timeline = build_timeline(submissions)

    assert len(timeline) == 3
    assert timeline[0].creation_time == 100
    assert timeline[1].creation_time == 200
    assert timeline[2].creation_time == 300


def test_empty_submissions():
    """空列表 → 不抛异常，返回空列表"""
    result = build_timeline([])
    assert result == []


def test_ac_only():
    """只有 1 条 AC → timeline 正确"""
    submissions = [make_submission(1, "B", "OK", 500)]
    problems = [{"index": "B", "name": "Problem B"}]

    timeline = build_timeline(submissions)

    assert len(timeline) == 1
    entry = timeline[0]
    assert entry.verdict == "OK"
    assert entry.problem_index == "B"
    assert entry.solved is True


def test_mixed_verdicts():
    """混合 TLE / RE / CE 不干扰 sorted_by_time"""
    submissions = [
        make_submission(1, "A", "COMPILATION_ERROR", 50),
        make_submission(2, "A", "TIME_LIMIT_EXCEEDED", 150),
        make_submission(3, "A", "RUNTIME_ERROR", 250),
        make_submission(4, "A", "OK", 350),
    ]
    problems = [{"index": "A", "name": "Problem A"}]

    timeline = build_timeline(submissions)

    assert len(timeline) == 4
    assert timeline[0].creation_time == 50
    assert timeline[3].creation_time == 350
    assert timeline[0].solved is False
    assert timeline[3].solved is True


# ── tests: extract_wa_ac_pairs ────────────────────────────────────────────────


def test_get_wa_ac_diff():
    """2 WA + 1 AC → diff 包含正确的 wa_id、ac_id、failed_attempts=2"""
    submissions = [
        make_submission(10, "A", "WRONG_ANSWER", 100),
        make_submission(11, "A", "WRONG_ANSWER", 200),
        make_submission(12, "A", "OK", 300),
    ]
    problems = [{"index": "A", "name": "Problem A"}]

    timeline = build_timeline(submissions)
    pairs = extract_wa_ac_pairs(timeline)

    assert len(pairs) == 1
    pair = pairs[0]
    assert pair.problem_index == "A"
    assert len(pair.wa_submissions) == 2
    assert pair.ac_submission is not None
    assert pair.ac_submission.id == 12
    assert pair.wa_submissions[0].id == 10
    assert pair.wa_submissions[1].id == 11
    assert pair.failed_attempts == 2


def test_wa_only_not_in_pairs():
    """全是 WA → 不出现在 pairs 中（验收标准 #6）"""
    submissions = [
        make_submission(1, "A", "WRONG_ANSWER", 100),
        make_submission(2, "A", "WRONG_ANSWER", 200),
    ]
    problems = [{"index": "A", "name": "Problem A"}]

    timeline = build_timeline(submissions)
    pairs = extract_wa_ac_pairs(timeline)

    assert pairs == []


def test_first_try_ac_not_in_pairs():
    """一血 AC → 不出现在 pairs 中（验收标准 #5）"""
    submissions = [make_submission(1, "B", "OK", 100)]
    problems = [{"index": "B", "name": "Problem B"}]

    timeline = build_timeline(submissions)
    pairs = extract_wa_ac_pairs(timeline)

    assert pairs == []


def test_tle_not_treated_as_wa():
    """TLE / CE / RE 不算 WA，不出现在 wa_submissions 中"""
    submissions = [
        make_submission(1, "A", "TIME_LIMIT_EXCEEDED", 100),
        make_submission(2, "A", "COMPILATION_ERROR", 200),
        make_submission(3, "A", "RUNTIME_ERROR", 300),
        make_submission(4, "A", "OK", 400),
    ]
    problems = [{"index": "A", "name": "Problem A"}]

    timeline = build_timeline(submissions)
    pairs = extract_wa_ac_pairs(timeline)

    # TLE+CE+RE 都不是 WA，所以没有 wa_ac_pair
    assert pairs == []


def test_multi_problem():
    """多题目混合：A 有 WA→AC，B 一血 AC，C 未通过"""
    submissions = [
        make_submission(1, "A", "WRONG_ANSWER", 100),
        make_submission(2, "A", "OK", 200),
        make_submission(3, "B", "OK", 150),
        make_submission(4, "C", "TIME_LIMIT_EXCEEDED", 300),
    ]
    problems = [
        {"index": "A", "name": "Problem A"},
        {"index": "B", "name": "Problem B"},
        {"index": "C", "name": "Problem C"},
    ]

    timeline = build_timeline(submissions)
    pairs = extract_wa_ac_pairs(timeline)

    assert len(pairs) == 1
    assert pairs[0].problem_index == "A"


def test_type_hints():
    """验证类型的明确性（编译期检查）"""
    assert Submission(id=1, problem_index="X", problem_name="X", verdict="OK",
                      language="py", memory_bytes=0, time_millis=0, creation_time=0)
    assert TimelineEntry(id=1, problem_index="X", problem_name="X", verdict="OK",
                         language="py", memory_bytes=0, time_millis=0, creation_time=0, solved=True)
    assert ProblemCodePair(problem_index="X", problem_name="X", wa_submissions=[],
                           ac_submission=None, failed_attempts=0)
    assert ContestOverview(handle="test", contest_name="Test", rank=1,
                           old_rating=1500, new_rating=1600, rating_delta=100,
                           problems_solved=3, total_problems=5)


# ── tests: build_submissions_from_status ──────────────────────────────────────


def test_build_submissions_from_status():
    """将 CF user.status 转为 Submission 列表，按时间排序"""
    raw = [
        {"id": 1, "contestId": 1, "problem": {"index": "A", "name": "Watermelon"},
         "verdict": "OK", "programmingLanguage": "C++17", "memoryConsumedBytes": 262144,
         "timeConsumedMillis": 15, "creationTimeSeconds": 300},
        {"id": 2, "contestId": 1, "problem": {"index": "A", "name": "Watermelon"},
         "verdict": "WRONG_ANSWER", "programmingLanguage": "C++17", "memoryConsumedBytes": 524288,
         "timeConsumedMillis": 30, "creationTimeSeconds": 100},
    ]
    result = build_submissions_from_status(raw, contest_id=1)
    assert len(result) == 2
    assert result[0].creation_time == 100
    assert result[1].creation_time == 300
    assert result[1].verdict == "OK"


def test_build_submissions_from_status_excludes_other_contests():
    """过滤掉不匹配 contestId 的提交"""
    raw = [
        {"id": 1, "contestId": 1, "problem": {"index": "A", "name": "A"}, "verdict": "OK",
         "programmingLanguage": "py", "memoryConsumedBytes": 0, "timeConsumedMillis": 0,
         "creationTimeSeconds": 100},
        {"id": 2, "contestId": 999, "problem": {"index": "B", "name": "B"}, "verdict": "OK",
         "programmingLanguage": "py", "memoryConsumedBytes": 0, "timeConsumedMillis": 0,
         "creationTimeSeconds": 200},
    ]
    result = build_submissions_from_status(raw, contest_id=1)
    assert len(result) == 1
    assert result[0].id == 1


# ── tests: extract_overview ───────────────────────────────────────────────────


STUB_STANDINGS = {
    "contest": {"id": 1, "name": "CF Round #1", "startTimeSeconds": 1263849600},
    "problems": [{"index": "A"}, {"index": "B"}, {"index": "C"}],
    "rows": [{"rank": 42, "problemResults": [
        {"points": 500, "rejectedAttemptCount": 0},
        {"points": 500, "rejectedAttemptCount": 2},
        {"points": 0, "rejectedAttemptCount": 0},
    ]}],
}


def test_extract_overview_with_rating():
    """有 rating_change → 返回完整 overview"""
    rc = {"handle": "tourist", "oldRating": 1532, "newRating": 1621}
    overview = extract_overview(STUB_STANDINGS, rc, "tourist")
    assert overview.handle == "tourist"
    assert overview.contest_name == "CF Round #1"
    assert overview.rank == 42
    assert overview.old_rating == 1532
    assert overview.new_rating == 1621
    assert overview.rating_delta == 89
    assert overview.problems_solved == 2
    assert overview.total_problems == 3


def test_extract_overview_no_rating():
    """rating_change=None → rating 字段填 0"""
    overview = extract_overview(STUB_STANDINGS, None, "tourist")
    assert overview.old_rating == 0
    assert overview.new_rating == 0
    assert overview.rating_delta == 0


# ── tests: calculate_contest_start ────────────────────────────────────────────


def test_calculate_contest_start():
    """从 standings 提取比赛开始时间"""
    assert calculate_contest_start(STUB_STANDINGS) == 1263849600


def test_calculate_contest_start_default():
    """无 startTimeSeconds → 返回 0"""
    assert calculate_contest_start({}) == 0
