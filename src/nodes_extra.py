"""额外节点 — Planner, Outline Builder, Coverage Checker

与 nodes.py 分离, 避免单文件过长。
"""

from __future__ import annotations

from datetime import datetime

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from src.config import settings
from src.models import (
    NodeExecutionRecord,
    ResearchPlan,
    ResearchQuestion,
    SearchQuery,
    new_id,
)
from src.prompts import PLANNER_PROMPT
from src.state import CrewState

# ═══════════════════════════════════════════
# Planner (结构化输出 ResearchPlan)
# ═══════════════════════════════════════════


def planner_node(state: CrewState) -> dict:
    """研究规划节点：输出结构化 ResearchPlan"""
    print("  [Planner] 正在制定研究计划...")
    record = NodeExecutionRecord(
        node_name="planner", started_at=datetime.now(), model=settings.PLANNER_MODEL
    )

    req = state["requirements"]
    llm = ChatOpenAI(
        model=settings.PLANNER_MODEL,
        temperature=0.2,
        timeout=settings.REQUEST_TIMEOUT,
        max_retries=settings.MAX_RETRIES,
    )
    structured = llm.with_structured_output(ResearchPlan)

    msgs = [
        SystemMessage(
            content=PLANNER_PROMPT.format(
                topic=req.topic, purpose=req.purpose or "通用调研", audience=req.audience
            )
        ),
        HumanMessage(content="请制定研究计划"),
    ]

    try:
        plan: ResearchPlan = structured.invoke(msgs)
        plan.questions = plan.questions[:6]
        max_q = min(req.max_queries, 12)
        seen = {q.id for q in plan.questions}
        plan.queries = [q for q in (plan.queries or []) if q.question_id in seen][:max_q]

        # 中文课题自动补充英文搜索
        if req.language == "zh-CN" and plan.questions:
            engs = [
                q for q in (plan.queries or []) if any(c.isascii() and c.isalpha() for c in q.query)
            ]
            if not engs:
                plan.queries.append(
                    SearchQuery(
                        id=new_id("sq_"),
                        question_id=plan.questions[0].id,
                        query=req.topic,
                        language="en",
                    )
                )

        print(f"  [Planner] {len(plan.questions)}Q / {len(plan.queries or [])}S")
        record.status = "completed"
        record.ended_at = datetime.now()
        return {
            "research_plan": plan,
            "current_node": "planner",
            "node_executions": [record],
            "updated_at": datetime.now(),
        }

    except Exception as e:
        record.status = "failed"
        record.ended_at = datetime.now()
        record.error_type = type(e).__name__
        return {
            "errors": [f"Planner 失败: {e}"],
            "research_plan": ResearchPlan(
                thesis=req.topic,
                questions=[ResearchQuestion(question=req.topic, importance=5)],
                queries=[SearchQuery(question_id="q_fb", query=req.topic)],
                completion_criteria=["完成"],
            ),
            "node_executions": [record],
        }


# ═══════════════════════════════════════════
# Outline Builder (结构化大纲)
# ═══════════════════════════════════════════


class SectionOutline(BaseModel):
    """单节大纲"""

    title: str = Field(..., description="节标题")
    purpose: str = Field("", description="本节目标")
    claim_ids: list[str] = Field(default_factory=list, description="使用的 Claim ID")
    target_words: int = Field(500, ge=50, description="预计字数")
    required_perspectives: list[str] = Field(default_factory=list, description="必须覆盖的视角")
    notes: str | None = Field(None, description="写作提示")


class ReportOutline(BaseModel):
    """报告大纲"""

    sections: list[SectionOutline] = Field(default_factory=list)
    estimated_total_words: int = Field(0, ge=0)


def outline_builder_node(state: CrewState) -> dict:
    """大纲生成节点：写作前生成结构化大纲"""
    print("  [OutlineBuilder] 正在生成大纲...")
    record = NodeExecutionRecord(node_name="outline_builder", started_at=datetime.now())

    llm = ChatOpenAI(
        model=settings.WRITER_MODEL, temperature=0.3, timeout=settings.REQUEST_TIMEOUT
    ).with_structured_output(ReportOutline)

    claims = state.get("claims", [])
    claims_str = "\n".join(f"- [{c.id}] {c.text} (置信度:{c.confidence})" for c in claims[:15])
    msgs = [
        SystemMessage(
            content=(
                f"你是一名报告结构专家。课题: {state['topic']}\n\n"
                f"结论:\n{claims_str or '(无)'}\n\n要求:\n"
                "1. 覆盖主要维度 2. 每节指定 Claim ID 3. 每节字数 "
                "4. 逻辑递进: 背景->现状->分析->结论->局限"
            )
        ),
        HumanMessage(content="生成大纲"),
    ]

    try:
        outline: ReportOutline = llm.invoke(msgs)
        print(
            f"  [OutlineBuilder] {len(outline.sections)} 节, 约 {outline.estimated_total_words} 字"
        )
        record.status = "completed"
        record.ended_at = datetime.now()
        return {"outline": outline.model_dump(), "node_executions": [record]}
    except Exception as e:
        record.status = "failed"
        record.ended_at = datetime.now()
        record.error_type = type(e).__name__
        return {"errors": [f"OutlineBuilder 失败: {e}"], "node_executions": [record]}


# ═══════════════════════════════════════════
# Coverage Checker (确定性的覆盖度检查, 不调用 LLM)
# ═══════════════════════════════════════════


def coverage_checker_node(state: CrewState) -> dict:
    """检查每个 ResearchQuestion 是否有足够的 Source 和 Claim 覆盖"""
    print("  [CoverageChecker] 正在检查覆盖度...")
    record = NodeExecutionRecord(node_name="coverage_checker", started_at=datetime.now())

    plan = state.get("research_plan")
    claims = state.get("claims", [])
    gaps: list[str] = []

    if not plan or not plan.questions:
        record.status = "completed"
        record.ended_at = datetime.now()
        return {"node_executions": [record]}

    from collections import defaultdict

    q_src: dict[str, set[str]] = defaultdict(set)
    q_clm: dict[str, list[str]] = defaultdict(list)

    for c in claims:
        q_clm[c.question_id].append(c.text)
        for ev in c.evidence:
            q_src[c.question_id].add(ev.source_id)

    for q in plan.questions:
        sc = len(q_src.get(q.id, set()))
        cc = len(q_clm.get(q.id, []))
        if sc == 0:
            gaps.append(f"问题 '{q.question[:40]}' 没有来源")
        if cc == 0:
            gaps.append(f"问题 '{q.question[:40]}' 没有 Claim")
        if q.importance >= 7 and sc < 2:
            gaps.append(f"核心问题 '{q.question[:40]}' 仅 {sc} 个来源 (需 >=2)")

    if gaps:
        print(f"  [CoverageChecker] 发现 {len(gaps)} 个覆盖缺口")
        for g in gaps[:5]:
            print(f"    {g}")

    record.status = "completed"
    record.ended_at = datetime.now()
    return {"coverage_gaps": gaps, "node_executions": [record]}
