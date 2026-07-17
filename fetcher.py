import time
from typing import Any

import requests

BASE_URL = "https://codeforces.com/api/"


class CFAPIError(RuntimeError):
    """CF API 返回非 OK 状态时抛出"""
    pass


def cf_api_get(endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """调用 CF API，失败时重试 4 次（最终 3 次重试，指数退避 1s → 2s → 4s）"""
    url = f"{BASE_URL}{endpoint}"
    last_error: Exception | None = None

    for attempt in range(4):
        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if data.get("status") != "OK":
                raise CFAPIError(
                    f"CF API returned FAILED: {data.get('comment', 'no comment')}"
                )

            return data
        except (requests.RequestException, CFAPIError) as e:
            last_error = e
            if attempt < 3:
                wait = 2**attempt  # 1, 2, 4
                time.sleep(wait)

    raise CFAPIError(f"CF API call failed after 4 attempts: {last_error}")


def fetch_contest_list() -> dict[str, Any]:
    """获取所有非 Gym 比赛列表"""
    # 请求间隔 ≥ 1 秒
    time.sleep(1)
    return cf_api_get("contest.list", {"gym": "false"})


def fetch_contest_standings(contest_id: int, handle: str) -> dict[str, Any]:
    """获取指定比赛的 standings 数据（单用户）

    CF API 要求 standings 只能用匿名 GET（仅 contestId 参数，不带 showUnofficial）。
    因此拉取全部排名后在本地筛选目标 handle。
    """
    time.sleep(1)
    response = cf_api_get(
        "contest.standings",
        {"contestId": str(contest_id)},
    )
    result = response["result"]
    # 本地筛选目标 handle（CF API 不允许传递 handles 参数）
    result["rows"] = [
        row for row in result.get("rows", [])
        if any(m.get("handle") == handle for m in row.get("party", {}).get("members", []))
    ]
    return result


def fetch_user_submissions(handle: str, contest_id: int) -> list[dict[str, Any]]:
    """获取用户在某场比赛的正式参赛提交记录

    只保留 participantType == CONTESTANT 的提交——
    赛后补题（PRACTICE）和虚拟参赛（VIRTUAL）共享 contestId，会污染复盘数据。
    """
    time.sleep(1)
    response = cf_api_get(
        "user.status",
        {"handle": handle, "from": "1", "count": "100"},
    )
    submissions = response.get("result", [])
    return [
        s for s in submissions
        if s.get("contestId") == contest_id
        and s.get("author", {}).get("participantType") == "CONTESTANT"
    ]


def fetch_rating_changes(contest_id: int, handle: str) -> dict[str, Any] | None:
    """获取比赛 rating 变化，未找到 handle 时返回 None（未 rated 的比赛）"""
    time.sleep(1)
    response = cf_api_get("contest.ratingChanges", {"contestId": str(contest_id)})
    changes = response.get("result", [])
    for change in changes:
        if change.get("handle") == handle:
            return change
    return None


def fetch_recent_contests(handle: str, count: int = 10) -> list[dict[str, Any]]:
    """获取用户最近 N 场 rated 比赛列表（按时间降序，最新在前）

    调用 CF API user.rating 端点（无需鉴权），返回每条记录：
    contestId, contestName, rank, ratingChange(new-old), date(Unix timestamp)
    """
    time.sleep(1)
    response = cf_api_get("user.rating", {"handle": handle})
    history = response.get("result", [])
    # CF API 返回按时间升序；取最后 count 条后反转
    recent = history[-count:] if len(history) > count else history
    recent.reverse()
    return [
        {
            "contestId": entry["contestId"],
            "contestName": entry["contestName"],
            "rank": entry["rank"],
            "ratingChange": entry["newRating"] - entry["oldRating"],
            "date": entry["ratingUpdateTimeSeconds"],
        }
        for entry in recent
    ]


_PAGE_SIZE = 100  # user.status 每页拉取条数


def fetch_recent_submissions(handle: str, count: int = 500) -> list[dict[str, Any]]:
    """分页拉取用户最近的提交记录（M2-3 弱点分析数据源）

    按需分页：from=1 → from=101 → ... 直到某页返回不足 _PAGE_SIZE 条
    （数据到底）或累计达到 count。每页请求间隔 ≥ 1 秒。
    """
    collected: list[dict[str, Any]] = []
    from_index = 1
    while len(collected) < count:
        time.sleep(1)
        response = cf_api_get(
            "user.status",
            {"handle": handle, "from": str(from_index), "count": str(_PAGE_SIZE)},
        )
        page = response.get("result", [])
        collected.extend(page)
        if len(page) < _PAGE_SIZE:
            break  # 数据到底
        from_index += _PAGE_SIZE
    return collected[:count]


def fetch_problem_tags(contest_id: int) -> dict[str, list[str]]:
    """获取某场比赛的题目 tags 映射 {index: [tags]}（M2-3 弱点分析数据源）"""
    time.sleep(1)
    response = cf_api_get("contest.standings", {"contestId": str(contest_id)})
    problems = response.get("result", {}).get("problems", [])
    return {p.get("index", "?"): p.get("tags", []) for p in problems}
