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
from functools import wraps

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from src.state import CrewState
from src.nodes import (
    validate_input_node,
    researcher_node,
    source_processor_node,
    claim_builder_node,
    analyst_node,
    writer_node,
    citation_checker_node,
    reviewer_node,
    publisher_node,
    human_review_node,
)
from src.nodes_extra import (
    planner_node,
    outline_builder_node,
    coverage_checker_node,
)
from src.edges import should_revise_or_end, after_human_review


def _sync(f):
    @wraps(f)
    def wrapper(state: CrewState):
        return asyncio.run(f(state))
    return wrapper


_graph_instance = None


def build_graph() -> StateGraph:
    global _graph_instance
    if _graph_instance is not None:
        return _graph_instance

    graph = StateGraph(CrewState)

    # 节点
    graph.add_node("validate_input", validate_input_node)
    graph.add_node("planner", planner_node)
    graph.add_node("researcher", _sync(researcher_node))
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

    memory = MemorySaver()
    _graph_instance = graph.compile(checkpointer=memory, interrupt_before=[])
    return _graph_instance


def reset_graph():
    global _graph_instance
    _graph_instance = None
