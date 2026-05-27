"""LangGraph 编排 - 组装完整的协作流程图"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from .state import CrewState
from .nodes import (
    researcher_node,
    analyst_node,
    writer_node,
    reviewer_node,
    human_review_node,
)
from .edges import should_review, should_revise_or_end


def build_graph():
    """构建 CrewFlow 协作流程图

    流程:
    START → Researcher → Analyst → Writer → Reviewer → [条件] → Writer(修改) 或 END
    """
    graph = StateGraph(CrewState)

    # 添加节点
    graph.add_node("researcher", researcher_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("writer", writer_node)
    graph.add_node("reviewer", reviewer_node)

    # 添加边：固定流程
    graph.add_edge(START, "researcher")
    graph.add_edge("researcher", "analyst")
    graph.add_edge("analyst", "writer")
    graph.add_edge("writer", "reviewer")

    # 添加条件边：审查后的分支
    graph.add_conditional_edges(
        "reviewer",
        should_revise_or_end,
        {
            "writer": "writer",    # 需要修改，回到 Writer
            "end": END,            # 审查通过，结束
        },
    )

    # 编译图
    memory = MemorySaver()
    return graph.compile(checkpointer=memory)


def build_graph_with_human_review():
    """带人工审查的流程图（可选）"""
    graph = StateGraph(CrewState)

    graph.add_node("researcher", researcher_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("writer", writer_node)
    graph.add_node("reviewer", reviewer_node)
    graph.add_node("human_review", human_review_node)

    graph.add_edge(START, "researcher")
    graph.add_edge("researcher", "analyst")
    graph.add_edge("analyst", "writer")
    graph.add_edge("writer", "reviewer")

    # 审查通过后进入人工审查
    graph.add_conditional_edges(
        "reviewer",
        should_revise_or_end,
        {
            "writer": "writer",
            "end": "human_review",
        },
    )

    graph.add_edge("human_review", END)

    memory = MemorySaver()
    return graph.compile(checkpointer=memory)
