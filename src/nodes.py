"""Agent 节点实现 — 每个节点是一个 LangGraph 图中的节点函数

关键原则:
- Reviewer 使用结构化输出, 不从字符串解析 APPROVED 关键字
- Publisher 独立节点, 职责分离
- Human review 使用真正的 interrupt()
- 错误分类处理, 不可恢复错误不重试
- 搜索失败不导致整个任务崩溃
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import interrupt

from src.config import settings
from src.state import CrewState
from src.models import (
    ResearchRequirements,
    ResearchPlan,
    ReviewResult,
    ReviewIssue,
    HumanDecision,
    ReportVersion,
    NodeExecutionRecord,
    new_id,
    Claim,
    Evidence,
    Source,
    SearchResult,
)
from src.prompts import (
    RESEARCHER_PROMPT,
    ANALYST_PROMPT,
    WRITER_PROMPT,
    REVIEWER_PROMPT,
)
from src.tools import save_report


# ═══════════════════════════════════════════
# 搜索提供商 (延迟初始化)
# ═══════════════════════════════════════════

_search_provider = None


def _get_search_provider():
    """获取搜索提供商

    有 TAVILY_API_KEY 时使用 Tavily, 否则使用模拟搜索。
    """
    global _search_provider
    if _search_provider is not None:
        return _search_provider

    if settings.TAVILY_API_KEY:
        from src.search.providers import TavilySearchProvider
        _search_provider = TavilySearchProvider(api_key=settings.TAVILY_API_KEY)
    else:
        # 模拟搜索 (开发/演示用)
        from src.search import SearchResultItem as MockItem
        class MockSearchProvider:
            async def search(self, query, **kwargs):
                return [
                    MockItem(
                        query=query,
                        url=f"https://example.com/result-{i}",
                        title=f"关于 '{query[:20]}' 的第 {i+1} 条结果",
                        snippet=f"这是关于 {query[:20]} 的模拟搜索结果 #{i+1}。生产环境请配置 TAVILY_API_KEY。",
                        publisher="example.com",
                    )
                    for i in range(min(kwargs.get("max_results", 5), 5))
                ]
        _search_provider = MockSearchProvider()

    return _search_provider


# ═══════════════════════════════════════════
# 模型路由
# ═══════════════════════════════════════════

def _get_llm(model: str | None = None, temperature: float = 0.3):
    """获取 LLM 实例"""
    return ChatOpenAI(
        model=model or settings.RESEARCHER_MODEL,
        temperature=temperature,
        timeout=settings.REQUEST_TIMEOUT,
        max_retries=settings.MAX_RETRIES,
    )


def _structured_llm(model: str | None = None):
    """获取支持结构化输出的 LLM 实例"""
    return ChatOpenAI(
        model=model or settings.REVIEWER_MODEL,
        temperature=0.1,
        timeout=settings.REQUEST_TIMEOUT,
        max_retries=settings.MAX_RETRIES,
    )


def _start_record(node_name: str) -> NodeExecutionRecord:
    return NodeExecutionRecord(
        node_name=node_name,
        started_at=datetime.now(),
    )


# ═══════════════════════════════════════════
# Validate Input
# ═══════════════════════════════════════════

def validate_input_node(state: CrewState) -> dict:
    """输入校验 — 纯逻辑, 不调用 LLM"""
    print("  [Validate] 校验输入...")

    req = state.get("requirements")
    if not req or not req.topic.strip():
        return {"status": "failed", "errors": ["研究课题不能为空"]}

    settings.ensure_dirs()
    return {"status": "running", "current_node": "validate_input", "updated_at": datetime.now()}


# ═══════════════════════════════════════════
# Researcher (使用真实搜索)
# ═══════════════════════════════════════════

async def researcher_node(state: CrewState) -> dict:
    """研究专员：使用 SearchProvider 搜集真实信息"""
    print("  [Researcher] 正在搜索信息...")
    record = _start_record("researcher")

    topic = state["topic"]
    provider = _get_search_provider()

    # 生成搜索查询
    queries = [topic]
    queries.extend(state.get("requirements", ResearchRequirements(topic=topic)).preferred_domains[:2])

    all_results: list[SearchResult] = []
    search_errors: list[str] = []

    for query in queries[:3]:  # 最多 3 个查询
        try:
            items = await provider.search(
                query,
                max_results=5,
                domains=state.get("requirements", ResearchRequirements(topic=topic)).preferred_domains or None,
            )
            for item in items:
                all_results.append(SearchResult(
                    url=item.url,
                    title=item.title,
                    snippet=item.snippet,
                    publisher=item.publisher,
                    author=item.author,
                    published_at=item.published_at,
                    retrieved_at=item.retrieved_at,
                ))
            print(f"  [Researcher] 查询 '{query[:40]}' → {len(items)} 条结果")
        except Exception as e:
            err_msg = f"搜索查询失败 '{query[:40]}': {type(e).__name__}: {e}"
            print(f"  ⚠️ {err_msg}")
            search_errors.append(err_msg)

    # 用 LLM 整理搜索结果
    llm = _get_llm(temperature=0.3)
    formatted_results = "\n\n".join(
        f"标题: {r.title}\n来源: {r.url}\n摘要: {r.snippet}\n"
        for r in all_results[:10]
    ) or "搜索无结果"

    msgs = [
        SystemMessage(content=RESEARCHER_PROMPT.format(
            topic=topic,
            search_results=formatted_results,
            language="zh-CN",
        )),
        HumanMessage(content="请开始搜集信息"),
    ]

    try:
        response = llm.invoke(msgs)
        record.status = "completed"
        record.ended_at = datetime.now()
        record.output_summary = f"搜索到 {len(all_results)} 条结果, 误差 {len(search_errors)} 条"

        return {
            "draft": response.content,  # 保持向后兼容
            "search_results": all_results,
            "current_node": "researcher",
            "errors": search_errors if search_errors else [],
            "updated_at": datetime.now(),
            "node_executions": [record],
        }
    except Exception as e:
        record.status = "failed"
        record.ended_at = datetime.now()
        record.error_type = type(e).__name__
        return {
            "errors": [f"Researcher 整理失败: {e}"],
            "current_node": "researcher",
            "updated_at": datetime.now(),
            "node_executions": [record],
        }


# ═══════════════════════════════════════════
# Source Processor (来源抓取 + 处理)
# ═══════════════════════════════════════════

def source_processor_node(state: CrewState) -> dict:
    """来源处理器：抓取正文、去重、可信度评估、保存快照"""
    print("  [SourceProcessor] 正在处理来源...")
    record = _start_record("source_processor")

    from src.services.source_service import (
        normalize_url,
        fetch_webpage,
        content_hash,
        deduplicate_sources,
        evaluate_credibility,
        url_to_source_type,
    )

    search_results = state.get("search_results", [])
    existing_sources = state.get("sources", [])

    if not search_results:
        return {
            "current_node": "source_processor",
            "updated_at": datetime.now(),
            "node_executions": [record],
        }

    # 去重
    result_items = [
        SearchResult(
            url=r.url, title=r.title, snippet=r.snippet,
            publisher=r.publisher, author=r.author, published_at=r.published_at,
        )
        for r in search_results
    ]
    new_sources = deduplicate_sources(existing_sources, result_items)

    if not new_sources:
        print("  [SourceProcessor] 无新来源")
        record.status = "completed"
        record.ended_at = datetime.now()
        return {
            "current_node": "source_processor",
            "updated_at": datetime.now(),
            "node_executions": [record],
        }

    # 抓取正文 (最多前 10 个)
    errors: list[str] = []
    for source in new_sources[:10]:
        result = fetch_webpage(source.canonical_url, timeout=10)
        if result["error"]:
            source.extraction_status = "failed"
            source.extraction_error = result["error"]
            errors.append(f"抓取失败: {source.canonical_url[:60]} - {result['error']}")
            continue

        source.extraction_status = "success"
        source.content_hash = content_hash(result["content"])

        # 保存正文快照
        artifact_path = settings.ARTIFACTS_DIR / f"{source.id}.txt"
        try:
            artifact_path.write_text(result["content"], encoding="utf-8")
            source.content_location = str(artifact_path)
        except Exception as e:
            errors.append(f"保存快照失败 {source.id}: {e}")

        # 补充元数据
        if not source.title and result["title"]:
            source.title = result["title"]
        source.source_type = url_to_source_type(source.canonical_url)

        # 可信度评估
        score, reasons = evaluate_credibility(source, result["content"])
        source.credibility_score = score
        source.credibility_reasons = reasons

        print(f"  [SourceProcessor] 已处理: {source.title[:40]} ({source.source_type})")

    record.status = "completed"
    record.ended_at = datetime.now()
    return {
        "sources": new_sources,
        "errors": errors if errors else [],
        "current_node": "source_processor",
        "updated_at": datetime.now(),
        "node_executions": [record],
    }


# ═══════════════════════════════════════════
# Analyst
# ═══════════════════════════════════════════

def analyst_node(state: CrewState) -> dict:
    """分析师：基于搜集的信息分析"""
    print("  [Analyst] 正在分析信息...")
    record = _start_record("analyst")

    llm = _get_llm(temperature=0.4)
    msgs = [
        SystemMessage(content=ANALYST_PROMPT.format(
            search_results=state.get("draft", "无研究资料"),
            language="zh-CN",
        )),
        HumanMessage(content="请开始分析"),
    ]

    try:
        response = llm.invoke(msgs)
        record.status = "completed"
        record.ended_at = datetime.now()
        return {
            "analysis": response.content,
            "current_node": "analyst",
            "updated_at": datetime.now(),
            "node_executions": [record],
        }
    except Exception as e:
        record.status = "failed"
        record.ended_at = datetime.now()
        record.error_type = type(e).__name__
        return {
            "errors": [f"Analyst 失败: {e}"],
            "current_node": "analyst",
            "node_executions": [record],
        }


# ═══════════════════════════════════════════
# Writer
# ═══════════════════════════════════════════

def writer_node(state: CrewState) -> dict:
    """撰稿人：撰写/修改报告"""
    print("  [Writer] 正在撰写报告...")
    record = _start_record("writer")

    feedback_section = ""
    if state.get("review") and state["review"].issues:
        issues_str = "\n".join(
            f"- [{i.severity}] {i.category}: {i.description}"
            for i in state["review"].issues
        )
        feedback_section = f"审查反馈 (请据此修改):\n{issues_str}"

    # 引用来源信息
    sources = state.get("sources", [])
    sources_str = "\n".join(
        f"[{s.id}] {s.title}" + (f" - {s.canonical_url}" if s.canonical_url else "")
        for s in sources[:20]
    )

    llm = _get_llm(model=settings.WRITER_MODEL, temperature=0.5)
    msgs = [
        SystemMessage(content=WRITER_PROMPT.format(
            claims=sources_str,
            analysis=state.get("draft", state.get("analysis", "")),
            outline="",
            feedback_section=feedback_section,
            language="zh-CN",
            target_words=2500,
        )),
        HumanMessage(content="请开始撰写"),
    ]

    try:
        response = llm.invoke(msgs)
        record.status = "completed"
        record.ended_at = datetime.now()

        total_versions = len(state.get("report_versions", []))
        new_version = ReportVersion(
            id=new_id("R"),
            run_id=state["run_id"],
            version=total_versions + 1,
            markdown=response.content,
            created_by_node="writer",
            based_on_version=state.get("draft_id"),
        )

        return {
            "draft": response.content,
            "draft_id": new_version.id,
            "report_versions": [new_version],
            "current_node": "writer",
            "updated_at": datetime.now(),
            "node_executions": [record],
        }
    except Exception as e:
        record.status = "failed"
        record.ended_at = datetime.now()
        record.error_type = type(e).__name__
        return {
            "errors": [f"Writer 失败: {e}"],
            "current_node": "writer",
            "node_executions": [record],
        }


# ═══════════════════════════════════════════
# Reviewer (结构化输出)
# ═══════════════════════════════════════════

def reviewer_node(state: CrewState) -> dict:
    """审查员：结构化质量审查"""
    print("  [Reviewer] 正在审查报告...")
    record = _start_record("reviewer")

    draft = state.get("draft", "")
    if not draft:
        return {
            "review": ReviewResult(
                verdict="human_review",
                factuality_score=0, citation_score=0,
                coverage_score=0, structure_score=0,
                issues=[ReviewIssue(
                    category="structure", severity="critical",
                    description="报告草稿为空",
                    suggestion="请重新生成报告",
                )],
            ),
            "current_node": "reviewer",
            "updated_at": datetime.now(),
            "node_executions": [record],
        }

    structured_reviewer = _structured_llm(
        model=settings.REVIEWER_MODEL
    ).with_structured_output(ReviewResult)

    msgs = [
        SystemMessage(content=REVIEWER_PROMPT.format(draft=draft)),
        HumanMessage(content="请审查"),
    ]

    try:
        review: ReviewResult = structured_reviewer.invoke(msgs)
        record.status = "completed"
        record.ended_at = datetime.now()

        iteration = state.get("iteration", 0) + 1
        print(f"  [Reviewer] 裁定: {review.verdict} (第{iteration}轮)")
        print(f"    事实:{review.factuality_score} 引用:{review.citation_score} 覆盖:{review.coverage_score} 结构:{review.structure_score}")

        quality_status = "passed" if review.verdict == "approved" else \
                        "needs_human_review" if review.verdict == "human_review" else "failed"

        return {
            "review": review,
            "iteration": iteration,
            "quality_status": quality_status,
            "current_node": "reviewer",
            "updated_at": datetime.now(),
            "node_executions": [record],
        }
    except Exception as e:
        record.status = "failed"
        record.ended_at = datetime.now()
        record.error_type = type(e).__name__
        return {
            "errors": [f"Reviewer 失败: {e}"],
            "review": ReviewResult(
                verdict="human_review",
                factuality_score=0, citation_score=0,
                coverage_score=0, structure_score=0,
                issues=[ReviewIssue(
                    category="factuality", severity="critical",
                    description=f"审查引擎错误: {e}",
                    suggestion="请人工判断",
                )],
            ),
            "quality_status": "needs_human_review",
            "current_node": "reviewer",
            "node_executions": [record],
        }


# ═══════════════════════════════════════════
# Publisher
# ═══════════════════════════════════════════

def publisher_node(state: CrewState) -> dict:
    """发布员：固化最终版本并导出"""
    print("  [Publisher] 正在固化最终报告...")
    record = _start_record("publisher")

    draft = state.get("draft", "")
    if not draft:
        return {
            "errors": ["Publisher: draft 为空"],
            "current_node": "publisher",
            "node_executions": [record],
        }

    try:
        save_path = save_report(draft, state["topic"])
        print(f"  [Publisher] 已保存: {save_path}")

        final_version = ReportVersion(
            id=new_id("R"),
            run_id=state["run_id"],
            version=len(state.get("report_versions", [])) + 1,
            markdown=draft,
            created_by_node="publisher",
            created_at=datetime.now(),
        )

        return {
            "final_report_id": final_version.id,
            "final_report": draft,
            "status": "completed",
            "current_node": "publisher",
            "updated_at": datetime.now(),
            "report_versions": [final_version],
            "node_executions": [record],
        }
    except Exception as e:
        record.status = "failed"
        record.ended_at = datetime.now()
        record.error_type = type(e).__name__
        return {
            "errors": [f"Publisher 失败: {e}"],
            "current_node": "publisher",
            "node_executions": [record],
        }


# ═══════════════════════════════════════════
# Human Review
# ═══════════════════════════════════════════

def human_review_node(state: CrewState) -> dict:
    """人工审查节点 — 使用 interrupt() 暂停"""
    print("  [HumanReview] 等待人工审批...")

    review = state.get("review")
    draft = state.get("draft", "")

    review_info = {
        "run_id": state["run_id"],
        "topic": state["topic"],
        "draft_preview": draft[:500] + "..." if len(draft) > 500 else draft,
        "review_summary": review.summary if review else "无审查结果",
        "review_scores": {
            "factuality": review.factuality_score if review else 0,
            "citation": review.citation_score if review else 0,
            "coverage": review.coverage_score if review else 0,
            "structure": review.structure_score if review else 0,
        } if review else {},
        "issues": [i.model_dump() for i in review.issues] if review and review.issues else [],
        "allowed_actions": ["approve", "revise", "cancel"],
    }

    decision_data = interrupt(review_info)

    if isinstance(decision_data, dict):
        decision = HumanDecision(
            action=decision_data.get("action", "revise"),
            feedback=decision_data.get("feedback", ""),
        )
    else:
        decision = HumanDecision(action="revise", feedback=str(decision_data))

    print(f"  [HumanReview] 决策: {decision.action}")

    result: dict = {
        "human_decision": decision,
        "current_node": "human_review",
        "updated_at": datetime.now(),
    }
    if decision.action == "approve":
        result["status"] = "completed"
    elif decision.action == "cancel":
        result["status"] = "cancelled"

    return result


# ═══════════════════════════════════════════
# Claim Builder (从来源提取结构化结论)
# ═══════════════════════════════════════════

def claim_builder_node(state: CrewState) -> dict:
    """结论提取节点：从来源正文中提取结构化 Claim 和 Evidence

    使用 structured output 确保每个结论都有原文引用。
    不生成来源中没有的事实。
    """
    print("  [ClaimBuilder] 正在提取研究结论...")
    record = _start_record("claim_builder")

    from src.services.claim_service import extract_all_claims

    sources = state.get("sources", [])
    topic = state["topic"]

    if not sources:
        return {
            "current_node": "claim_builder",
            "updated_at": datetime.now(),
            "node_executions": [record],
        }

    try:
        claims = extract_all_claims(sources, topic)

        record.status = "completed" if claims else "completed"
        record.ended_at = datetime.now()
        record.output_summary = f"提取 {len(claims)} 条结论"

        # Also detect conflicts
        from src.services.citation_service import detect_conflicting_claims
        conflicts = detect_conflicting_claims(claims)
        if conflicts:
            print(f"  [ClaimBuilder] 检测到 {len(conflicts)} 组来源冲突")
            for c in conflicts:
                print(f"    ⚠️  冲突: {c['text_a'][:40]} ↔ {c['text_b'][:40]}")

        return {
            "claims": claims,
            "current_node": "claim_builder",
            "errors": [f"{len(conflicts)} 组来源冲突"] if conflicts else [],
            "updated_at": datetime.now(),
            "node_executions": [record],
        }
    except Exception as e:
        record.status = "failed"
        record.ended_at = datetime.now()
        record.error_type = type(e).__name__
        return {
            "errors": [f"ClaimBuilder 失败: {e}"],
            "current_node": "claim_builder",
            "node_executions": [record],
        }


# ═══════════════════════════════════════════
# Citation Checker (确定性检查, 不调用 LLM)
# ═══════════════════════════════════════════

def citation_checker_node(state: CrewState) -> dict:
    """引用检查器：检查引用有效性和覆盖度

    纯确定性代码，不调用 LLM：
    1. 检查 [Sxxx] 引用是否指向存在的 Source
    2. 检查关键断言是否有引用
    3. 报告覆盖度
    """
    print("  [CitationChecker] 正在检查引用...")
    record = _start_record("citation_checker")

    from src.services.citation_service import (
        check_citations,
        find_uncited_assertions,
    )

    draft = state.get("draft", "")
    sources = state.get("sources", [])

    if not draft:
        return {
            "current_node": "citation_checker",
            "updated_at": datetime.now(),
            "node_executions": [record],
        }

    try:
        # 引用有效性
        citation_report = check_citations(draft, sources)
        print(f"  [CitationChecker] 引用覆盖: {citation_report.coverage_rate:.0%}")
        print(f"    有效: {len(citation_report.valid_citations)}, 无效: {len(citation_report.invalid_citations)}")

        # 无来源断言
        uncited = find_uncited_assertions(draft)
        if uncited:
            print(f"  [CitationChecker] 发现 {len(uncited)} 个无引用断言")

        # 生成检查问题
        issues: list[ReviewIssue] = []
        for invalid in citation_report.invalid_citations:
            issues.append(ReviewIssue(
                category="citation",
                severity="critical",
                description=f"引用 [S{invalid.source_id}] 指向不存在的来源",
                suggestion="请修正为实际存在的 Source ID",
            ))

        if citation_report.coverage_rate < 0.5 and citation_report.valid_citations:
            issues.append(ReviewIssue(
                category="citation",
                severity="high",
                description=f"引用覆盖率仅 {citation_report.coverage_rate:.0%}",
                suggestion="请确保每个关键断言都有来源支持",
            ))

        record.status = "completed"
        record.ended_at = datetime.now()

        return {
            "citation_report": citation_report,
            "current_node": "citation_checker",
            "updated_at": datetime.now(),
            "node_executions": [record],
        }
    except Exception as e:
        record.status = "failed"
        record.ended_at = datetime.now()
        record.error_type = type(e).__name__
        return {
            "errors": [f"CitationChecker 失败: {e}"],
            "current_node": "citation_checker",
            "node_executions": [record],
        }

