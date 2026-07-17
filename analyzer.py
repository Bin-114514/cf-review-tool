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


def build_timeline(
    submissions: list[Submission],
    problems: list[dict[str, Any]],
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
