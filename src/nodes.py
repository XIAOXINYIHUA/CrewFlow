"""Agent 节点实现 - 每个节点是一个 LangGraph 图中的节点函数"""

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from .state import CrewState
from .prompts import (
    RESEARCHER_PROMPT,
    ANALYST_PROMPT,
    WRITER_PROMPT,
    REVIEWER_PROMPT,
)
from .tools import web_search, save_report


def get_llm():
    """获取 LLM 实例"""
    return ChatOpenAI(model="gpt-4o-mini", temperature=0.7)


def researcher_node(state: CrewState) -> dict:
    """研究专员：搜集信息"""
    print("🔍 Researcher 正在搜集信息...")
    llm = get_llm()
    topic = state["topic"]

    # 搜索相关信息
    search_result = web_search(topic)

    # LLM 整理搜索结果
    messages = [
        SystemMessage(content=RESEARCHER_PROMPT.format(topic=topic)),
        HumanMessage(content=f"以下是搜索结果，请整理：\n\n{search_result}"),
    ]
    response = llm.invoke(messages)

    return {
        "search_results": response.content,
        "step": "researcher",
    }


def analyst_node(state: CrewState) -> dict:
    """分析师：深度分析"""
    print("📊 Analyst 正在分析信息...")
    llm = get_llm()

    messages = [
        SystemMessage(content=ANALYST_PROMPT.format(
            search_results=state.get("search_results", "无研究资料"),
        )),
        HumanMessage(content="请开始分析"),
    ]
    response = llm.invoke(messages)

    return {
        "analysis": response.content,
        "step": "analyst",
    }


def writer_node(state: CrewState) -> dict:
    """撰稿人：撰写报告"""
    print("✍️ Writer 正在撰写报告...")
    llm = get_llm()

    # 如果有审查反馈，加入 prompt
    feedback_section = ""
    if state.get("review_feedback"):
        feedback_section = f"审查反馈（请据此修改）:\n{state['review_feedback']}"

    messages = [
        SystemMessage(content=WRITER_PROMPT.format(
            search_results=state.get("search_results", ""),
            analysis=state.get("analysis", ""),
            feedback_section=feedback_section,
        )),
        HumanMessage(content="请开始撰写"),
    ]
    response = llm.invoke(messages)

    return {
        "draft": response.content,
        "step": "writer",
        "review_feedback": None,  # 清除反馈，下次审查用新的
    }


def reviewer_node(state: CrewState) -> dict:
    """审查员：质量审查"""
    print("🔎 Reviewer 正在审查报告...")
    llm = get_llm()

    messages = [
        SystemMessage(content=REVIEWER_PROMPT.format(
            draft=state.get("draft", ""),
        )),
        HumanMessage(content="请审查"),
    ]
    response = llm.invoke(messages)

    feedback = response.content
    iteration = state.get("iteration", 0) + 1

    # 如果通过审查
    if "APPROVED" in feedback.upper():
        final_report = state.get("draft", "")
        save_msg = save_report(final_report, state.get("topic", "research"))
        print(f"✅ {save_msg}")
        return {
            "review_feedback": None,
            "final_report": final_report,
            "step": "approved",
            "iteration": iteration,
        }

    # 需要修改
    print(f"⚠️ 审查未通过（第{iteration}次），建议修改")
    return {
        "review_feedback": feedback,
        "step": "reviewer",
        "iteration": iteration,
    }


def human_review_node(state: CrewState) -> dict:
    """人工审查节点（Human-in-the-Loop）

    LangGraph 会在遇到 interrupt() 时暂停，等待人工输入
    """
    print("👤 等待人工审查...")
    return {"step": "human_review"}
