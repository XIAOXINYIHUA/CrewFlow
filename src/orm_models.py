"""SQLAlchemy ORM 模型 — 对应 Pydantic 模型的持久化存储"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Column, String, Text, DateTime, Integer, Float, Boolean,
    ForeignKey, JSON, Enum as SAEnum,
    create_engine,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base


# ═══════════════════════════════════════════
# 研究运行
# ═══════════════════════════════════════════

class ResearchRunORM(Base):
    """research_runs 表"""
    __tablename__ = "research_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    quality_status: Mapped[str] = mapped_column(String(20), default="unchecked")
    language: Mapped[str] = mapped_column(String(10), default="zh-CN")
    target_words: Mapped[int] = mapped_column(Integer, default=2500)
    require_human_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    current_node: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    iteration: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "run_id": self.id,
            "thread_id": self.thread_id,
            "topic": self.topic,
            "status": self.status,
            "quality_status": self.quality_status,
            "language": self.language,
            "require_human_approval": self.require_human_approval,
            "current_node": self.current_node,
            "iteration": self.iteration,
            "total_cost_usd": self.total_cost_usd,
            "error_count": self.error_count,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


# ═══════════════════════════════════════════
# 来源
# ═══════════════════════════════════════════

class SourceORM(Base):
    """sources 表"""
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), ForeignKey("research_runs.id"), index=True)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, default="")
    publisher: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    author: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    source_type: Mapped[str] = mapped_column(String(20), default="unknown")
    content_hash: Mapped[str] = mapped_column(String(32), default="")
    content_location: Mapped[str] = mapped_column(Text, default="")
    extraction_status: Mapped[str] = mapped_column(String(10), default="pending")
    extraction_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    credibility_score: Mapped[float] = mapped_column(Float, default=0.5)
    credibility_reasons: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list


# ═══════════════════════════════════════════
# 结论 (Claim)
# ═══════════════════════════════════════════

class ClaimORM(Base):
    """claims 表"""
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), ForeignKey("research_runs.id"), index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    question_id: Mapped[str] = mapped_column(String(32), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[str] = mapped_column(String(20), default="unsupported")


class EvidenceORM(Base):
    """claim_evidence 表"""
    __tablename__ = "claim_evidence"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    claim_id: Mapped[str] = mapped_column(String(32), ForeignKey("claims.id"), index=True)
    source_id: Mapped[str] = mapped_column(String(32), ForeignKey("sources.id"))
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    supports_claim: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ═══════════════════════════════════════════
# 报告版本
# ═══════════════════════════════════════════

class ReportVersionORM(Base):
    """report_versions 表"""
    __tablename__ = "report_versions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), ForeignKey("research_runs.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_node: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    citation_ids: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list


# ═══════════════════════════════════════════
# 审查记录
# ═══════════════════════════════════════════

class ReviewORM(Base):
    """reviews 表"""
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), ForeignKey("research_runs.id"), index=True)
    iteration: Mapped[int] = mapped_column(Integer, default=0)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    factuality_score: Mapped[int] = mapped_column(Integer, default=0)
    citation_score: Mapped[int] = mapped_column(Integer, default=0)
    coverage_score: Mapped[int] = mapped_column(Integer, default=0)
    structure_score: Mapped[int] = mapped_column(Integer, default=0)
    issues_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class HumanDecisionORM(Base):
    """human_decisions 表"""
    __tablename__ = "human_decisions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), ForeignKey("research_runs.id"), index=True)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


# ═══════════════════════════════════════════
# 节点执行记录
# ═══════════════════════════════════════════

class NodeExecutionORM(Base):
    """node_executions 表"""
    __tablename__ = "node_executions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(32), ForeignKey("research_runs.id"), index=True)
    node_name: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(10), default="running")
    model: Mapped[str] = mapped_column(String(50), default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    error_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
