"""Pure-function data analysis layer for CF contest review data."""

from dataclasses import dataclass
from typing import Any


@dataclass
class Submission:
    """单条提交记录 — CF API user.status 中的一条"""
    id: int
    problem_index: str
    problem_name: str
    verdict: str
    language: str
    memory_bytes: int
    time_millis: int
    creation_time: int


@dataclass
class TimelineEntry:
    """单条提交在时间线中的条目（Submission + solved 标记）"""
    id: int
    problem_index: str
    problem_name: str
    verdict: str
    language: str
    memory_bytes: int
    time_millis: int
    creation_time: int
    solved: bool


@dataclass
class ProblemCodePair:
    """一道题目的 WA→AC 对比对"""
    problem_index: str
    problem_name: str
    wa_submissions: list[TimelineEntry]
    ac_submission: TimelineEntry | None
    failed_attempts: int


@dataclass
class ContestOverview:
    """比赛总览数据"""
    handle: str
    contest_name: str
    rank: int
    old_rating: int
    new_rating: int
    rating_delta: int
    problems_solved: int
    total_problems: int


def build_submissions_from_status(
    status_data: list[dict[str, Any]],
    contest_id: int,
) -> list[Submission]:
    """将 CF user.status 原始数据转为 Submission 列表，按 creation_time 升序（纯函数）"""
    result: list[Submission] = []
    for s in status_data:
        if s.get("contestId") != contest_id:
            continue
        prob = s.get("problem", {})
        result.append(Submission(
            id=s.get("id", 0),
            problem_index=prob.get("index", "?"),
            problem_name=prob.get("name", "Unknown"),
            verdict=s.get("verdict", "UNKNOWN"),
            language=s.get("programmingLanguage", "?"),
            memory_bytes=s.get("memoryConsumedBytes", 0),
            time_millis=s.get("timeConsumedMillis", 0),
            creation_time=s.get("creationTimeSeconds", 0),
        ))
    result.sort(key=lambda s: s.creation_time)
    return result


def calculate_contest_start(standings: dict[str, Any]) -> int:
    """从 standings 中提取比赛开始时间（Unix timestamp）（纯函数）"""
    contest = standings.get("contest", {})
    return contest.get("startTimeSeconds", 0)


def extract_overview(
    standings: dict[str, Any],
    rating_change: dict[str, Any] | None,
    handle: str,
) -> ContestOverview:
    """从 standings 和 ratingChanges 中提取比赛总览（纯函数）"""
    contest = standings.get("contest", {})
    problems = standings.get("problems", [])
    rows = standings.get("rows", [])
    user_row = rows[0] if rows else {}

    problem_results = user_row.get("problemResults", [])
    problems_solved = sum(1 for p in problem_results if p.get("points", 0) > 0)

    rank = user_row.get("rank", 0)

    if rating_change is not None:
        old_rating = rating_change.get("oldRating", 0)
        new_rating = rating_change.get("newRating", 0)
    else:
        old_rating = 0
        new_rating = 0

    return ContestOverview(
        handle=handle,
        contest_name=contest.get("name", f"Contest {contest.get('id', '?')}"),
        rank=rank,
        old_rating=old_rating,
        new_rating=new_rating,
        rating_delta=new_rating - old_rating,
        problems_solved=problems_solved,
        total_problems=len(problems),
    )


def build_timeline(
    submissions: list[Submission],
) -> list[TimelineEntry]:
    """将提交按时间排序，构建时间线条目列表（纯函数）"""
    sorted_subs = sorted(submissions, key=lambda s: s.creation_time)
    return [
        TimelineEntry(
            id=s.id,
            problem_index=s.problem_index,
            problem_name=s.problem_name,
            verdict=s.verdict,
            language=s.language,
            memory_bytes=s.memory_bytes,
            time_millis=s.time_millis,
            creation_time=s.creation_time,
            solved=(s.verdict == "OK"),
        )
        for s in sorted_subs
    ]


def extract_wa_ac_pairs(
    timeline: list[TimelineEntry],
) -> list[ProblemCodePair]:
    """从时间线中提取有 WA→AC 过程的题目对（至少 1 次 WA 后 AC）（纯函数）"""
    # 按 problem_index 分组
    groups: dict[str, list[TimelineEntry]] = {}
    for entry in timeline:
        groups.setdefault(entry.problem_index, []).append(entry)

    pairs: list[ProblemCodePair] = []
    for idx, entries in groups.items():
        wa_subs = [e for e in entries if e.verdict == "WRONG_ANSWER"]
        ac_sub = next((e for e in entries if e.verdict == "OK"), None)

        # 只返回有至少 1 次 WA 且最终 AC 的题目
        if wa_subs and ac_sub is not None:
            pairs.append(ProblemCodePair(
                problem_index=idx,
                problem_name=entries[0].problem_name,
                wa_submissions=wa_subs,
                ac_submission=ac_sub,
                failed_attempts=len(wa_subs),
            ))

    return pairs
