# CF Review Tool

Codeforces 赛后复盘网页工具 — 输入 handle + contestID，获取比赛数据并生成可视化复盘报告。

## 功能

三面板复盘报告：

1. **比赛总览卡片** — 排名、Rating 变化（±delta）、解题数
2. **逐题提交时间线** — WA 黄 / AC 绿 / 其他失败红、距开赛时间
3. **WA → AC 对比** — 每道 WA 后 AC 的题目左右并排 detail 对比

## 技术栈

- Python 3.11 + Streamlit + plotly + requests
- 依赖管理：uv (pyproject.toml)
- Codeforces API（公开，无需密钥）
- 纯函数分析层（analyzer.py）+ 重试数据层（fetcher.py）

## 本地运行

```bash
# 1. 克隆项目
git clone https://github.com/tangbin0524/cf-review-tool.git
cd cf-review-tool

# 2. 安装依赖（需 uv: pip install uv）
uv sync

# 3. 启动开发服务器
uv run streamlit run app.py
```

打开浏览器访问 `http://localhost:8501`，在侧边栏输入 Codeforces handle 和 contest ID，点击 **Start Review**。

## 部署

本项目设计用于 Streamlit Community Cloud 部署：

1. Push 到 GitHub 仓库
2. 在 [share.streamlit.io](https://share.streamlit.io) 连接仓库
3. 入口文件：`app.py`，Python 版本：3.11

## 项目结构

```
cf-review-tool/
├── app.py           # Streamlit UI 组装
├── fetcher.py       # CF API 数据获取（重试机制）
├── analyzer.py      # 纯函数分析逻辑
├── tests/           # pytest 测试（34 cases）
├── pyproject.toml   # 项目配置与依赖
├── uv.lock          # 锁定依赖版本
└── README.md
```

## API 约束

- Codeforces API 请求间隔 ≥ 1 秒
- `contest.standings` 仅支持匿名 GET（不带 handles 参数），本地筛选
- `user.status` 默认拉取最近 100 条提交，按 contestId 过滤
