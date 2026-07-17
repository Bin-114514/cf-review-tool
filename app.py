# CF Review Tool - 赛后复盘工具
"""
Streamlit UI — 侧边栏输入 + spinner → 双 Tab：单场复盘（总览/洞察/时间线/WA对比）+ 弱点分析。
只做 UI 组装，业务逻辑全部在 fetcher/analyzer 中。
"""

import re
from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import streamlit as st

from analyzer import (
    ContestOverview,
    ProblemCodePair,
    Submission,
    TimelineEntry,
    analyze_rating_bands,
    analyze_tags,
    build_submissions_from_status,
    build_timeline,
    calculate_contest_start,
    count_contestant_contests,
    extract_overview,
    extract_wa_ac_pairs,
    generate_insights,
    per_problem_probability,
)
from fetcher import (
    CFAPIError,
    fetch_contest_standings,
    fetch_rating_changes,
    fetch_recent_contests,
    fetch_recent_submissions,
    fetch_user_submissions,
)

# CF handle 规则: 3–24 字符，字母/数字/下划线/连字符（\Z 避免 $ 匹配尾部换行）
_HANDLE_RE = re.compile(r"^[a-zA-Z0-9._-]{3,24}\Z")
# 与 st.spinner 共用文案，避免硬编码
_ERROR_GENERIC = "Failed to load contest data. Check your inputs or try again later."


@st.cache_data(ttl=300, show_spinner=False, max_entries=50)
def _cached_recent_contests(handle: str) -> list[dict[str, object]]:
    """缓存 fetch_recent_contests 结果，避免每次 re-render 都调用 CF API

    注意：CFAPIError 故意不在此捕获——st.cache_data 不缓存异常，
    若在这里吞掉错误返回 []，一次瞬时失败会被当成"无比赛"缓存 5 分钟。
    """
    return fetch_recent_contests(handle, count=10)


@st.cache_data(ttl=600, show_spinner=False, max_entries=50)
def _cached_recent_submissions(handle: str) -> list[dict[str, object]]:
    """缓存多场提交记录（分页拉取较慢，~5 次 API 调用）

    隐私约束：st.cache_data 默认仅进程内存缓存（不加 persist 参数即不落盘），
    用户提交数据只存活于 session 内存，进程结束即清除。
    注意：CFAPIError 故意不在此捕获——st.cache_data 不缓存异常，
    若在这里吞掉错误返回 []，一次瞬时失败会被当成"数据不足"缓存 10 分钟。
    """
    return fetch_recent_submissions(handle, count=500)


def _color_rows(row):
    """行背景色：AC 绿色，WA 黄色，其他失败（TLE/RE/CE 等）浅红色"""
    verdict = row["Verdict"]
    if verdict == "OK":
        return ["background-color: rgba(40, 167, 69, 0.25)"] * len(row)
    if verdict == "WRONG_ANSWER":
        return ["background-color: rgba(212, 160, 23, 0.25)"] * len(row)
    # 非 AC 也非 WA（TLE / RE / CE / MLE / 等）
    return ["background-color: rgba(220, 53, 69, 0.18)"] * len(row)


def _render_single_contest(
    overview: ContestOverview,
    submissions: list[Submission],
    timeline: list[TimelineEntry],
    pairs: list[ProblemCodePair],
    insights: list[str],
    contest_start: int,
    contest_id: int,
    problem_ratings: dict[str, int] | None = None,
) -> None:
    """Tab 1：单场复盘 — 总览卡片 + 柱状图 + 洞察 + 时间线 + WA 对比"""
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

    # ── 逐题概率展示（problem rating vs 选手 rating）──
    if problem_ratings and overview.old_rating > 0:
        probs = per_problem_probability(overview, problem_ratings)
        if probs:
            prob_parts: list[str] = []
            # timeline 中的序号顺序
            seen: set[str] = set()
            for entry in timeline:
                idx = entry.problem_index
                if idx in seen or idx not in probs:
                    continue
                seen.add(idx)
                P = probs[idx]
                ac = entry.verdict == "OK"
                if ac:
                    label = f"{idx} ✅ Solved (expected {P:.0%})"
                else:
                    label = f"{idx} ❌ Not solved (expected {P:.0%})"
                color = "green" if P >= 0.6 else "red" if P <= 0.4 else "gray"
                prob_parts.append(f":{color}[{label}]")
            if prob_parts:
                st.caption("  ·  ".join(prob_parts))

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
                ts = datetime.fromtimestamp(entry.creation_time, tz=timezone.utc).strftime("%H:%M:%S")
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
            st.dataframe(styled, width="stretch", hide_index=True)
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
                    # 提交 ID → CF 源码页链接（CF API 不返回源码，跳转官网查看）
                    st.markdown(" · ".join(
                        f'[📄 WA #{i}](https://codeforces.com/contest/{contest_id}/submission/{wa.id} "在 Codeforces 查看源码")'
                        for i, wa in enumerate(pair.wa_submissions, 1)
                    ))
                with right:
                    ac_sub = pair.ac_submission
                    if ac_sub:
                        ac_text = (
                            f"AC ✓\n"
                            f"Submission ID: {ac_sub.id}\n"
                            f"Language: {ac_sub.language}\n"
                            f"Time: {ac_sub.time_millis}ms\n"
                            f"Memory: {ac_sub.memory_bytes // 1024}KB"
                        )
                        st.code(ac_text, language=None)
                        st.markdown(f'[📄 AC](https://codeforces.com/contest/{contest_id}/submission/{ac_sub.id} "在 Codeforces 查看源码")')
        else:
            st.info("No WA→AC pairs — all problems either solved first-try or unsolved.")


def _weakness_table(rows: list[dict[str, object]], ac_rate_col) -> None:
    """按 AC 率升序渲染统计表（最弱在上），共用两张表的排序与列配置"""
    df = pd.DataFrame(rows).sort_values("AC 率").reset_index(drop=True)
    st.dataframe(
        df,
        column_config={"AC 率": ac_rate_col},
        width="stretch",
        hide_index=True,
    )


def _fmt_avg_time(stats: dict[str, object]) -> float | None:
    """AC 为 0 时平均耗时无意义，返回 None（数字列渲染为空，保持数值排序）"""
    if not stats["ac"]:
        return None
    return round(stats["avg_time"] / 60)  # type: ignore[operator]


def _render_weakness(handle: str) -> None:
    """Tab 2：弱点分析 — 多场提交交叉统计（Tag 表格 + Rating 段表格）"""
    with st.spinner("Fetching recent submissions (multi-page, may take a few seconds)..."):
        try:
            # handle 小写归一：CF handle 大小写不敏感，避免同一用户重复付分页开销
            recent_subs = _cached_recent_submissions(handle.lower())
        except CFAPIError:
            st.error(_ERROR_GENERIC)
            return
        except Exception:
            st.error(_ERROR_GENERIC)
            return

    # 空状态：正式参赛的比赛场次不足（统计逻辑在 analyzer）
    n_contests = count_contestant_contests(recent_subs)
    if n_contests < 3:
        st.info("需要至少 3 场比赛的数据才能生成弱点分析")
        return

    st.caption(f"基于最近 {len(recent_subs)} 条提交 · {n_contests} 场正式参赛")

    # tags 取自提交内联的 problem.tags（user.status 自带，跨比赛无 index 冲突）
    tag_stats = analyze_tags(recent_subs)
    band_stats = analyze_rating_bands(recent_subs)

    ac_rate_col = st.column_config.ProgressColumn(
        "AC 率", format="percent", min_value=0.0, max_value=1.0,
    )

    # ── 上半部分：Tag 分析（AC 率升序，最弱在上）──
    st.subheader("🏷 Tag 弱点分析")
    if tag_stats:
        _weakness_table([
            {
                "Tag": tag,
                "AC 率": s["ac_rate"],
                "提交数": s["total"],
                "WA 数": s["wa"],
                "平均耗时 (min)": _fmt_avg_time(s),
            }
            for tag, s in tag_stats.items()
        ], ac_rate_col)
    else:
        st.caption("提交数据中没有 tag 信息。")

    # ── 下半部分：Rating 段分析（AC 率升序）──
    st.subheader("📶 Rating 段分析")
    band_rows = [
        {
            "Rating 段": band,
            "提交数": s["total"],
            "AC 率": s["ac_rate"],
            "平均耗时 (min)": _fmt_avg_time(s),
        }
        for band, s in band_stats.items()
        if s["total"] > 0
    ]
    if band_rows:
        _weakness_table(band_rows, ac_rate_col)
    else:
        st.caption("提交数据中没有题目 rating 信息。")


def main() -> None:
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
            # handle 小写归一：与弱点缓存一致，避免同一用户大小写不同产生重复缓存。
            # try/except 兜底：瞬时 API 失败或响应结构变化不能把 traceback 泄露到页面
            try:
                recent = _cached_recent_contests(handle.lower())
            except Exception:
                recent = []
            if recent:
                options: dict[str, int] = {}
                for c in recent:
                    date_str = datetime.fromtimestamp(c["date"], tz=timezone.utc).strftime("%Y-%m-%d")
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

    # 服务端重校验：disabled 只是客户端约束，篡改的客户端仍可提交
    if not handle_ok:
        st.error("Invalid handle.")
        return

    # ── 数据获取 ──
    with st.spinner("Fetching contest data from Codeforces API..."):
        try:
            standings = fetch_contest_standings(int(contest_id), handle)
            # 先算出比赛开始时间（纯函数），供提交分页提前终止
            contest_start = calculate_contest_start(standings)
            rating_change = fetch_rating_changes(int(contest_id), handle)
            raw_subs = fetch_user_submissions(handle, int(contest_id), contest_start)
        except CFAPIError:
            st.error(_ERROR_GENERIC)
            return
        except Exception:
            st.error(_ERROR_GENERIC)
            return

    # ── 从 standings 提取 {problem_index: rating}，供概率洞察 ──
    problem_ratings: dict[str, int] = {}
    for p in standings.get("problems", []):
        rating = p.get("rating")
        index = p.get("index")
        if rating is not None and index is not None:
            problem_ratings[index] = rating

    # ── 数据分析 ──
    overview = extract_overview(standings, rating_change, handle)
    submissions = build_submissions_from_status(raw_subs, int(contest_id))
    timeline = build_timeline(submissions)
    pairs = extract_wa_ac_pairs(timeline)
    insights = generate_insights(overview, timeline, pairs, contest_start, problem_ratings)

    # ── 双 Tab 布局 ──
    tab_review, tab_weakness = st.tabs(["📊 单场复盘", "🎯 弱点分析"])
    with tab_review:
        _render_single_contest(overview, submissions, timeline, pairs, insights, contest_start, int(contest_id), problem_ratings)
    with tab_weakness:
        _render_weakness(handle)


if __name__ == "__main__":
    main()
