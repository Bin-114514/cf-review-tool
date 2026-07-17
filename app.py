# CF Review Tool - 赛后复盘工具
"""
Streamlit 最小骨架 — 侧边栏输入 + spinner → 总览卡片 + 题目尝试柱状图。
只做 UI 组装，业务逻辑全部在 fetcher/analyzer 中。
"""

import pandas as pd
import plotly.express as px
import streamlit as st

from analyzer import build_submissions_from_status, extract_overview
from fetcher import CFAPIError, fetch_contest_standings, fetch_rating_changes, fetch_user_submissions


def main():
    st.set_page_config(page_title="CF Review Tool", page_icon="📊")
    st.title("CF Review Tool")

    # ── sidebar: 输入 ──
    with st.sidebar:
        st.header("Input")
        handle = st.text_input("Handle", value="tourist")
        contest_id = st.number_input("Contest ID", min_value=1, step=1, value=2245)
        go = st.button("Start Review", type="primary", use_container_width=True)

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
        except CFAPIError as e:
            st.error(str(e))
            return

    # ── 数据分析 ──
    overview = extract_overview(standings, rating_change, handle)
    submissions = build_submissions_from_status(raw_subs, int(contest_id))

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


if __name__ == "__main__":
    main()
