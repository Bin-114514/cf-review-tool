# CF Review Tool - 赛后复盘工具
"""
Streamlit 主页面 — 侧边栏输入 + 三 Tab 展示（比赛总览 / 逐题复盘 / WA→AC 对比）。
只负责 UI 组装，不包含业务逻辑或 API 调用。
"""

import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from analyzer import (
    ContestOverview,
    ProblemCodePair,
    Submission,
    TimelineEntry,
    build_submissions_from_status,
    build_timeline,
    extract_overview,
    extract_wa_ac_pairs,
    calculate_contest_start,
)
from fetcher import (
    CFAPIError,
    fetch_contest_standings,
    fetch_rating_changes,
    fetch_user_submissions,
)


# ── constants ─────────────────────────────────────────────────────────────────

RANKING = ["Newbie", "Pupil", "Specialist", "Expert",
           "Candidate Master", "Master", "International Master",
           "Grandmaster", "International Grandmaster",
           "Legendary Grandmaster"]


# ── helpers ───────────────────────────────────────────────────────────────────


def _rating_to_rank(rating: int) -> str:
    if rating < 1200:
        return "Newbie"
    if rating < 1400:
        return "Pupil"
    if rating < 1600:
        return "Specialist"
    if rating < 1900:
        return "Expert"
    if rating < 2100:
        return "Candidate Master"
    if rating < 2200:
        return "Master"
    if rating < 2300:
        return "International Master"
    if rating < 2400:
        return "Grandmaster"
    if rating < 3000:
        return "International Grandmaster"
    return "Legendary Grandmaster"


def _format_duration(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s"


def _verdict_color(verdict: str) -> str:
    return {
        "OK": "#28A745",
        "WRONG_ANSWER": "#D4A017",
        "TIME_LIMIT_EXCEEDED": "#DC3545",
        "RUNTIME_ERROR": "#DC3545",
        "COMPILATION_ERROR": "#DC3545",
        "MEMORY_LIMIT_EXCEEDED": "#DC3545",
    }.get(verdict, "#888888")


def _verdict_label(verdict: str) -> str:
    short = {
        "OK": "AC",
        "WRONG_ANSWER": "WA",
        "TIME_LIMIT_EXCEEDED": "TLE",
        "RUNTIME_ERROR": "RE",
        "COMPILATION_ERROR": "CE",
        "MEMORY_LIMIT_EXCEEDED": "MLE",
    }
    return short.get(verdict, verdict)


# ── tab: 比赛总览 ─────────────────────────────────────────────────────────────


def _render_overview_tab(overview: ContestOverview, duration_seconds: int):
    """展示比赛总览卡片"""
    # 比赛名称 + 时长
    st.markdown(f"### {overview.contest_name}")
    if duration_seconds > 0:
        st.caption(f"Duration · {_format_duration(duration_seconds)}")

    # 四枚 metric 卡片等宽分布
    c1, c2, c3, c4 = st.columns(4)
    rank_title = f"#{overview.rank}" if overview.rank else "—"
    with c1:
        st.metric("Rank", rank_title)
    with c2:
        st.metric("Old Rating", str(overview.old_rating) if overview.old_rating else "Unrated")
    with c3:
        delta_str = f"{overview.rating_delta:+d}" if overview.rating_delta else None
        st.metric("New Rating", str(overview.new_rating) if overview.new_rating else "Unrated",
                  delta=delta_str)
    with c4:
        st.metric("Solved", f"{overview.problems_solved}/{overview.total_problems}")

    # Rating 称号
    if overview.new_rating:
        rank_label = _rating_to_rank(overview.new_rating)
        st.caption(f"Rank: **{rank_label}**")

    # 解题完成度进度条
    if overview.total_problems > 0:
        pct = overview.problems_solved / overview.total_problems
        st.progress(pct, f"{pct:.0%} problems solved")


# ── tab: 逐题复盘 ─────────────────────────────────────────────────────────────


def _render_timeline_tab(timeline: list[TimelineEntry]):
    """用 st.dataframe + column_config 展示逐题提交矩阵"""
    if not timeline:
        st.info("No submissions found for this contest.")
        return

    # 构建渲染用的数据行
    rows: list[dict] = []
    for entry in timeline:
        rows.append({
            "Problem": f"{entry.problem_index} · {entry.problem_name}",
            "Verdict": _verdict_label(entry.verdict),
            "Language": entry.language,
            "Time": f"{entry.time_millis} ms",
            "Memory": f"{entry.memory_bytes // 1024} KB",
            "Submitted": datetime.fromtimestamp(entry.creation_time, tz=timezone.utc).strftime("%H:%M:%S"),
            "_color": _verdict_color(entry.verdict),
            "_solved": entry.solved,
        })

    df = pd.DataFrame(rows)

    # styled dataframe
    styled = df.style.applymap(
        lambda v, row: f"background-color: {row['_color']}; color: {'#000' if row['_color'] == '#D4A017' else '#fff'}; font-weight: bold",
        subset=["Verdict"],
    )

    st.dataframe(
        styled,
        column_order=["Problem", "Verdict", "Language", "Time", "Memory", "Submitted"],
        column_config={
            "Problem": "Problem",
            "Verdict": st.column_config.TextColumn("Verdict", width="small"),
            "Language": st.column_config.TextColumn("Language", width="medium"),
            "Time": st.column_config.TextColumn("Time", width="small"),
            "Memory": st.column_config.TextColumn("Memory", width="small"),
            "Submitted": st.column_config.TextColumn("Submitted", width="small"),
        },
        use_container_width=True,
        hide_index=True,
    )


# ── tab: WA → AC 对比 ────────────────────────────────────────────────────────


def _render_wa_ac_tab(pairs: list[ProblemCodePair], timeline: list[TimelineEntry]):
    """展示有 WA→AC 过程的题目对比（WA 按时间倒序，左侧 WA 右侧 AC）"""
    if not pairs:
        # 统计一次通过率
        groups: dict[str, list[TimelineEntry]] = {}
        for e in timeline:
            groups.setdefault(e.problem_index, []).append(e)
        first_try = sum(1 for g in groups.values() if len(g) == 1 and g[0].solved)
        total = len(groups) if groups else 0
        st.info(
            f"This contest has no 'WA → AC' problems.\n\n"
            f"First-try solve rate: **{first_try}/{total}**"
        )
        return

    st.caption("Only problems with at least 1 WA attempt and a final AC are shown. "
               "First-try AC problems are excluded.")

    for pair in pairs:
        st.markdown(f"### {pair.problem_index} · {pair.problem_name}")

        left, right = st.columns([1, 1])

        with left:
            st.markdown("#### ✗ WA Submissions")
            # WA 按时间倒序：最新的在顶，从上往下是改进轨迹
            for wa in reversed(pair.wa_submissions):
                st.markdown(
                    f"""<div style="background:#2D2D3F; border-left:4px solid #D4A017;
                    padding:8px 12px; margin-bottom:6px; border-radius:4px;">
                    <b style="color:#D4A017">WA #{wa.id}</b><br>
                    {wa.language}<br>
                    ⏱ {wa.time_millis}ms &nbsp; 💾 {wa.memory_bytes // 1024}KB
                    </div>""",
                    unsafe_allow_html=True,
                )

        with right:
            st.markdown("#### ✓ Accepted")
            if pair.ac_submission:
                ac = pair.ac_submission
                st.markdown(
                    f"""<div style="background:#2D2D3F; border-left:4px solid #28A745;
                    padding:8px 12px; margin-bottom:6px; border-radius:4px;">
                    <b style="color:#28A745">AC #{ac.id}</b><br>
                    {ac.language}<br>
                    ⏱ {ac.time_millis}ms &nbsp; 💾 {ac.memory_bytes // 1024}KB
                    </div>""",
                    unsafe_allow_html=True,
                )

        # 底部 delta 总结
        if pair.ac_submission:
            ac = pair.ac_submission
            last_wa = pair.wa_submissions[-1]
            time_diff = ac.time_millis - last_wa.time_millis
            mem_diff = (ac.memory_bytes - last_wa.memory_bytes) // 1024
            time_arrow = "↓" if time_diff < 0 else "↑"
            mem_arrow = "↓" if mem_diff < 0 else "↑"
            st.caption(
                f"⚡ {pair.failed_attempts} failed → 1 accepted · "
                f"Time {time_arrow}{abs(time_diff)}ms · "
                f"Memory {mem_arrow}{abs(mem_diff)}KB"
            )

        st.divider()


# ── main ──────────────────────────────────────────────────────────────────────


def main():
    st.set_page_config(
        page_title="CF Review Tool",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.title("CF Review Tool")

    # ── sidebar: 输入 ──
    with st.sidebar:
        st.header("Contest Review")
        handle = st.text_input("Codeforces Handle", placeholder="e.g. tourist")
        contest_id = st.number_input("Contest ID", min_value=1, step=1, value=None, placeholder="e.g. 2048")

        search_disabled = not handle or not contest_id
        if search_disabled:
            st.caption("Enter both handle and contest ID to begin.")
        go = st.button("Start Review", type="primary", disabled=search_disabled, use_container_width=True)

    # ── 冷态：未搜索 ──
    if not go:
        st.info("Enter your handle and contest ID in the sidebar, then click **Start Review**.")
        return

    # ── 加载态 ──
    msg = st.empty()
    msg.info("Fetching contest data from Codeforces API...")
    try:
        standings = fetch_contest_standings(int(contest_id), handle)
        time.sleep(1)
        rating_change = fetch_rating_changes(int(contest_id), handle)
        time.sleep(1)
        raw_subs = fetch_user_submissions(handle, int(contest_id))
    except CFAPIError as e:
        msg.empty()
        st.error(str(e))
        return
    except Exception as e:
        msg.empty()
        st.error(f"Unexpected error: {e}")
        return
    msg.empty()

    # ── 数据处理（纯函数链） ──
    contest_start = calculate_contest_start(standings)
    overview = extract_overview(standings, rating_change, handle)

    # 比赛时长：从 standings contest 字段取
    contest_duration = standings.get("contest", {}).get("durationSeconds", 0)

    submissions = build_submissions_from_status(raw_subs, int(contest_id))
    timeline = build_timeline(submissions, standings.get("problems", []))
    pairs = extract_wa_ac_pairs(timeline)

    # ── 三个 Tab ──
    tab1, tab2, tab3 = st.tabs(["📊 Contest Overview", "⏱ Problem Timeline", "🔍 WA vs AC"])

    with tab1:
        _render_overview_tab(overview, contest_duration)

    with tab2:
        _render_timeline_tab(timeline)

    with tab3:
        _render_wa_ac_tab(pairs, timeline)


if __name__ == "__main__":
    main()
