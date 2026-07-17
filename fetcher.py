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
    # 本地筛选目标 handle（CF API 不允许传递 handles 参数）；CF handle 大小写不敏感
    target = handle.casefold()
    result["rows"] = [
        row for row in result.get("rows", [])
        if any(
            m.get("handle", "").casefold() == target
            for m in row.get("party", {}).get("members", [])
        )
    ]
    return result


# 分页保护上限：无 contest_start 时最多扫描的提交条数（避免高产用户无止境翻页）
_MAX_SCAN = 1000


def fetch_user_submissions(
    handle: str,
    contest_id: int,
    contest_start: int = 0,
) -> list[dict[str, Any]]:
    """获取用户在某场比赛的正式参赛提交记录（分页拉取）

    只保留 participantType == CONTESTANT 的提交——
    赛后补题（PRACTICE）和虚拟参赛（VIRTUAL）共享 contestId，会污染复盘数据。

    分页终止条件（user.status 按时间降序返回）：
    1. 短页 → 数据到底
    2. 整页提交都早于 contest_start → 更早的页不会再有该场比赛的提交
    3. 扫描量达到 _MAX_SCAN → 保护上限（仅在 contest_start=0 时可能触发）
    """
    matched: list[dict[str, Any]] = []
    from_index = 1
    while True:
        time.sleep(1)
        response = cf_api_get(
            "user.status",
            {"handle": handle, "from": str(from_index), "count": str(_PAGE_SIZE)},
        )
        page = response.get("result", [])
        matched.extend(
            s for s in page
            if s.get("contestId") == contest_id
            and s.get("author", {}).get("participantType") == "CONTESTANT"
        )
        if len(page) < _PAGE_SIZE:
            break  # 数据到底
        if contest_start and min(
            s.get("creationTimeSeconds", 0) for s in page
        ) < contest_start:
            break  # 已越过该场比赛的时间范围
        from_index += _PAGE_SIZE
        if from_index > _MAX_SCAN:
            break  # 保护上限
    return matched


def fetch_rating_changes(contest_id: int, handle: str) -> dict[str, Any] | None:
    """获取比赛 rating 变化，未找到 handle 时返回 None（未 rated 的比赛）"""
    time.sleep(1)
    response = cf_api_get("contest.ratingChanges", {"contestId": str(contest_id)})
    changes = response.get("result", [])
    # CF handle 大小写不敏感
    target = handle.casefold()
    for change in changes:
        if change.get("handle", "").casefold() == target:
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
    # CF API 返回按时间升序；切片总是产生副本（避免原地 reverse 污染 response），再反转
    recent = history[-count:]
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
