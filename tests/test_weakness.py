"""Tests for M2-3 weakness-analysis data layer — paginated fetch + tag extraction."""

import pytest
from fetcher import CFAPIError, fetch_problem_tags, fetch_recent_submissions

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


# ── tests: fetch_problem_tags（题目 tags 映射）──────────────────────────────


def test_fetch_problem_tags(mocker):
    """从 contest.standings 提取 {index: [tags]} 映射"""
    response = {
        "status": "OK",
        "result": {
            "contest": {"id": 1, "name": "CF Round #1"},
            "problems": [
                {"contestId": 1, "index": "A", "name": "Theatre Square",
                 "rating": 1000, "tags": ["math"]},
                {"contestId": 1, "index": "B", "name": "Spreadsheet",
                 "rating": 1600, "tags": ["implementation", "math"]},
                {"contestId": 1, "index": "C", "name": "Graph",
                 "rating": 1900, "tags": ["dfs and similar", "graphs"]},
            ],
            "rows": [],
        },
    }
    mock = mocker.patch("fetcher.cf_api_get", return_value=response)
    mocker.patch("fetcher.time.sleep")

    result = fetch_problem_tags(contest_id=1)

    assert result == {
        "A": ["math"],
        "B": ["implementation", "math"],
        "C": ["dfs and similar", "graphs"],
    }
    mock.assert_called_once_with("contest.standings", {"contestId": "1"})


def test_fetch_problem_tags_missing_tags(mocker):
    """题目缺少 tags 字段 → 该题映射为空列表，不崩溃"""
    response = {
        "status": "OK",
        "result": {
            "contest": {"id": 2, "name": "CF Round #2"},
            "problems": [
                {"contestId": 2, "index": "A", "name": "No Tags Problem"},
            ],
            "rows": [],
        },
    }
    mocker.patch("fetcher.cf_api_get", return_value=response)
    mocker.patch("fetcher.time.sleep")

    result = fetch_problem_tags(contest_id=2)

    assert result == {"A": []}


def test_fetch_problem_tags_handles_api_error(mocker):
    """CFAPIError 透传"""
    mocker.patch("fetcher.cf_api_get", side_effect=CFAPIError("CF API returned FAILED"))
    mocker.patch("fetcher.time.sleep")

    with pytest.raises(CFAPIError, match="CF API returned FAILED"):
        fetch_problem_tags(contest_id=9999999)
