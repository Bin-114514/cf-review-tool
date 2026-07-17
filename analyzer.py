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


# ── M2-2: 启发式复盘摘要（纯规则引擎，零外部 API 依赖）─────────────────────────
#
# 所有规则签名统一为 (overview, timeline, pairs, contest_start) -> str | None。
# contest_start=0 时回退到"首提交时间"锚点（向后兼容）；
# 传入真实比赛开始时间（calculate_contest_start）可获得准确罚时/速度计算。


def _group_by_problem(timeline: list[TimelineEntry]) -> dict[str, list[TimelineEntry]]:
    """按 problem_index 分组时间线条目（纯函数）"""
    groups: dict[str, list[TimelineEntry]] = {}
    for e in timeline:
        groups.setdefault(e.problem_index, []).append(e)
    return groups


def _heaviest_penalty(
    overview: ContestOverview,
    timeline: list[TimelineEntry],
    pairs: list[ProblemCodePair],
    contest_start: int = 0,
) -> str | None:
    """找出罚时占比最大的 WA 过的题目（CF 罚时 = AC 距开赛时间 + WA 次数 × 10min）"""
    if not pairs:
        return None
    total_penalty_seconds = 0
    per_problem: list[tuple[str, int, int]] = []  # (label, penalty_seconds, wa_count)
    for idx, entries in _group_by_problem(timeline).items():
        ac = next((e for e in entries if e.verdict == "OK"), None)
        if ac is None:
            continue
        wa_count = sum(
            1 for e in entries
            if e.verdict == "WRONG_ANSWER" and e.creation_time < ac.creation_time
        )
        # 锚点：优先用比赛开始时间；缺失时退回该题首次提交时间
        anchor = contest_start if contest_start > 0 else entries[0].creation_time
        penalty_seconds = (ac.creation_time - anchor) + wa_count * 600
        total_penalty_seconds += penalty_seconds
        if wa_count > 0:
            per_problem.append((idx, penalty_seconds, wa_count))
    if total_penalty_seconds == 0 or not per_problem:
        return None
    heaviest = max(per_problem, key=lambda x: x[1])
    idx, penalty_s, wa_c = heaviest
    # 秒级累加后一次除法，避免先取整的精度损失
    pct = penalty_s / total_penalty_seconds * 100
    return f"🏅 最重罚时题：{idx} 题 {wa_c} 次 WA，罚时约 {penalty_s // 60}min，占总罚时 {pct:.0f}%"


def _speed_tier(
    overview: ContestOverview,
    timeline: list[TimelineEntry],
    pairs: list[ProblemCodePair],
    contest_start: int = 0,
) -> str | None:
    """前 30min 内 AC 的题数统计（锚点：比赛开始时间，缺失时退回首提交）"""
    if not timeline:
        return None
    anchor = contest_start if contest_start > 0 else timeline[0].creation_time
    ac_labels: list[str] = []
    seen: set[str] = set()
    for e in timeline:
        if e.verdict == "OK" and e.problem_index not in seen:
            if e.creation_time - anchor <= 1800:  # 30min
                seen.add(e.problem_index)
                ac_labels.append(e.problem_index)
    if not ac_labels:
        return None
    labels_str = "、".join(ac_labels)
    return f"⚡ 速度档位：前 30min 内 AC {len(ac_labels)} 题（{labels_str}），开局状态火热"


def _wa_density(
    overview: ContestOverview,
    timeline: list[TimelineEntry],
    pairs: list[ProblemCodePair],
    contest_start: int = 0,
) -> str | None:
    """WA 次数 ≥ 3 的所有题目 → 警告"""
    if not timeline:
        return None
    heavy: list[str] = []
    for idx, entries in _group_by_problem(timeline).items():
        wa_count = sum(1 for e in entries if e.verdict == "WRONG_ANSWER")
        if wa_count >= 3:
            heavy.append(f"{idx} 题 {wa_count} 次 WA")
    if not heavy:
        return None
    return f"⚠️ WA 密度：{'、'.join(heavy)}，建议赛后重点复盘"


def _one_shot_ac_praise(
    overview: ContestOverview,
    timeline: list[TimelineEntry],
    pairs: list[ProblemCodePair],
    contest_start: int = 0,
) -> str | None:
    """只有 1 条提交且 AC 的题目 → 表扬（一发 AC，非 CF 全场一血含义）"""
    if not timeline:
        return None
    clean: list[str] = []
    for idx, entries in _group_by_problem(timeline).items():
        if len(entries) == 1 and entries[0].verdict == "OK":
            clean.append(idx)
    if not clean:
        return None
    labels_str = "、".join(clean)
    return f"✨ 一次通过：{labels_str} 题一发 AC，干净利落"


def _unsolved_warning(
    overview: ContestOverview,
    timeline: list[TimelineEntry],
    pairs: list[ProblemCodePair],
    contest_start: int = 0,
) -> str | None:
    """有提交但零 AC 的题目 → 警告"""
    if not timeline:
        return None
    unsolved: list[str] = []
    for idx, entries in _group_by_problem(timeline).items():
        if not any(e.verdict == "OK" for e in entries):
            unsolved.append(f"{idx}({len(entries)}次)")
    if not unsolved:
        return None
    labels_str = "、".join(unsolved)
    return f"🚫 未 AC 警告：{labels_str} 有提交但未通过，建议对照题解复查"


def _efficiency_trend(
    overview: ContestOverview,
    timeline: list[TimelineEntry],
    pairs: list[ProblemCodePair],
    contest_start: int = 0,
) -> str | None:
    """按 AC 顺序计算相邻 AC 时间间隔，判断放缓趋势"""
    if not timeline:
        return None
    ac_times: list[tuple[str, int]] = []
    seen: set[str] = set()
    for e in timeline:
        if e.verdict == "OK" and e.problem_index not in seen:
            seen.add(e.problem_index)
            ac_times.append((e.problem_index, e.creation_time))
    if len(ac_times) < 3:  # 至少 3 道 AC 才有前后半段可比
        return None
    gaps = [
        (ac_times[i][1] - ac_times[i - 1][1]) // 60
        for i in range(1, len(ac_times))
    ]
    first_half_avg = sum(gaps[:len(gaps) // 2]) / (len(gaps) // 2)
    second_half_avg = sum(gaps[len(gaps) // 2:]) / (len(gaps) - len(gaps) // 2)
    # 最小间隔阈值：前半段平均 < 1min 时（间隔取整为 0），不足以判断趋势
    if first_half_avg < 1:
        return None
    if second_half_avg > first_half_avg * 1.5:
        details = "、".join(
            f"{ac_times[i - 1][0]}→{ac_times[i][0]} {g}min"
            for i, g in enumerate(gaps, 1) if g > 0
        )
        return (
            f"📈 效率趋势：后期解题速度放缓（{details}），"
            f"后半段平均间隔 {second_half_avg:.0f}min > 前半段 {first_half_avg:.0f}min"
        )
    return None


def generate_insights(
    overview: ContestOverview,
    timeline: list[TimelineEntry],
    pairs: list[ProblemCodePair],
    contest_start: int = 0,
) -> list[str]:
    """生成多条中文比赛洞察（纯规则引擎，不调 API）

    contest_start 建议传入 calculate_contest_start(standings)；
    为 0 时罚时/速度锚点退回首提交时间（向后兼容）。
    """
    # 按重要性排序：罚时 > 速度 > 一发 AC > 其他
    rules = [
        _heaviest_penalty,
        _speed_tier,
        _one_shot_ac_praise,
        _wa_density,
        _unsolved_warning,
        _efficiency_trend,
    ]
    results: list[str] = []
    for rule in rules:
        insight = rule(overview, timeline, pairs, contest_start)
        if insight is not None:
            results.append(insight)
    return results


# ── M2-3b: 弱点识别 — 多场提交交叉分析（纯函数）──────────────────────────────
#
# 输入为 CF user.status 原始 dict（而非 Submission dataclass），
# 因为 participantType 过滤需要 author 字段。


def _blank_stats() -> dict[str, Any]:
    """单个统计桶的初始值"""
    return {"total": 0, "ac": 0, "wa": 0, "ac_rate": 0.0, "avg_time": 0.0}


def _finalize_stats(bucket: dict[str, Any], ac_times: list[int]) -> None:
    """计算派生指标：ac_rate 和 avg_time（AC 提交的平均 relativeTimeSeconds）"""
    if bucket["total"] > 0:
        bucket["ac_rate"] = bucket["ac"] / bucket["total"]
    if ac_times:
        bucket["avg_time"] = sum(ac_times) / len(ac_times)


def _is_contestant(submission: dict[str, Any]) -> bool:
    """只统计正式参赛（rated）的提交"""
    return submission.get("author", {}).get("participantType") == "CONTESTANT"


def analyze_tags(
    submissions: list[dict[str, Any]],
    tags_map: dict[str, list[str]],
) -> dict[str, dict[str, Any]]:
    """按题目 tag 交叉统计提交表现（纯函数）

    返回 {tag: {total, ac, wa, ac_rate, avg_time}}。
    tags 查找顺序：tags_map[index] 优先，缺失时回退提交内联的 problem.tags。
    avg_time = AC 提交的平均 relativeTimeSeconds（距开赛秒数）。
    """
    stats: dict[str, dict[str, Any]] = {}
    ac_times: dict[str, list[int]] = {}
    for s in submissions:
        if not _is_contestant(s):
            continue
        problem = s.get("problem", {})
        index = problem.get("index", "?")
        tags = tags_map.get(index) or problem.get("tags", [])
        verdict = s.get("verdict", "UNKNOWN")
        for tag in tags:
            bucket = stats.setdefault(tag, _blank_stats())
            bucket["total"] += 1
            if verdict == "OK":
                bucket["ac"] += 1
                ac_times.setdefault(tag, []).append(s.get("relativeTimeSeconds", 0))
            elif verdict == "WRONG_ANSWER":
                bucket["wa"] += 1
    for tag, bucket in stats.items():
        _finalize_stats(bucket, ac_times.get(tag, []))
    return stats


# rating 分段边界：左闭右开，[下界, 上界)
_RATING_BANDS: list[tuple[str, int, int]] = [
    ("<1400", 0, 1400),
    ("1400-1600", 1400, 1600),
    ("1600-1900", 1600, 1900),
    ("1900+", 1900, 10**9),
]


def analyze_rating_bands(
    submissions: list[dict[str, Any]],
    tags_map: dict[str, list[str]],
) -> dict[str, dict[str, Any]]:
    """按题目 rating 分段统计提交表现（纯函数）

    分段：<1400, 1400-1600, 1600-1900, 1900+（左闭右开）。
    无 rating 的题目跳过。返回 {band: {total, ac, wa, ac_rate, avg_time}}。
    """
    stats: dict[str, dict[str, Any]] = {name: _blank_stats() for name, _, _ in _RATING_BANDS}
    ac_times: dict[str, list[int]] = {name: [] for name, _, _ in _RATING_BANDS}
    for s in submissions:
        if not _is_contestant(s):
            continue
        rating = s.get("problem", {}).get("rating")
        if rating is None:
            continue
        band = next(
            (name for name, lo, hi in _RATING_BANDS if lo <= rating < hi),
            None,
        )
        if band is None:
            continue
        verdict = s.get("verdict", "UNKNOWN")
        bucket = stats[band]
        bucket["total"] += 1
        if verdict == "OK":
            bucket["ac"] += 1
            ac_times[band].append(s.get("relativeTimeSeconds", 0))
        elif verdict == "WRONG_ANSWER":
            bucket["wa"] += 1
    for band, bucket in stats.items():
        _finalize_stats(bucket, ac_times[band])
    return stats


def count_contestant_contests(submissions: list[dict[str, Any]]) -> int:
    """统计 CONTESTANT 提交覆盖的不同比赛场数（纯函数，弱点分析数据量 guard）"""
    return len({
        s["contestId"]
        for s in submissions
        if _is_contestant(s) and s.get("contestId") is not None
    })
