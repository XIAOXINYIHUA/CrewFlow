# CrewFlow

CrewFlow 是一个基于 LangGraph 的多 Agent 可信研究系统。它把研究任务拆分为规划、检索、来源处理、主张提取、分析、写作、引用检查、质量审查和人工审批，并保存来源与报告版本，便于审计和继续处理。

当前版本：`0.2.0` · Python `3.11+` · MIT License

## 核心能力

- 完整研究状态机，而非一次性 Prompt 串联
- Tavily 检索、网页正文抽取、来源规范化与可信度评分
- Claim/Evidence 结构化提取、引用覆盖检查和冲突检测
- Writer/Reviewer 自动修订循环，达到上限后转人工处理
- LangGraph checkpoint 支持单进程内暂停与恢复
- CLI、Gradio 工作台和 FastAPI/SSE 三种入口
- SQLite 默认存储，可切换 PostgreSQL
- 报告版本、运行日志、成本预算和导出功能
- Pytest、Ruff、MyPy 与 GitHub Actions 工程基线

## 研究流程

```text
START
  → validate_input
  → planner
  → researcher
  → source_processor
  → claim_builder
  → coverage_checker
  → outline_builder
  → analyst
  → writer
  → citation_checker
  → reviewer
      ├─ 需要修改 → writer
      ├─ 需要审批 → human_review → publisher / writer / END
      └─ 自动通过 → publisher
  → END
```

## 快速开始

### 1. 准备环境

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，至少填写：

```dotenv
OPENAI_API_KEY=your-api-key
TAVILY_API_KEY=your-tavily-key
```

没有 Tavily Key 时，搜索模块会使用开发用模拟结果，不应把这种结果用于正式研究报告。

### 2. 安装依赖

推荐使用 [uv](https://docs.astral.sh/uv/)：

```powershell
uv sync --extra dev --extra server --extra web
```

也可以使用 pip：

```powershell
python -m pip install -e ".[dev,server,web]"
```

### 3. 启动

CLI：

```powershell
uv run python main.py
```

Web 工作台：

```powershell
uv run python web.py
```

浏览器访问 `http://localhost:7860`。

API：

```powershell
uv run uvicorn src.api:app --host 0.0.0.0 --port 8000
```

- 健康检查：`GET http://localhost:8000/health`
- OpenAPI：`http://localhost:8000/docs`
- API 前缀：`/api/v1`

## Docker Compose

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Compose 会启动：

- FastAPI：`http://localhost:8000`
- Gradio：`http://localhost:7860`
- PostgreSQL：`localhost:5432`

API 与 Web 服务共用 PostgreSQL、报告输出卷和来源制品卷。

## 常用配置

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `OPENAI_API_KEY` | 空 | OpenAI API Key |
| `OPENAI_API_BASE` | 官方 API | OpenAI 兼容端点 |
| `TAVILY_API_KEY` | 空 | 真实联网检索 |
| `CREWFLOW_*_MODEL` | `gpt-4o-mini` | 各研究角色使用的模型 |
| `CREWFLOW_MAX_ITERATIONS` | `3` | 自动修改上限 |
| `CREWFLOW_MAX_SOURCES` | `30` | 全局来源上限 |
| `CREWFLOW_MAX_BUDGET_USD` | 不限制 | 单次研究预算 |
| `CREWFLOW_DATABASE_URL` | `sqlite:///data/crewflow.db` | SQLAlchemy 数据库 URL |
| `CREWFLOW_OUTPUT_DIR` | `<base>/output` | 报告输出目录 |
| `CREWFLOW_ARTIFACTS_DIR` | `<base>/data/artifacts` | 来源正文制品目录 |
| `CREWFLOW_HOST` / `CREWFLOW_PORT` | `0.0.0.0` / `8000` | API 监听地址 |
| `CREWFLOW_WEB_HOST` / `CREWFLOW_WEB_PORT` | `0.0.0.0` / `7860` | Web 监听地址 |

完整配置见 [`.env.example`](.env.example)。

## API 使用流程

```text
POST /api/v1/runs
GET  /api/v1/runs/{run_id}/events
POST /api/v1/runs/{run_id}/review
GET  /api/v1/runs/{run_id}/sources
GET  /api/v1/runs/{run_id}/reports
GET  /api/v1/runs/{run_id}/export
```

创建任务后连接 SSE 端点接收节点事件；任务进入 `waiting_human` 后，通过 review 端点提交 `approve`、`revise` 或 `cancel`。

## 开发与验证

```powershell
uv run ruff check src tests main.py web.py
uv run ruff format --check src tests main.py web.py
uv run pytest
uv run mypy src
```

外部 API 集成测试应标记为 `integration`，默认测试集不应产生网络费用。

## 项目结构

```text
CrewFlow/
├── main.py                   # CLI
├── web.py                    # Gradio 工作台
├── src/
│   ├── api.py                # FastAPI 与 SSE
│   ├── graph.py              # LangGraph 编排
│   ├── nodes.py              # 核心节点
│   ├── nodes_extra.py        # 规划/大纲/覆盖节点
│   ├── state.py              # 图状态
│   ├── models.py             # Pydantic 模型
│   ├── orm_models.py         # SQLAlchemy 模型
│   ├── repository.py         # 数据访问层
│   ├── search/               # 搜索提供方
│   └── services/             # 来源、引用、Claim、成本与安全服务
├── migrations/               # Alembic 迁移
├── tests/                    # 单元测试
├── Dockerfile
└── compose.yaml
```

## 当前边界

- 图 checkpoint 当前保存在进程内；服务重启后的研究恢复能力将在后续版本使用持久化 checkpointer 完善。
- API Key 并不等同于访问控制；将 API 暴露到公网前应增加身份认证、限流和反向代理。
- LLM 输出仍可能出错，重要结论必须回到来源原文复核。

## License

[MIT](LICENSE)
