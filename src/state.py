"""CrewFlow 全局状态定义 — 使用 Pydantic 模型的结构化状态"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, TypeVar, cast

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from langgraph.managed import IsLastStep
from typing_extensions import TypedDict

from .models import (
    Claim,
    HumanDecision,
    NodeExecutionRecord,
    QualityStatus,
    ReportVersion,
    ResearchPlan,
    ResearchRequirements,
    ReviewResult,
    RunStatus,
    SearchResult,
    Source,
)

T = TypeVar("T")


def reduce_list(existing: list[T] | None, update: list[T] | None) -> list[T]:
    """Reducer for list fields — replace on update, keep on no-op."""
    if update is None:
        return existing or []
    return update


def reduce_optional(existing: T | None, update: T | None) -> T | None:
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
    research_plan: ResearchPlan | None
    outline: dict[str, object] | None  # ReportOutline 的事例化
    coverage_gaps: Annotated[list[str], reduce_list]

    # ── 搜索结果和来源 ──
    search_results: Annotated[list[SearchResult], reduce_list]
    sources: Annotated[list[Source], reduce_list]

    # ── 结论 (Claim) ──
    claims: Annotated[list[Claim], reduce_list]

    # ── 报告版本 ──
    analysis: str | None  # Analyst 的分析
    draft_id: str | None  # 当前草稿版本 ID
    draft: str | None  # 当前草稿 Markdown
    report_versions: Annotated[list[ReportVersion], reduce_list]
    final_report_id: str | None
    final_report: str | None

    # ── 审查 ──
    review: ReviewResult | None
    iteration: int

    # ── 人工审批 ──
    human_decision: HumanDecision | None
    require_human_approval: bool

    # ── 执行追踪 ──
    current_node: str | None
    node_executions: Annotated[list[NodeExecutionRecord], reduce_list]
    total_cost_usd: Decimal
    errors: Annotated[list[str], reduce_list]

    # ── 消息 (LangGraph 兼容) ──
    messages: Annotated[list[AnyMessage], add_messages]
    is_last_step: IsLastStep


# ── 初始状态工厂 ──


def create_initial_state(
    topic: str,
    run_id: str,
    thread_id: str,
    **overrides: object,
) -> CrewState:
    """创建符合 CrewState 的初始状态字典"""
    base: dict[str, object] = {
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
    return cast(CrewState, base)
