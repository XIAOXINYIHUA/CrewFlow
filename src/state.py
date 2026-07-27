"""CrewFlow 全局状态定义 — 使用 Pydantic 模型的结构化状态"""

from __future__ import annotations

from typing import Annotated, Optional
from datetime import datetime
from decimal import Decimal

from langgraph.graph.message import add_messages
from langgraph.managed import IsLastStep
from langgraph.graph import StateGraph, MessagesState
from typing_extensions import TypedDict

from .models import (
    ResearchRequirements,
    ResearchPlan,
    SearchResult,
    Source,
    Claim,
    ReviewResult,
    ReportVersion,
    HumanDecision,
    NodeExecutionRecord,
    RunStatus,
    QualityStatus,
)


def reduce_list(existing: list, update: list) -> list:
    """Reducer for list fields — replace on update, keep on no-op."""
    if update is None:
        return existing or []
    return update


def reduce_optional(existing, update):
    """Reducer for optional fields — last writer wins."""
    return update if update is not None else existing


class CrewState(TypedDict):
    """Multi-Agent 协作全局状态

    所有节点函数通过 dict 键访问。Pydantic 模型用于深层结构的序列化和校验。
    """

    # ── 运行元信息 ──
    run_id: str
    thread_id: str
    status: RunStatus
    quality_status: QualityStatus
    created_at: datetime
    updated_at: datetime

    # ── 用户输入 ──
    requirements: ResearchRequirements
    topic: str

    # ── 研究计划 ──
    research_plan: Optional[ResearchPlan]
    outline: Optional[dict]          # ReportOutline 的事例化
    coverage_gaps: Annotated[list[str], reduce_list]

    # ── 搜索结果和来源 ──
    search_results: Annotated[list[SearchResult], reduce_list]
    sources: Annotated[list[Source], reduce_list]

    # ── 结论 (Claim) ──
    claims: Annotated[list[Claim], reduce_list]

    # ── 报告版本 ──
    analysis: Optional[str]          # Analyst 的分析
    draft_id: Optional[str]           # 当前草稿版本 ID
    draft: Optional[str]              # 当前草稿 Markdown
    report_versions: Annotated[list[ReportVersion], reduce_list]
    final_report_id: Optional[str]
    final_report: Optional[str]

    # ── 审查 ──
    review: Optional[ReviewResult]
    iteration: int

    # ── 人工审批 ──
    human_decision: Optional[HumanDecision]
    require_human_approval: bool

    # ── 执行追踪 ──
    current_node: Optional[str]
    node_executions: Annotated[list[NodeExecutionRecord], reduce_list]
    total_cost_usd: Decimal
    errors: Annotated[list[str], reduce_list]

    # ── 消息 (LangGraph 兼容) ──
    messages: Annotated[list, add_messages]
    is_last_step: IsLastStep


# ── 初始状态工厂 ──

def create_initial_state(
    topic: str,
    run_id: str,
    thread_id: str,
    **overrides,
) -> dict:
    """创建符合 CrewState 的初始状态字典"""
    base: dict = {
        "run_id": run_id,
        "thread_id": thread_id,
        "status": "queued",
        "quality_status": "unchecked",
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
        "requirements": ResearchRequirements(topic=topic),
        "topic": topic,
        "research_plan": None,
        "outline": None,
        "coverage_gaps": [],
        "search_results": [],
        "sources": [],
        "claims": [],
        "analysis": None,
        "draft_id": None,
        "draft": None,
        "report_versions": [],
        "final_report_id": None,
        "final_report": None,
        "review": None,
        "iteration": 0,
        "human_decision": None,
        "require_human_approval": True,
        "current_node": None,
        "node_executions": [],
        "total_cost_usd": Decimal("0"),
        "errors": [],
        "messages": [],
        "is_last_step": False,
    }
    base.update(overrides)
    return base
