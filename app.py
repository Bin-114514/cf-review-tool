# CF Review Tool - 赛后复盘工具
"""
Streamlit UI — 侧边栏输入 + spinner → 总览卡片 + 题目尝试柱状图 + 逐题时间线 + WA vs AC。
只做 UI 组装，业务逻辑全部在 fetcher/analyzer 中。
"""

import re
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from analyzer import (
    build_submissions_from_status,
    build_timeline,
    calculate_contest_start,
    extract_overview,
    extract_wa_ac_pairs,
    generate_insights,
)
from fetcher import (
    CFAPIError,
    fetch_contest_standings,
    fetch_rating_changes,
    fetch_recent_contests,
    fetch_user_submissions,
)

# CF handle 规则: 3–24 字符，字母/数字/下划线/连字符
_HANDLE_RE = re.compile(r"^[a-zA-Z0-9._-]{3,24}$")
# 与 st.spinner 共用文案，避免硬编码
_ERROR_GENERIC = "Failed to load contest data. Check your inputs or try again later."


@st.cache_data(ttl=300, show_spinner=False)
def _cached_recent_contests(handle: str) -> list[dict[str, object]]:
    """缓存 fetch_recent_contests 结果，避免每次 re-render 都调用 CF API"""
    try:
        return fetch_recent_contests(handle, count=10)
    except CFAPIError:
        return []


def _color_rows(row):
    """行背景色：AC 绿色，WA 黄色，其他失败（TLE/RE/CE 等）浅红色"""
    verdict = row["Verdict"]
    if verdict == "OK":
        return ["background-color: rgba(40, 167, 69, 0.25)"] * len(row)
    if verdict == "WRONG_ANSWER":
        return ["background-color: rgba(212, 160, 23, 0.25)"] * len(row)
    # 非 AC 也非 WA（TLE / RE / CE / MLE / 等）
    return ["background-color: rgba(220, 53, 69, 0.18)"] * len(row)


def main():
    st.set_page_config(page_title="CF Review Tool", page_icon="📊")
    st.title("CF Review Tool")

    # ── sidebar: 输入 ──
    with st.sidebar:
        st.header("Input")
        handle = st.text_input("Handle", value="tourist")
        handle_ok = bool(_HANDLE_RE.match(handle))
        if handle and not handle_ok:
            st.caption("⚠️ Handle must be 3–24 chars: letters, digits, `.`, `-`, `_`.")

        # 最近 N 场比赛选择器
        recent_contest_id: int | None = None
        if handle_ok:
            recent = _cached_recent_contests(handle)
            if recent:
                options: dict[str, int] = {}
                for c in recent:
                    date_str = datetime.utcfromtimestamp(c["date"]).strftime("%Y-%m-%d")
                    label = f"{date_str} · {c['contestName']} · #{c['rank']}"
                    options[label] = c["contestId"]
                picked = st.selectbox(
                    "Recent rated contests",
                    options=["(choose a contest)"] + list(options.keys()),
                    key="contest_picker",
                )
                if picked and picked != "(choose a contest)":
                    recent_contest_id = options[picked]
            else:
                st.caption("No rated contests found for this handle.")

        # contest_id: 选择器优先，否则手动输入
        contest_id = st.number_input(
            "Contest ID",
            min_value=1,
            step=1,
            value=recent_contest_id if recent_contest_id else 2245,
        )
        go = st.button(
            "Start Review",
            type="primary",
            use_container_width=True,
            disabled=not handle_ok,
        )

    # ── 冷态 ──
    if not go:
        st.info("Enter handle and contest ID, then click **Start Review**.")
        return

    # ── 数据获取 ──
    with st.spinner("Fetching contest data from Codeforces API..."):
        try:
            standings = fetch_contest_standings(int(contest_id), handle)
            rating_change = fetch_rating_changes(int(contest_id), handle)
            raw_subs = fetch_user_submissions(handle, int(contest_id))
        except CFAPIError:
            st.error(_ERROR_GENERIC)
            return
        except Exception:
            st.error(_ERROR_GENERIC)
            st.exception("Internal error — see details below")
            return

    # ── 数据分析 ──
    overview = extract_overview(standings, rating_change, handle)
    submissions = build_submissions_from_status(raw_subs, int(contest_id))
    contest_start = calculate_contest_start(standings)
    timeline = build_timeline(submissions)
    pairs = extract_wa_ac_pairs(timeline)
    insights = generate_insights(overview, timeline, pairs, contest_start)

    # ── 比赛总览卡片 ──
    st.header(f"🏆 {overview.contest_name}")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Rank", f"#{overview.rank}" if overview.rank else "—")
    with c2:
        st.metric("Old Rating", str(overview.old_rating) if overview.old_rating else "Unrated")
    with c3:
        delta_str = f"{overview.rating_delta:+d}" if overview.rating_delta else None
        st.metric("New Rating",
                  str(overview.new_rating) if overview.new_rating else "Unrated",
                  delta=delta_str)
    with c4:
        total = len(submissions)
        ac = sum(1 for s in submissions if s.verdict == "OK")
        st.metric("Submissions", f"{ac} AC / {total} total")

    # ── 题目尝试次数柱状图 ──
    if submissions:
        problems = sorted(dict.fromkeys(s.problem_index for s in submissions))
        ac_counts = [sum(1 for s in submissions if s.problem_index == p and s.verdict == "OK") for p in problems]
        wa_counts = [sum(1 for s in submissions if s.problem_index == p and s.verdict != "OK") for p in problems]

        df = pd.DataFrame({"Problem": problems, "AC": ac_counts, "WA / Other": wa_counts})

        fig = px.bar(
            df,
            x="Problem",
            y=["AC", "WA / Other"],
            title="Attempts per Problem",
            color_discrete_map={"AC": "#28A745", "WA / Other": "#D4A017"},
            barmode="stack",
        )
        fig.update_layout(
            yaxis_title="Attempts",
            legend_title=None,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig, use_container_width=True)

    # ── 比赛洞察（M2-2 启发式规则引擎）──
    st.subheader("💡 比赛洞察")
    if insights:
        # analyzer 已按重要性排序，上限 6 条
        for insight in insights[:6]:
            st.info(insight)
    else:
        st.caption("本场比赛数据不足以生成洞察")

    # ── 逐题时间线 ──
    with st.expander("⏱ 逐题时间线", expanded=False):
        if timeline:
            rows: list[dict[str, object]] = []
            for entry in timeline:
                ts = datetime.utcfromtimestamp(entry.creation_time).strftime("%H:%M:%S")
                if contest_start:
                    mins = (entry.creation_time - contest_start) // 60
                else:
                    mins = 0
                rows.append({
                    "Problem": f"{entry.problem_index}. {entry.problem_name}",
                    "Time (UTC)": ts,
                    "Verdict": entry.verdict,
                    "Min from Start": f"+{mins}min",
                })

            tdf = pd.DataFrame(rows)
            styled = tdf.style.apply(_color_rows, axis=1)
            st.dataframe(styled, use_container_width=True, hide_index=True)
        else:
            st.caption("No submissions found.")

    # ── WA vs AC ──
    with st.expander("🔍 WA → AC 对比", expanded=False):
        if pairs:
            for pair in pairs:
                st.subheader(
                    f"Problem {pair.problem_index} — "
                    f"{pair.problem_name} / {pair.failed_attempts} attempt{'s' if pair.failed_attempts > 1 else ''}"
                )
                left, right = st.columns(2)
                with left:
                    wa_blocks: list[str] = []
                    for i, wa in enumerate(pair.wa_submissions, 1):
                        wa_blocks.append(
                            f"WA #{i}\n"
                            f"Submission ID: {wa.id}\n"
                            f"Language: {wa.language}\n"
                            f"Time: {wa.time_millis}ms\n"
                            f"Memory: {wa.memory_bytes // 1024}KB"
                        )
                    st.code("\n\n".join(wa_blocks), language=None)
                with right:
                    ac = pair.ac_submission
                    if ac:
                        ac_text = (
                            f"AC ✓\n"
                            f"Submission ID: {ac.id}\n"
                            f"Language: {ac.language}\n"
                            f"Time: {ac.time_millis}ms\n"
                            f"Memory: {ac.memory_bytes // 1024}KB"
                        )
                        st.code(ac_text, language=None)
        else:
            st.info("No WA→AC pairs — all problems either solved first-try or unsolved.")


if __name__ == "__main__":
    main()
