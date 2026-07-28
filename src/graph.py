"""LangGraph 编排 — 完整研究流程图

节点流程:
  START → validate_input → planner → researcher → source_processor
    → claim_builder → coverage_checker → outline_builder → analyst
    → writer → citation_checker → reviewer
    → revision_router → writer | publisher | human_review
  human_review → after_human → writer | publisher | end
  publisher → end
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.config import settings
from src.edges import after_human_review, should_revise_or_end
from src.nodes import (
    analyst_node,
    citation_checker_node,
    claim_builder_node,
    human_review_node,
    publisher_node,
    researcher_node,
    reviewer_node,
    source_processor_node,
    validate_input_node,
    writer_node,
)
from src.nodes_extra import (
    coverage_checker_node,
    outline_builder_node,
    planner_node,
)
from src.state import CrewState

NodeUpdate = dict[str, Any]
CompiledCrewGraph = CompiledStateGraph[CrewState, None, CrewState, CrewState]
_CHECKPOINT_MODEL_ALLOWLIST: tuple[tuple[str, str], ...] = (
    ("src.models", "ResearchRequirements"),
    ("src.models", "ResearchQuestion"),
    ("src.models", "SearchQuery"),
    ("src.models", "ResearchPlan"),
    ("src.models", "SearchResult"),
    ("src.models", "Source"),
    ("src.models", "Evidence"),
    ("src.models", "Claim"),
    ("src.models", "ReviewIssue"),
    ("src.models", "ReviewResult"),
    ("src.models", "ReportVersion"),
    ("src.models", "HumanDecision"),
    ("src.models", "NodeExecutionRecord"),
)


def _sync(
    f: Callable[[CrewState], Coroutine[Any, Any, NodeUpdate]],
) -> Callable[[CrewState], NodeUpdate]:
    @wraps(f)
    def wrapper(state: CrewState) -> NodeUpdate:
        return asyncio.run(f(state))

    return wrapper


_graph_instance: CompiledCrewGraph | None = None
_checkpoint_connection: sqlite3.Connection | None = None


def _build_checkpointer() -> BaseCheckpointSaver[Any]:
    """Create the durable SQLite saver used by all graph executions."""
    global _checkpoint_connection

    settings.ensure_dirs()
    _checkpoint_connection = sqlite3.connect(
        settings.CHECKPOINT_DB,
        check_same_thread=False,
        timeout=30.0,
    )
    _checkpoint_connection.execute("PRAGMA journal_mode=WAL")
    serializer = JsonPlusSerializer(allowed_msgpack_modules=_CHECKPOINT_MODEL_ALLOWLIST)
    checkpointer = SqliteSaver(_checkpoint_connection, serde=serializer)
    checkpointer.setup()
    return cast(BaseCheckpointSaver[Any], checkpointer)


def build_graph() -> CompiledCrewGraph:
    global _graph_instance
    if _graph_instance is not None:
        return _graph_instance

    graph: StateGraph[CrewState, None, CrewState, CrewState] = StateGraph(CrewState)

    # 节点
    graph.add_node("validate_input", validate_input_node)
    graph.add_node("planner", planner_node)
    # LangGraph's add_node overload currently cannot infer a wrapped coroutine node.
    graph.add_node("researcher", cast(Any, _sync(researcher_node)))
    graph.add_node("source_processor", source_processor_node)
    graph.add_node("claim_builder", claim_builder_node)
    graph.add_node("coverage_checker", coverage_checker_node)
    graph.add_node("outline_builder", outline_builder_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("writer", writer_node)
    graph.add_node("citation_checker", citation_checker_node)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("publisher", publisher_node)
    graph.add_node("human_review", human_review_node)

    # 固定边
    graph.add_edge(START, "validate_input")
    graph.add_edge("validate_input", "planner")
    graph.add_edge("planner", "researcher")
    graph.add_edge("researcher", "source_processor")
    graph.add_edge("source_processor", "claim_builder")
    graph.add_edge("claim_builder", "coverage_checker")
    graph.add_edge("coverage_checker", "outline_builder")
    graph.add_edge("outline_builder", "analyst")
    graph.add_edge("analyst", "writer")
    graph.add_edge("writer", "citation_checker")
    graph.add_edge("citation_checker", "reviewer")

    # 审查后路由
    graph.add_conditional_edges(
        "reviewer",
        should_revise_or_end,
        {"writer": "writer", "publisher": "publisher", "human_review": "human_review"},
    )

    # 人工审批后路由
    graph.add_conditional_edges(
        "human_review",
        after_human_review,
        {"writer": "writer", "publisher": "publisher", "human_review": "human_review", "end": END},
    )

    graph.add_edge("publisher", END)

    _graph_instance = graph.compile(checkpointer=_build_checkpointer(), interrupt_before=[])
    return _graph_instance


def reset_graph() -> None:
    global _checkpoint_connection, _graph_instance
    _graph_instance = None
    if _checkpoint_connection is not None:
        _checkpoint_connection.close()
        _checkpoint_connection = None
