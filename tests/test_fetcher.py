import pytest
from fetcher import (
    CFAPIError,
    cf_api_get,
    fetch_contest_list,
    fetch_contest_standings,
    fetch_rating_changes,
    fetch_user_submissions,
)


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def standings_response() -> dict:
    """模拟 contest.standings?contestId=1&handles=tourist 的 CF 响应"""
    return {
        "status": "OK",
        "result": {
            "contest": {
                "id": 1,
                "name": "Codeforces Beta Round #1",
                "type": "CF",
                "phase": "FINISHED",
                "frozen": False,
                "durationSeconds": 7200,
                "startTimeSeconds": 1263849600,
            },
            "problems": [
                {"index": "A", "name": "Theatre Square", "rating": 1000, "tags": ["math"]},
                {"index": "B", "name": "Spreadsheet", "rating": 1600, "tags": ["implementation"]},
            ],
            "rows": [
                {
                    "party": {
                        "contestId": 1,
                        "members": [{"handle": "tourist", "name": None}],
                        "participantType": "CONTESTANT",
                        "ghost": False,
                        "room": 42,
                        "startTimeSeconds": 1263849600,
                    },
                    "rank": 1,
                    "points": 1000.0,
                    "penalty": 0,
                    "successfulHackCount": 0,
                    "unsuccessfulHackCount": 0,
                    "problemResults": [
                        {"points": 500.0, "rejectedAttemptCount": 0, "type": "FINAL", "bestSubmissionTimeSeconds": 180},
                        {"points": 500.0, "rejectedAttemptCount": 2, "type": "FINAL", "bestSubmissionTimeSeconds": 1200},
                    ],
                }
            ],
        },
    }


@pytest.fixture
def submissions_response() -> dict:
    """模拟 user.status?handle=tourist 的 CF 响应"""
    return {
        "status": "OK",
        "result": [
            {
                "id": 1001, "contestId": 1, "creationTimeSeconds": 1263849780, "relativeTimeSeconds": 180,
                "problem": {"contestId": 1, "index": "A", "name": "Theatre Square", "rating": 1000, "tags": ["math"]},
                "author": {"contestId": 1, "members": [{"handle": "tourist"}]},
                "programmingLanguage": "C++17 (GCC 7-32)", "verdict": "OK",
                "testset": "TESTS", "passedTestCount": 10, "timeConsumedMillis": 15, "memoryConsumedBytes": 262144,
            },
            {
                "id": 1002, "contestId": 1, "creationTimeSeconds": 1263849960, "relativeTimeSeconds": 360,
                "problem": {"contestId": 1, "index": "B", "name": "Spreadsheet", "rating": 1600, "tags": ["implementation"]},
                "author": {"contestId": 1, "members": [{"handle": "tourist"}]},
                "programmingLanguage": "C++17 (GCC 7-32)", "verdict": "WRONG_ANSWER",
                "testset": "TESTS", "passedTestCount": 5, "timeConsumedMillis": 30, "memoryConsumedBytes": 524288,
            },
        ],
    }


@pytest.fixture
def submissions_multi_contest() -> dict:
    """user.status 返回多个比赛的数据，用于验证 contestId 过滤"""
    return {
        "status": "OK",
        "result": [
            {
                "id": 1001, "contestId": 1, "creationTimeSeconds": 1263849780, "relativeTimeSeconds": 180,
                "problem": {"contestId": 1, "index": "A", "name": "Theatre Square", "rating": 1000, "tags": ["math"]},
                "author": {"contestId": 1, "members": [{"handle": "tourist"}]},
                "programmingLanguage": "C++17 (GCC 7-32)", "verdict": "OK",
                "testset": "TESTS", "passedTestCount": 10, "timeConsumedMillis": 15, "memoryConsumedBytes": 262144,
            },
            {
                "id": 2001, "contestId": 2, "creationTimeSeconds": 1264000000, "relativeTimeSeconds": 600,
                "problem": {"contestId": 2, "index": "A", "name": "Another Problem", "rating": 1200, "tags": ["dp"]},
                "author": {"contestId": 2, "members": [{"handle": "tourist"}]},
                "programmingLanguage": "Python 3", "verdict": "OK",
                "testset": "TESTS", "passedTestCount": 8, "timeConsumedMillis": 50, "memoryConsumedBytes": 131072,
            },
        ],
    }


@pytest.fixture
def rating_changes_response() -> dict:
    """模拟 contest.ratingChanges?contestId=1 的 CF 响应"""
    return {
        "status": "OK",
        "result": [
            {"contestId": 1, "contestName": "Codeforces Beta Round #1", "handle": "tourist",
             "rank": 1, "oldRating": 2600, "newRating": 2680, "ratingUpdateTimeSeconds": 1263850000},
            {"contestId": 1, "contestName": "Codeforces Beta Round #1", "handle": "other_user",
             "rank": 2, "oldRating": 2400, "newRating": 2450, "ratingUpdateTimeSeconds": 1263850000},
        ],
    }


# ── tests: cf_api_get (existing) ──────────────────────────────────────────────


def test_api_connectivity():
    """验证 CF API 可达且返回合法数据"""
    data = fetch_contest_list()
    assert data["status"] == "OK"
    assert isinstance(data["result"], list)
    assert len(data["result"]) > 0


# ── tests: cf_api_get retry ───────────────────────────────────────────────────


def test_cf_api_get_retry_logic(mocker):
    """cf_api_get: 3 次 ConnectionError 后第 4 次成功（4 次总尝试）"""
    import requests as req
    fake_response = mocker.MagicMock()
    fake_response.json.return_value = {"status": "OK", "result": [1, 2, 3]}
    fake_response.raise_for_status.return_value = None

    mock_get = mocker.patch("fetcher.requests.get")
    mock_sleep = mocker.patch("fetcher.time.sleep")

    mock_get.side_effect = [
        req.ConnectionError("timeout"),
        req.ConnectionError("timeout"),
        req.ConnectionError("timeout"),
        fake_response,
    ]

    result = cf_api_get("contest.list", {"gym": "false"})

    assert mock_get.call_count == 4
    assert mock_sleep.call_count == 3  # 1s, 2s, 4s
    assert result == {"status": "OK", "result": [1, 2, 3]}


def test_cf_api_get_exhausts_retries(mocker):
    """cf_api_get: 4 次全部失败时抛出 CFAPIError"""
    import requests as req
    mocker.patch("fetcher.requests.get", side_effect=req.ConnectionError("always down"))
    mocker.patch("fetcher.time.sleep")

    with pytest.raises(CFAPIError, match="CF API call failed after 4 attempts"):
        cf_api_get("contest.list")


def test_cf_api_get_bad_status(mocker):
    """CF API 返回 status != OK 时经重试后抛 CFAPIError"""
    fake_response = mocker.MagicMock()
    fake_response.json.return_value = {"status": "FAILED", "comment": "contest not found"}
    fake_response.raise_for_status.return_value = None

    mocker.patch("fetcher.requests.get", return_value=fake_response)
    mocker.patch("fetcher.time.sleep")

    with pytest.raises(CFAPIError, match="CF API call failed after 4 attempts"):
        cf_api_get("contest.standings", {"contestId": "9999999"})


# ── tests: fetch_contest_standings ────────────────────────────────────────────


def test_fetch_contest_standings_returns_result(mocker, standings_response):
    """返回 result 字典，包含 contest / problems / rows"""
    mock = mocker.patch("fetcher.cf_api_get", return_value=standings_response)

    result = fetch_contest_standings(contest_id=1, handle="tourist")

    assert "contest" in result
    assert "problems" in result
    assert "rows" in result
    assert result["contest"]["id"] == 1
    assert len(result["problems"]) == 2
    assert result["rows"][0]["rank"] == 1
    mock.assert_called_once_with(
        "contest.standings",
        {"contestId": "1"},
    )


def test_fetch_contest_standings_handles_api_error(mocker):
    """CFAPIError 透传"""
    mocker.patch("fetcher.cf_api_get", side_effect=CFAPIError("CF API returned FAILED"))

    with pytest.raises(CFAPIError, match="CF API returned FAILED"):
        fetch_contest_standings(contest_id=9999999, handle="nonexistent")


# ── tests: fetch_user_submissions ─────────────────────────────────────────────


def test_fetch_user_submissions_filters_by_contest(mocker, submissions_response):
    """返回该比赛的所有提交"""
    mock = mocker.patch("fetcher.cf_api_get", return_value=submissions_response)

    result = fetch_user_submissions(handle="tourist", contest_id=1)

    assert isinstance(result, list)
    assert len(result) == 2
    assert all(s["contestId"] == 1 for s in result)
    mock.assert_called_once_with(
        "user.status",
        {"handle": "tourist", "from": "1", "count": "100"},
    )


def test_fetch_user_submissions_excludes_other_contests(mocker, submissions_multi_contest):
    """只返回目标 contestId 的提交"""
    mocker.patch("fetcher.cf_api_get", return_value=submissions_multi_contest)

    result = fetch_user_submissions(handle="tourist", contest_id=1)

    assert len(result) == 1
    assert result[0]["contestId"] == 1
    assert result[0]["problem"]["name"] == "Theatre Square"


def test_fetch_user_submissions_empty_for_missing_contest(mocker):
    """用户未参加目标 contestId → 返回空列表"""
    response = {
        "status": "OK",
        "result": [{
            "id": 3001, "contestId": 999, "creationTimeSeconds": 1264000000, "relativeTimeSeconds": 600,
            "problem": {"contestId": 999, "index": "C", "name": "Some Problem", "rating": 2000, "tags": ["math"]},
            "author": {"contestId": 999, "members": [{"handle": "tourist"}]},
            "programmingLanguage": "C++17", "verdict": "OK",
            "testset": "TESTS", "passedTestCount": 20, "timeConsumedMillis": 25, "memoryConsumedBytes": 65536,
        }],
    }
    mocker.patch("fetcher.cf_api_get", return_value=response)

    result = fetch_user_submissions(handle="tourist", contest_id=1)

    assert result == []


def test_fetch_user_submissions_handles_api_error(mocker):
    """CFAPIError 透传"""
    mocker.patch("fetcher.cf_api_get", side_effect=CFAPIError("CF API returned FAILED"))

    with pytest.raises(CFAPIError, match="CF API returned FAILED"):
        fetch_user_submissions(handle="tourist", contest_id=1)


# ── tests: fetch_rating_changes ───────────────────────────────────────────────


def test_fetch_rating_changes_returns_match(mocker, rating_changes_response):
    """找到 handle 时返回该 ratingChange 对象"""
    mock = mocker.patch("fetcher.cf_api_get", return_value=rating_changes_response)

    result = fetch_rating_changes(contest_id=1, handle="tourist")

    assert result is not None
    assert result["handle"] == "tourist"
    assert result["oldRating"] == 2600
    assert result["newRating"] == 2680
    mock.assert_called_once_with(
        "contest.ratingChanges",
        {"contestId": "1"},
    )


def test_fetch_rating_changes_returns_none_for_missing_handle(mocker):
    """handle 不在 ratingChanges 中 → 返回 None"""
    response = {
        "status": "OK",
        "result": [{"contestId": 1, "handle": "someone_else", "rank": 5, "oldRating": 1500, "newRating": 1550}],
    }
    mocker.patch("fetcher.cf_api_get", return_value=response)

    result = fetch_rating_changes(contest_id=1, handle="tourist")

    assert result is None


def test_fetch_rating_changes_empty_result(mocker):
    """ratingChanges 为空列表 → 返回 None（未 rated 的比赛）"""
    mocker.patch("fetcher.cf_api_get", return_value={"status": "OK", "result": []})

    result = fetch_rating_changes(contest_id=9999999, handle="tourist")

    assert result is None


def test_fetch_rating_changes_handles_api_error(mocker):
    """CFAPIError 透传"""
    mocker.patch("fetcher.cf_api_get", side_effect=CFAPIError("CF API returned FAILED"))

    with pytest.raises(CFAPIError, match="CF API returned FAILED"):
        fetch_rating_changes(contest_id=1, handle="tourist")


# ── tests: fetch_contest_list ─────────────────────────────────────────────────


def test_fetch_contest_list_params(mocker):
    """fetch_contest_list 传递正确的查询参数"""
    fake_response = {"status": "OK", "result": [{"id": 1, "name": "Test"}]}
    mock = mocker.patch("fetcher.cf_api_get", return_value=fake_response)

    result = fetch_contest_list()

    mock.assert_called_once_with("contest.list", {"gym": "false"})
    assert result == fake_response


# ── tests: return type verification ───────────────────────────────────────────


def test_fetch_contest_standings_return_type(standings_response, mocker):
    """验证返回值是 dict"""
    mocker.patch("fetcher.cf_api_get", return_value=standings_response)
    result = fetch_contest_standings(1, "tourist")
    assert isinstance(result, dict)


def test_fetch_user_submissions_return_type(submissions_response, mocker):
    """验证返回值是 list"""
    mocker.patch("fetcher.cf_api_get", return_value=submissions_response)
    result = fetch_user_submissions("tourist", 1)
    assert isinstance(result, list)


def test_fetch_rating_changes_return_type(mocker):
    """验证未找到时返回 None"""
    mocker.patch("fetcher.cf_api_get", return_value={"status": "OK", "result": []})
    result = fetch_rating_changes(1, "tourist")
    assert result is None
