"""数据访问层 — 业务 CRUD 操作"""

from __future__ import annotations

import json
from datetime import datetime

from src.database import get_session
from src.models import (
    Claim,
    HumanDecision,
    NodeExecutionRecord,
    ReportVersion,
    ReviewResult,
    Source,
    new_id,
)
from src.orm_models import (
    ClaimORM,
    EvidenceORM,
    HumanDecisionORM,
    NodeExecutionORM,
    ReportVersionORM,
    ResearchRunORM,
    ReviewORM,
    SourceORM,
)

# ═══════════════════════════════════════════
# 研究运行
# ═══════════════════════════════════════════


def create_run(run_id: str, thread_id: str, topic: str, **kwargs) -> ResearchRunORM:
    """创建新运行记录"""
    session = get_session()
    try:
        run = ResearchRunORM(
            id=run_id,
            thread_id=thread_id,
            topic=topic,
            language=kwargs.get("language", "zh-CN"),
            target_words=kwargs.get("target_words", 2500),
            require_human_approval=kwargs.get("require_human_approval", True),
            status="queued",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        return run
    finally:
        session.close()


def get_run(run_id: str) -> ResearchRunORM | None:
    """获取运行记录"""
    session = get_session()
    try:
        return session.query(ResearchRunORM).filter(ResearchRunORM.id == run_id).first()
    finally:
        session.close()


def update_run_status(run_id: str, status: str, **updates) -> None:
    """更新运行状态"""
    session = get_session()
    try:
        run = session.query(ResearchRunORM).filter(ResearchRunORM.id == run_id).first()
        if run:
            run.status = status
            run.updated_at = datetime.now()
            for key, value in updates.items():
                setattr(run, key, value)
            if status == "completed":
                run.completed_at = datetime.now()
            session.commit()
    finally:
        session.close()


def list_runs(limit: int = 20, offset: int = 0) -> list[ResearchRunORM]:
    """列出运行记录"""
    session = get_session()
    try:
        return (
            session.query(ResearchRunORM)
            .order_by(ResearchRunORM.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
    finally:
        session.close()


# ═══════════════════════════════════════════
# 来源
# ═══════════════════════════════════════════


def save_sources(run_id: str, sources: list[Source]) -> int:
    """保存来源列表"""
    session = get_session()
    count = 0
    try:
        for source in sources:
            orm = SourceORM(
                id=source.id,
                run_id=run_id,
                canonical_url=source.canonical_url,
                title=source.title,
                publisher=source.publisher,
                author=source.author,
                published_at=source.published_at,
                retrieved_at=source.retrieved_at,
                source_type=source.source_type,
                content_hash=source.content_hash,
                content_location=source.content_location,
                extraction_status=source.extraction_status,
                extraction_error=source.extraction_error,
                credibility_score=source.credibility_score,
                credibility_reasons=json.dumps(source.credibility_reasons, ensure_ascii=False),
            )
            session.merge(orm)  # upsert
            count += 1
        session.commit()
    finally:
        session.close()
    return count


def get_sources(run_id: str) -> list[SourceORM]:
    """获取运行的所有来源"""
    session = get_session()
    try:
        return session.query(SourceORM).filter(SourceORM.run_id == run_id).all()
    finally:
        session.close()


# ═══════════════════════════════════════════
# 结论
# ═══════════════════════════════════════════


def save_claims(run_id: str, claims: list[Claim]) -> int:
    """保存结论列表"""
    session = get_session()
    count = 0
    try:
        for claim in claims:
            orm = ClaimORM(
                id=claim.id,
                run_id=run_id,
                text=claim.text,
                question_id=claim.question_id,
                confidence=claim.confidence,
                status=claim.status,
            )
            session.merge(orm)

            # 保存证据
            for ev in claim.evidence:
                ev_orm = EvidenceORM(
                    id=new_id("ev_"),
                    claim_id=claim.id,
                    source_id=ev.source_id,
                    quote=ev.quote,
                    supports_claim=ev.supports_claim,
                    notes=ev.notes,
                )
                session.merge(ev_orm)
            count += 1
        session.commit()
    finally:
        session.close()
    return count


# ═══════════════════════════════════════════
# 报告版本
# ═══════════════════════════════════════════


def save_report_version(run_id: str, version: ReportVersion) -> None:
    """保存报告版本"""
    session = get_session()
    try:
        orm = ReportVersionORM(
            id=version.id,
            run_id=run_id,
            version=version.version,
            markdown=version.markdown,
            created_by_node=version.created_by_node,
            created_at=version.created_at,
            citation_ids=json.dumps(version.citation_ids, ensure_ascii=False),
        )
        session.add(orm)
        session.commit()
    finally:
        session.close()


def get_report_versions(run_id: str) -> list[ReportVersionORM]:
    """获取报告版本列表"""
    session = get_session()
    try:
        return (
            session.query(ReportVersionORM)
            .filter(ReportVersionORM.run_id == run_id)
            .order_by(ReportVersionORM.version.desc())
            .all()
        )
    finally:
        session.close()


# ═══════════════════════════════════════════
# 审查
# ═══════════════════════════════════════════


def save_review(run_id: str, iteration: int, review: ReviewResult) -> None:
    """保存审查记录"""
    session = get_session()
    try:
        orm = ReviewORM(
            id=new_id("rev_"),
            run_id=run_id,
            iteration=iteration,
            verdict=review.verdict,
            factuality_score=review.factuality_score,
            citation_score=review.citation_score,
            coverage_score=review.coverage_score,
            structure_score=review.structure_score,
            issues_json=json.dumps(
                [i.model_dump() for i in review.issues],
                ensure_ascii=False,
            )
            if review.issues
            else None,
            summary=review.summary,
            created_at=datetime.now(),
        )
        session.add(orm)
        session.commit()
    finally:
        session.close()


def save_human_decision(run_id: str, decision: HumanDecision) -> None:
    """保存人工决策"""
    session = get_session()
    try:
        orm = HumanDecisionORM(
            id=new_id("hd_"),
            run_id=run_id,
            action=decision.action,
            feedback=decision.feedback,
            decided_at=decision.decided_at,
        )
        session.add(orm)
        session.commit()
    finally:
        session.close()


# ═══════════════════════════════════════════
# 节点执行记录
# ═══════════════════════════════════════════


def save_node_execution(run_id: str, record: NodeExecutionRecord) -> None:
    """保存节点执行记录"""
    session = get_session()
    try:
        orm = NodeExecutionORM(
            id=new_id("ne_"),
            run_id=run_id,
            node_name=record.node_name,
            status=record.status,
            model=record.model,
            prompt_tokens=record.prompt_tokens,
            completion_tokens=record.completion_tokens,
            cost_usd=float(record.cost_usd),
            error_type=record.error_type,
            error_message=record.error_message,
            started_at=record.started_at,
            ended_at=record.ended_at,
        )
        session.add(orm)
        session.commit()
    finally:
        session.close()
