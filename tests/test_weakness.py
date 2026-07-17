"""Tests for M2-3 weakness-analysis data layer — paginated fetch + tag extraction."""

import pytest
from fetcher import CFAPIError, fetch_recent_submissions

# ── helpers ─────────────────────────────────────────────────────────────────


def _make_raw_submission(sub_id: int, contest_id: int = 1) -> dict:
    """构造一条 CF user.status 原始提交记录"""
    return {
        "id": sub_id,
        "contestId": contest_id,
        "creationTimeSeconds": 1700000000 + sub_id,
        "problem": {
            "contestId": contest_id,
            "index": "A",
            "name": f"Problem {sub_id}",
            "rating": 1200,
            "tags": ["implementation"],
        },
        "author": {
            "contestId": contest_id,
            "members": [{"handle": "tourist"}],
            "participantType": "CONTESTANT",
        },
        "programmingLanguage": "C++17",
        "verdict": "OK",
        "timeConsumedMillis": 15,
        "memoryConsumedBytes": 262144,
    }


def _page(ids: range) -> dict:
    """构造一页 user.status 响应"""
    return {"status": "OK", "result": [_make_raw_submission(i) for i in ids]}


# ── tests: fetch_recent_submissions（分页拉取）──────────────────────────────


def test_paginated_fetch(mocker):
    """250 条提交分 3 页（100+100+50）→ 拉取全部 250 条，页间无重复"""
    pages = [
        _page(range(1, 101)),     # 第 1 页：id 1-100
        _page(range(101, 201)),   # 第 2 页：id 101-200
        _page(range(201, 251)),   # 第 3 页：id 201-250（不足 100 → 数据到底）
    ]
    mock = mocker.patch("fetcher.cf_api_get", side_effect=pages)
    mocker.patch("fetcher.time.sleep")  # 跳过分页间隔等待

    result = fetch_recent_submissions(handle="tourist", count=500)

    assert len(result) == 250
    # 页间数据不重复
    ids = [s["id"] for s in result]
    assert len(ids) == len(set(ids)), "duplicate submissions across pages"
    # 分页参数正确：from 递增 1 → 101 → 201
    assert mock.call_count == 3
    calls = mock.call_args_list
    assert calls[0].args[1]["from"] == "1"
    assert calls[1].args[1]["from"] == "101"
    assert calls[2].args[1]["from"] == "201"


def test_paginated_fetch_stops_at_count(mocker):
    """count=150 → 拉满 150 条即停止，不再请求第 3 页"""
    pages = [
        _page(range(1, 101)),
        _page(range(101, 201)),
    ]
    mock = mocker.patch("fetcher.cf_api_get", side_effect=pages)
    mocker.patch("fetcher.time.sleep")

    result = fetch_recent_submissions(handle="tourist", count=150)

    assert len(result) == 150
    assert mock.call_count == 2  # 两页已凑够 150，不发第 3 次请求


def test_paginated_fetch_single_short_page(mocker):
    """总量不足一页（30 条）→ 一次请求即返回"""
    mock = mocker.patch("fetcher.cf_api_get", side_effect=[_page(range(1, 31))])
    mocker.patch("fetcher.time.sleep")

    result = fetch_recent_submissions(handle="tourist", count=500)

    assert len(result) == 30
    assert mock.call_count == 1


def test_paginated_fetch_empty(mocker):
    """新用户无提交 → 返回空列表"""
    mocker.patch("fetcher.cf_api_get", return_value={"status": "OK", "result": []})
    mocker.patch("fetcher.time.sleep")

    result = fetch_recent_submissions(handle="new_user", count=500)

    assert result == []


def test_paginated_fetch_handles_api_error(mocker):
    """CFAPIError 透传"""
    mocker.patch("fetcher.cf_api_get", side_effect=CFAPIError("CF API returned FAILED"))
    mocker.patch("fetcher.time.sleep")

    with pytest.raises(CFAPIError, match="CF API returned FAILED"):
        fetch_recent_submissions(handle="tourist", count=500)


# ── tests: analyze_tags / analyze_rating_bands（M2-3b 分析层，纯函数）────────

from analyzer import analyze_rating_bands, analyze_tags  # noqa: E402


def _make_analysis_submission(
    sub_id: int,
    index: str = "A",
    tags: list[str] | None = None,
    rating: int | None = 1200,
    verdict: str = "OK",
    relative_time: int = 600,
    participant_type: str = "CONTESTANT",
) -> dict:
    """构造一条用于弱点分析的原始提交记录（含 tags / rating / relativeTimeSeconds）"""
    problem: dict = {"contestId": 1, "index": index, "name": f"Problem {index}"}
    if tags is not None:
        problem["tags"] = tags
    if rating is not None:
        problem["rating"] = rating
    return {
        "id": sub_id,
        "contestId": 1,
        "creationTimeSeconds": 1700000000 + sub_id,
        "relativeTimeSeconds": relative_time,
        "problem": problem,
        "author": {
            "contestId": 1,
            "members": [{"handle": "tourist"}],
            "participantType": participant_type,
        },
        "programmingLanguage": "C++17",
        "verdict": verdict,
        "timeConsumedMillis": 15,
        "memoryConsumedBytes": 262144,
    }


def test_tag_analysis():
    """100 条混合提交 → 各 tag 的 total/ac/wa/ac_rate/avg_time 统计正确"""
    submissions: list[dict] = []
    sid = 0
    # dp: 30 AC (relative_time=600) + 10 WA → total 40, ac_rate 0.75
    for _ in range(30):
        sid += 1
        submissions.append(_make_analysis_submission(sid, "A", ["dp"], 1500, "OK", 600))
    for _ in range(10):
        sid += 1
        submissions.append(_make_analysis_submission(sid, "A", ["dp"], 1500, "WRONG_ANSWER", 300))
    # math: 15 AC (relative_time=1200) + 15 WA → total 30, ac_rate 0.5
    for _ in range(15):
        sid += 1
        submissions.append(_make_analysis_submission(sid, "B", ["math"], 1300, "OK", 1200))
    for _ in range(15):
        sid += 1
        submissions.append(_make_analysis_submission(sid, "B", ["math"], 1300, "WRONG_ANSWER", 900))
    # greedy: 20 AC + 5 WA + 5 TLE → total 30, ac 20, wa 5（TLE 不算 WA）
    for _ in range(20):
        sid += 1
        submissions.append(_make_analysis_submission(sid, "C", ["greedy"], 1700, "OK", 1800))
    for _ in range(5):
        sid += 1
        submissions.append(_make_analysis_submission(sid, "C", ["greedy"], 1700, "WRONG_ANSWER", 1500))
    for _ in range(5):
        sid += 1
        submissions.append(_make_analysis_submission(sid, "C", ["greedy"], 1700, "TIME_LIMIT_EXCEEDED", 1500))

    assert len(submissions) == 100

    result = analyze_tags(submissions)

    assert result["dp"]["total"] == 40
    assert result["dp"]["ac"] == 30
    assert result["dp"]["wa"] == 10
    assert result["dp"]["ac_rate"] == pytest.approx(0.75)
    assert result["dp"]["avg_time"] == pytest.approx(600)  # AC 提交的平均 relativeTimeSeconds

    assert result["math"]["total"] == 30
    assert result["math"]["ac"] == 15
    assert result["math"]["wa"] == 15
    assert result["math"]["ac_rate"] == pytest.approx(0.5)
    assert result["math"]["avg_time"] == pytest.approx(1200)

    assert result["greedy"]["total"] == 30
    assert result["greedy"]["ac"] == 20
    assert result["greedy"]["wa"] == 5  # TLE 不计入 wa
    assert result["greedy"]["ac_rate"] == pytest.approx(20 / 30)


def test_tag_analysis_multi_tag_problem():
    """一道题多个 tags → 每个 tag 都计入该提交"""
    submissions = [
        _make_analysis_submission(1, "A", ["dp", "math"], 1500, "OK", 600),
        _make_analysis_submission(2, "A", ["dp", "math"], 1500, "WRONG_ANSWER", 300),
    ]

    result = analyze_tags(submissions)

    for tag in ("dp", "math"):
        assert result[tag]["total"] == 2
        assert result[tag]["ac"] == 1
        assert result[tag]["wa"] == 1
        assert result[tag]["ac_rate"] == pytest.approx(0.5)


def test_tag_analysis_excludes_practice():
    """PRACTICE / VIRTUAL 提交不计入统计（只统计 rated 参赛）"""
    submissions = [
        _make_analysis_submission(1, "A", ["dp"], 1500, "OK", 600, "CONTESTANT"),
        _make_analysis_submission(2, "A", ["dp"], 1500, "OK", 600, "PRACTICE"),
        _make_analysis_submission(3, "A", ["dp"], 1500, "WRONG_ANSWER", 300, "VIRTUAL"),
    ]

    result = analyze_tags(submissions)

    assert result["dp"]["total"] == 1
    assert result["dp"]["ac"] == 1
    assert result["dp"]["wa"] == 0


def test_rating_band_analysis():
    """按 100-rating 分桶统计 AC 率和平均时间"""
    submissions = [
        _make_analysis_submission(1, "A", ["math"], 1200, "OK", 300),
        _make_analysis_submission(2, "A", ["math"], 1300, "OK", 500),
        _make_analysis_submission(3, "B", ["dp"], 1500, "OK", 1000),
        _make_analysis_submission(4, "B", ["dp"], 1400, "WRONG_ANSWER", 800),
        _make_analysis_submission(5, "C", ["graphs"], 1700, "WRONG_ANSWER", 2000),
        _make_analysis_submission(6, "D", ["dp"], 2100, "OK", 3000),
    ]

    result = analyze_rating_bands(submissions)

    assert result["1200-1300"]["total"] == 1
    assert result["1200-1300"]["ac"] == 1
    assert result["1200-1300"]["ac_rate"] == pytest.approx(1.0)
    assert result["1200-1300"]["avg_time"] == pytest.approx(300)

    assert result["1300-1400"]["total"] == 1
    assert result["1300-1400"]["ac"] == 1
    assert result["1300-1400"]["avg_time"] == pytest.approx(500)

    assert result["1400-1500"]["total"] == 1
    assert result["1400-1500"]["ac"] == 0
    assert result["1400-1500"]["wa"] == 1
    assert result["1400-1500"]["ac_rate"] == pytest.approx(0.0)

    assert result["1500-1600"]["total"] == 1
    assert result["1500-1600"]["ac"] == 1

    assert result["1700-1800"]["total"] == 1
    assert result["1700-1800"]["ac"] == 0

    assert result["2100-2200"]["total"] == 1
    assert result["2100-2200"]["ac"] == 1


def test_rating_band_skips_unrated_problems():
    """题目无 rating 字段 → 不计入任何 band，不崩溃"""
    submissions = [
        _make_analysis_submission(1, "A", ["math"], None, "OK", 300),
        _make_analysis_submission(2, "B", ["dp"], 1500, "OK", 1000),
    ]

    result = analyze_rating_bands(submissions)

    total_across_bands = sum(band["total"] for band in result.values())
    assert total_across_bands == 1  # 只有 rated 的那条


def test_100_band_granularity():
    """1700-1800 段有 5 题，1800-1900 段有 3 题

    边界验证：
    - 1749 落 1700-1800（左闭右开）
    - 1800 落 1800-1900（1800 是下一个桶的下界）
    """
    submissions = [
        # 1700-1800: 5 题（rating 1700, 1720, 1749, 1755, 1799）
        _make_analysis_submission(1, "A", tags=["math"],  rating=1700, verdict="OK"),
        _make_analysis_submission(2, "B", tags=["dp"],    rating=1720, verdict="OK"),
        _make_analysis_submission(3, "C", tags=["dp"],    rating=1749, verdict="WRONG_ANSWER"),
        _make_analysis_submission(4, "D", tags=["greedy"],rating=1755, verdict="OK"),
        _make_analysis_submission(5, "E", tags=["dp"],    rating=1799, verdict="OK"),
        # 1800-1900: 3 题（1800 不在 1700-1800，是下一桶下界）
        _make_analysis_submission(6, "F", tags=["graphs"],rating=1800, verdict="OK"),
        _make_analysis_submission(7, "G", tags=["math"],  rating=1825, verdict="WRONG_ANSWER"),
        _make_analysis_submission(8, "H", tags=["dp"],    rating=1899, verdict="OK"),
    ]

    result = analyze_rating_bands(submissions)

    assert "1700-1800" in result, f"Expected 1700-1800 band, got keys: {list(result.keys())}"
    assert "1800-1900" in result, f"Expected 1800-1900 band, got keys: {list(result.keys())}"

    # 1700-1800: total=5, ac=4, wa=1
    b1 = result["1700-1800"]
    assert b1["total"] == 5, f"1700-1800 total=5, got {b1['total']}"
    assert b1["ac"] == 4
    assert b1["wa"] == 1
    assert b1["ac_rate"] == pytest.approx(0.8)

    # 1800-1900: total=3, ac=2, wa=1
    b2 = result["1800-1900"]
    assert b2["total"] == 3
    assert b2["ac"] == 2
    assert b2["wa"] == 1
    assert b2["ac_rate"] == pytest.approx(2 / 3)


def test_empty_bands():
    """中间有空桶（如 2000-2100 无数据）→ 不抛错，空桶不影响其他桶统计"""
    submissions = [
        _make_analysis_submission(1, "A", tags=["math"],  rating=1400, verdict="OK"),
        _make_analysis_submission(2, "B", tags=["dp"],    rating=2500, verdict="OK"),
    ]

    result = analyze_rating_bands(submissions)

    # 空桶不应抛错
    assert "1400-1500" in result, f"Expected 1400-1500 band, got keys: {list(result.keys())}"
    assert "2500-2600" in result, f"Expected 2500-2600 band, got keys: {list(result.keys())}"
    # 空桶索引存在但 total=0
    assert result["1400-1500"]["total"] == 1
    assert result["2500-2600"]["total"] == 1


def test_tag_breakdown():
    """1700-1800 段里 3 道 dp 1 道 math → top tags 是 dp (3) 然后 math (1)"""
    submissions = [
        _make_analysis_submission(1, "A", tags=["dp"],    rating=1750, verdict="OK"),
        _make_analysis_submission(2, "B", tags=["dp"],    rating=1700, verdict="OK"),
        _make_analysis_submission(3, "C", tags=["dp"],    rating=1799, verdict="WRONG_ANSWER"),
        _make_analysis_submission(4, "D", tags=["math"],  rating=1730, verdict="OK"),
    ]

    result = analyze_rating_bands(submissions)

    b = result["1700-1800"]
    assert "top_tags" in b, f"Missing top_tags in bucket: {b}"
    top = b["top_tags"]
    # dp 出现 3 次，math 出现 1 次
    assert len(top) == 2, f"Expected 2 distinct tags, got {len(top)}: {top}"
    assert top[0] == ("dp", 3), f"Expected dp(3) first, got {top[0]}"
    assert top[1] == ("math", 1), f"Expected math(1) second, got {top[1]}"


def test_analysis_empty_submissions():
    """空数据 → 两个函数都返回空 dict / 全零 band，不崩溃"""
    tags_result = analyze_tags([])
    bands_result = analyze_rating_bands([])

    assert tags_result == {}
    assert isinstance(bands_result, dict)
    # 空数据下所有 band 计数为 0（或返回空 dict，二选一均可接受——以实现为准断言不崩溃）
    for band in bands_result.values():
        assert band["total"] == 0


# ── tests: count_contestant_contests（弱点分析场次 guard）───────────────────

from analyzer import count_contestant_contests  # noqa: E402


def test_count_contestant_contests():
    """统计 CONTESTANT 提交覆盖的不同比赛场数"""
    submissions = [
        _make_analysis_submission(1, "A", ["dp"], 1500, "OK", 600, "CONTESTANT"),
        _make_analysis_submission(2, "B", ["dp"], 1500, "OK", 600, "CONTESTANT"),
    ]
    submissions[0]["contestId"] = 100
    submissions[1]["contestId"] = 200

    assert count_contestant_contests(submissions) == 2


def test_count_contestant_contests_dedupes_same_contest():
    """同一比赛的多条提交只算一场"""
    submissions = [
        _make_analysis_submission(1, "A", ["dp"], 1500, "OK", 600, "CONTESTANT"),
        _make_analysis_submission(2, "B", ["dp"], 1500, "WRONG_ANSWER", 700, "CONTESTANT"),
    ]
    # 两条默认 contestId=1
    assert count_contestant_contests(submissions) == 1


def test_count_contestant_contests_excludes_practice_and_none():
    """PRACTICE/VIRTUAL 提交和缺 contestId 的提交不计入"""
    subs = [
        _make_analysis_submission(1, "A", ["dp"], 1500, "OK", 600, "CONTESTANT"),
        _make_analysis_submission(2, "A", ["dp"], 1500, "OK", 600, "PRACTICE"),
        _make_analysis_submission(3, "A", ["dp"], 1500, "OK", 600, "VIRTUAL"),
    ]
    subs[1]["contestId"] = 300  # practice 的另一场：不计
    no_cid = _make_analysis_submission(4, "A", ["dp"], 1500, "OK", 600, "CONTESTANT")
    del no_cid["contestId"]
    subs.append(no_cid)

    assert count_contestant_contests(subs) == 1


def test_count_contestant_contests_empty():
    """空列表 → 0"""
    assert count_contestant_contests([]) == 0
