# CrewFlow - Multi-Agent 协作研究系统

[English](#english) | [中文](#中文)

---

## 中文

### 简介

CrewFlow 是一个基于 LangGraph 的多 Agent 协作系统，模拟"研究团队"的协作模式，让多个 AI Agent 分工合作，自动完成从信息搜集到报告撰写的完整研究流程。

### 功能特性

- **多角色协作**：Researcher（搜集）→ Analyst（分析）→ Writer（撰写）→ Reviewer（审查）
- **状态机编排**：基于 LangGraph StateGraph，支持条件分支和循环审查
- **自动质量控制**：Reviewer 自动审查初稿，不合格时 Writer 自动修改（最多 3 轮）
- **Human-in-the-Loop**：支持人工干预中间结果
- **双界面**：CLI 终端 + Gradio Web UI
- **报告自动保存**：生成的报告自动保存到 `output/` 目录

### 架构

```
                    ┌─────────────────────────────┐
                    │         CrewFlow             │
                    └─────────────────────────────┘
                               │
    ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
    │Researcher│──▶│ Analyst  │──▶│  Writer  │──▶│ Reviewer │
    │  搜集信息 │   │  深度分析 │   │  撰写报告 │   │  质量审查 │
    └──────────┘   └──────────┘   └──────────┘   └────┬─────┘
                                                       │
                                          ┌────────────┤
                                          │            │
                                     APPROVED     NEEDS REVISION
                                          │            │
                                          ▼            ▼
                                        END        Writer (修改)
                                                     │
                                                     └──▶ Reviewer (再次审查)
```

### 快速开始

```bash
# 1. 克隆项目
git clone https://github.com/your-username/CrewFlow.git
cd CrewFlow

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置 API Key
cp .env.example .env
# 编辑 .env 填入你的 OPENAI_API_KEY

# 4. 运行（二选一）

# CLI 模式
python main.py

# Web UI 模式
python web.py
```

### 使用示例

```bash
$ python main.py

请输入研究课题: 2025年 AI Agent 技术发展趋势

  → [researcher] 完成
  → [analyst] 完成
  → [writer] 完成
  → [reviewer] 完成
  ⚠️ 审查未通过（第1次），建议修改
  → [writer] 完成
  → [reviewer] 完成
  ✅ 报告已保存至: output/2025年_AI_Agent_技术发展趋势_20260527.md

============================================================
  最终报告
============================================================
（完整报告内容...）
```

### 项目结构

```
CrewFlow/
├── main.py                # CLI 入口
├── web.py                 # Gradio Web UI
├── requirements.txt       # Python 依赖
├── .env.example           # 环境变量模板
├── src/
│   ├── __init__.py
│   ├── state.py           # 全局状态定义（CrewState TypedDict）
│   ├── nodes.py           # Agent 节点（4个角色的实现）
│   ├── edges.py           # 条件路由（审查通过/修改逻辑）
│   ├── graph.py           # LangGraph 图编排
│   ├── tools.py           # 工具集（搜索、保存）
│   └── prompts.py         # 各角色 Prompt 模板
└── output/                # 生成的报告
```

---

## English

### Introduction

CrewFlow is a multi-agent collaboration system built with LangGraph. It simulates a "research team" where multiple AI agents work together, automatically completing the full research workflow from information gathering to report writing.

### Features

- **Multi-role Collaboration**: Researcher → Analyst → Writer → Reviewer
- **State Machine Orchestration**: LangGraph StateGraph with conditional branching and revision loops
- **Auto Quality Control**: Reviewer auto-checks drafts, Writer auto-revises on failure (up to 3 rounds)
- **Human-in-the-Loop**: Support for human intervention at any stage
- **Dual Interface**: CLI and Gradio Web UI
- **Auto-save Reports**: Generated reports saved to `output/` directory

### Quick Start

```bash
git clone https://github.com/your-username/CrewFlow.git
cd CrewFlow
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY
python main.py      # CLI mode
# or
python web.py       # Web UI mode
```

---

## License

MIT License
