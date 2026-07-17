# CLAUDE.md

## 项目概述

CF Review Tool — Codeforces 赛后复盘网页工具。用户输入 handle + contestID，获取比赛数据并生成可视化复盘报告。

## 技术栈

- **语言**: Python 3.11
- **Web 框架**: Streamlit
- **HTTP 客户端**: requests
- **可视化**: plotly
- **依赖管理**: uv (pyproject.toml)
- **部署目标**: Streamlit Community Cloud

## 项目结构

```
cf-review-tool/
├── app.py          # Streamlit UI 组装（只管界面，不含业务逻辑）
├── fetcher.py      # CF API 数据获取（带重试机制）
├── analyzer.py     # 纯函数分析逻辑（无副作用）
├── tests/          # pytest 测试
├── pyproject.toml  # 项目配置与依赖
├── README.md
└── uv.lock
```

## 核心架构

- **fetcher.py** — 封装对 Codeforces API 的 HTTP 请求，包含重试逻辑（requests.Session + Retry 或手动指数退避）。所有函数返回类型明确。
- **analyzer.py** — 纯函数模块：接收原始数据，返回分析结果。不调用 API、不读写文件、不修改外部状态。所有函数带 type hints。
- **app.py** — Streamlit 页面：只做用户输入（handle + contestID）和数据展示（plotly 图表），不包含分析逻辑。

## Codeforces API 约束

- API 基础 URL: `https://codeforces.com/api/`
- **请求间隔必须 ≥ 1 秒**，避免触发 CF 的 rate limit
- 相关端点：
  - `contest.standings` — 比赛排名 + 题目列表
  - `user.status` — 用户提交记录
  - `contest.ratingChanges` — Rating 变化

## 代码规范

1. **所有函数必须有 type hints**（参数和返回值）
2. **fetcher.py** — 所有 HTTP 调用必须带重试（至少 3 次，指数退避）
3. **analyzer.py** — 纯函数，输入/输出可预测、可测试
4. **app.py** — 只负责 UI 组装，不包含数据获取或分析逻辑
5. 使用描述性变量名，注释解释"为什么"而非"是什么"
6. API 调用之间确保 ≥ 1 秒间隔（time.sleep 或装饰器）

## Skill 触发规则

- `/brainstorming` — 每个新功能方向开始前
- `writing-plans` — 拆分子任务前
- `test-driven-development` — 写 fetcher / analyzer 时
- `frontend-design` — 设计 Streamlit UI 布局时
- `requesting-code-review` / `code-review` — 模块完成时
- `systematic-debugging` — 遇到 bug 时
- `verification-before-completion` — 每个子任务完成前

## Code Review 响应规则

审查结果按三级处理：
1. **无条件修** — 类型错误、bug、命名不一致、纯函数副作用 → 立即修
2. **确认后修** — 影响已有测试的数据结构变更 → 先讨论，确认后再修
3. **记 backlog** — scope 外的未实现函数 → 写入 CLAUDE.md 对应里程碑的 backlog

## 工作流约束

1. **一次一个子任务** — 完成后再进入下一个
2. **每约 100 行代码验证一次** — 运行程序/测试，确认无报错再继续
3. **AI 自愈** — 遇到报错时，先自行分析并修复，最多尝试 3 次
4. **commit 自动，push 手动** — 每个子任务完成后 commit，但 push 由用户手动控制

## 环境

```bash
# 同步依赖
uv sync

# 运行 Streamlit 开发服务器
uv run streamlit run app.py
```

## 依赖列表（pyproject.toml）

| 包 | 版本 | 用途 |
|---|---|---|
| streamlit | ≥1.59.2 | Web UI 框架 |
| requests | ≥2.34.2 | HTTP 请求 |
| plotly | ≥6.9.0 | 交互式图表 |
| pytest | — | 测试框架（dev） |

## 当前状态（2026-07-17）

- [x] uv 项目初始化，依赖已同步
- [x] CLAUDE.md 就绪
- [x] pytest 配置已添加（pyproject.toml [tool.pytest.ini_options]）
- [x] tests/ 已创建（34 tests: 18 fetcher + 16 analyzer）
- [x] fetcher.py 已完成（CFAPIError + 6 函数 + 18 tests）
- [x] analyzer.py 已完成（5 dataclasses + 5 函数 + 16 tests）
- [x] app.py 已完成 — 侧边栏输入校验 + 总览卡片 + plotly 柱状图 + 逐题时间线（AC 绿/WA 黄/失败红）+ WA→AC 对比面板
- [x] M1-3 完整 UI 已完成（code review + security review 修复已应用）

## M1: 单场比赛复盘 MVP

### 总体目标

用户输入 handle + contestID → 网页展示三个面板：
1. **比赛总览卡片** — 排名、Rating 变化、解题数
2. **逐题时间线表格** — WA 黄色背景、AC 绿色背景
3. **WA 与 AC 对比面板** — 每题 WA→AC 的提交详情对比

### 数据流

```
app.py (输入 handle + contestId)
  → fetcher.py (CF API 三级调用: standings, status, ratingChanges)
  → analyzer.py (纯函数: 提取 overview, timeline, wa_ac_pairs)
  → app.py (plotly 表格 + streamlit metric 渲染)
```

### 关键技术决策

- CF API 不返回源代码，代码对比面板用**提交元数据对比**（语言、时间、内存）代替源码 diff
- `contest.standings` 通过 `handles` 参数只拉取目标用户行，避免全榜下载
- `user.status` 拉取后按 `contestId` 过滤

---

### Task 1: fetcher.py — CF API 数据获取层

**文件：**
- 创建：`fetcher.py`
- 创建：`tests/test_fetcher.py`

**依赖：** 无

**产出接口：**
```python
def fetch_contest_standings(contest_id: int, handle: str) -> dict[str, Any]:
    """调用 contest.standings?contestId=X&handles=Y，返回 result 字典
    包含 contest、problems、rows 三个字段"""

def fetch_user_contest_submissions(handle: str, contest_id: int) -> list[dict[str, Any]]:
    """调用 user.status?handle=X&from=1&count=100，按 contestId 过滤
    返回该场比赛的所有提交记录列表"""

def fetch_rating_changes(contest_id: int, handle: str) -> dict[str, Any] | None:
    """调用 contest.ratingChanges?contestId=X，从列表中匹配 handle
    返回单个 ratingChange 对象或 None（未 rated 的比赛）"""
```

**验收标准：**

| # | 标准 | 验证方式 |
|---|------|---------|
| 1 | 所有函数有完整 type hints（参数+返回值） | grep `def ` fetcher.py，逐个检查 |
| 2 | HTTP 请求失败时自动重试（3 次，指数退避 1s→2s→4s） | 测试中 mock requests.get 连续失败 2 次后第 3 次成功 |
| 3 | 连续两次 API 调用间隔 ≥ 1 秒 | 检查代码中 `time.sleep(1)` 或装饰器存在 |
| 4 | CF API 返回 `status != "OK"` 时抛出 `CFAPIError` 自定义异常 | 测试中 mock API 返回 `{"status": "FAILED", "comment": "..."}` |
| 5 | `fetch_rating_changes` 在未找到 handle 时返回 None（不抛异常） | 测试中传入不存在的 handle |
| 6 | `tests/test_fetcher.py` 至少 6 个测试用例全部绿色 | `uv run pytest tests/test_fetcher.py -v` |

---

### Task 2: analyzer.py — 数据分析层

**文件：**
- 创建：`analyzer.py`
- 创建：`tests/test_analyzer.py`

**依赖：** Task 1（需要 fetcher 返回的原始 dict 结构来构造测试 fixture）

**涉及数据结构：**
```python
@dataclass
class Submission:
    id: int
    problem_index: str       # "A", "B", "C"...
    problem_name: str        # "Watermelon"
    verdict: str             # "OK" | "WRONG_ANSWER" | "TIME_LIMIT_EXCEEDED" | ...
    language: str            # "C++17 (GCC 7-32)"
    memory_bytes: int        # 内存占用
    time_millis: int         # 运行时间
    creation_time: int       # Unix 时间戳

@dataclass
class ContestOverview:
    handle: str
    contest_name: str
    rank: int
    old_rating: int
    new_rating: int
    rating_delta: int
    problems_solved: int
    total_problems: int

@dataclass
class ProblemTimelineEntry:
    problem_index: str
    problem_name: str
    submissions: list[Submission]  # 按时间升序
    solved: bool
    attempts: int
    first_solve_time: int | None   # 距比赛开始的秒数，未解决则为 None

@dataclass
class ProblemCodePair:
    problem_index: str
    problem_name: str
    wa_submissions: list[Submission]  # 所有 WA 尝试
    ac_submission: Submission | None  # 最终 AC，未通过则为 None
```

**产出接口：**
```python
def extract_overview(
    standings: dict[str, Any],
    rating_change: dict[str, Any] | None,
    handle: str,
) -> ContestOverview:
    """从 standings 和 ratingChanges 中提取比赛总览"""

def build_submissions_from_status(
    status_data: list[dict[str, Any]],
    contest_id: int,
) -> list[Submission]:
    """将 user.status 原始数据转为 Submission 列表，按 creation_time 升序"""

def build_timeline(
    submissions: list[Submission],
    problems: list[dict[str, Any]],
) -> list[ProblemTimelineEntry]:
    """将 submissions 按 problem_index 分组，构建时间线"""

def extract_wa_ac_pairs(
    timeline: list[ProblemTimelineEntry],
) -> list[ProblemCodePair]:
    """从时间线中提取有 WA→AC 过程的题目（至少 1 次 WA 后 AC）"""

def calculate_contest_start(standings: dict[str, Any]) -> int:
    """从 standings 中提取比赛开始时间（Unix timestamp）"""
```

**验收标准：**

| # | 标准 | 验证方式 |
|---|------|---------|
| 1 | 所有函数是纯函数（无 HTTP、无文件 IO、无全局状态） | 检查 analyzer.py，import 中无 requests / open / global |
| 2 | 所有函数完整 type hints | grep `def ` analyzer.py |
| 3 | `extract_overview` rating_change 为 None 时，rating 字段填 0 | 测试未 rated 比赛（Div3/Div4 新号场景） |
| 4 | `build_timeline` 每个 problem entry 的 submissions 按时间升序排列 | 测试中传入乱序提交 |
| 5 | `extract_wa_ac_pairs` 只返回包含至少 1 个 WA 且最终 AC 的题目 | 测试包含一血 AC、纯 WA、WA→AC 三种情况的 fixture |
| 6 | 未解决的题目（全是 WA/RE/TLE）不出现在 wa_ac_pairs 中 | 验证空列表 |
| 7 | `tests/test_analyzer.py` 至少 8 个测试用例全部绿色 | `uv run pytest tests/test_analyzer.py -v` |

---

### Task 3: app.py — Streamlit UI

**文件：**
- 修改：`app.py`

**依赖：** Task 2（需要 analyzer 所有函数和数据类可用）

**UI 结构：**
```
┌─────────────────────────────────────┐
│  CF Review Tool                     │
│  [handle输入框] [contestID输入框]    │
│  [开始复盘 按钮]                     │
├─────────────────────────────────────┤
│  📊 比赛总览                         │
│  ┌──────┬──────┬──────┬──────┐      │
│  │ 排名 │ Old  │ New  │ 解题 │      │
│  │  42  │ 1532 │ 1621 │ 3/6  │      │
│  └──────┴──────┴──────┴──────┘      │
├─────────────────────────────────────┤
│  ⏱ 逐题提交时间线                    │
│  ┌─────────────────────────────────┐│
│  │ A·Watermelon  [WA][WA][AC✓]     ││
│  │ B·Candies     [AC✓]             ││
│  │ C·Graph       [WA][TLE][WA]     ││
│  └─────────────────────────────────┘│
├─────────────────────────────────────┤
│  🔍 WA→AC 对比                      │
│  ┌──────────┬──────────┐            │
│  │ WA #1    │ AC       │            │
│  │ C++ 62ms │ C++ 15ms │            │
│  │ 12MB     │ 8MB      │            │
│  └──────────┴──────────┘            │
└─────────────────────────────────────┘
```

**验收标准：**

| # | 标准 | 验证方式 |
|---|------|---------|
| 1 | 无输入时不报错，显示提示文字 | `uv run streamlit run app.py` 打开页面，默认状态不报错 |
| 2 | 输入合法 handle + contestID，点击按钮后三个面板全部渲染 | 用 `tourist` + `1` 测试 |
| 3 | 时间线表格中 WA 行黄色背景、AC 行绿色背景 | 目视检查 |
| 4 | WA→AC 对比面板只显示有 WA 且最终 AC 的题目（一血 AC 不出现） | 目视检查 |
| 5 | API 报错时显示 `st.error()` 而非白屏/崩溃 | 输入不存在的 contestID（如 9999999） |
| 6 | 输入为空时按钮禁用或给出提示 | 点击空输入 |
| 7 | `app.py` 不包含任何数据处理逻辑 — 只调 analyzer 和渲染 | 检查 app.py 无 `def extract_` / `def build_` / `def calculate_` |

---

### Task 4: 部署配置 + 最终验证

**文件：**
- 创建：`requirements.txt`（Streamlit Cloud 需要）
- 可选创建：`.streamlit/config.toml`

**依赖：** Task 3（app.py 完整可用）

**验收标准：**

| # | 标准 | 验证方式 |
|---|------|---------|
| 1 | `requirements.txt` 包含 streamlit、requests、plotly 且版本与 uv.lock 一致 | `diff <(uv export --no-dev) requirements.txt` |
| 2 | `.streamlit/config.toml`（如需要）配置正确 | 检查 theme 等字段 |
| 3 | README.md 包含部署链接和使用说明 | 目视检查 |
| 4 | `uv run streamlit run app.py` 从头到尾无 import 错误 | 完整启动流程 |
| 5 | 最终 git status 干净，所有文件已 commit | `git status` |

### 任务依赖图

```
Task 1 (fetcher.py)
    │
    ▼
Task 2 (analyzer.py) — build_timeline + extract_wa_ac_pairs 已完成
    │
    ▼
Task 3 (app.py)
    │
    ▼
Task 4 (部署配置)
```

### M1 Backlog

- [x] `extract_overview(standings, rating_change, handle) -> ContestOverview` — 已实现（M1-3）
- [x] `build_submissions_from_status(status_data, contest_id) -> list[Submission]` — 已实现（M1-3）
- [x] `calculate_contest_start(standings) -> int` — 已实现（M1-3）
- [ ] `build_problem_timeline(submissions, problems) -> list[ProblemTimelineEntry]` — 按题目分组的时间线

### 全局约束（适用于所有 Task）

1. 每 ~100 行代码运行一次验证，确认无报错再继续
2. 遇到报错自行分析修复，最多 3 次尝试
3. 每个 Task 完成后 commit（用户手动 push）
4. 所有 `.py` 文件函数带 type hints
5. API 调用间隔 ≥ 1 秒
