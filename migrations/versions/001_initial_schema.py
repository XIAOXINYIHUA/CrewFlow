"""初始迁移 — 创建所有业务表

Revision ID: 001
Revises:
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "research_runs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("thread_id", sa.String(32), unique=True, index=True),
        sa.Column("topic", sa.String(500), nullable=False),
        sa.Column("status", sa.String(20), server_default="queued"),
        sa.Column("quality_status", sa.String(20), server_default="unchecked"),
        sa.Column("language", sa.String(10), server_default="zh-CN"),
        sa.Column("target_words", sa.Integer, server_default="2500"),
        sa.Column("require_human_approval", sa.Boolean, server_default="1"),
        sa.Column("current_node", sa.String(50), nullable=True),
        sa.Column("iteration", sa.Integer, server_default="0"),
        sa.Column("total_cost_usd", sa.Float, server_default="0.0"),
        sa.Column("error_count", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime, nullable=True),
    )

    op.create_table(
        "sources",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("run_id", sa.String(32), sa.ForeignKey("research_runs.id"), index=True),
        sa.Column("canonical_url", sa.Text, nullable=False),
        sa.Column("title", sa.Text, server_default=""),
        sa.Column("publisher", sa.String(200), nullable=True),
        sa.Column("author", sa.String(200), nullable=True),
        sa.Column("published_at", sa.DateTime, nullable=True),
        sa.Column("retrieved_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("source_type", sa.String(20), server_default="unknown"),
        sa.Column("content_hash", sa.String(32), server_default=""),
        sa.Column("content_location", sa.Text, server_default=""),
        sa.Column("extraction_status", sa.String(10), server_default="pending"),
        sa.Column("extraction_error", sa.Text, nullable=True),
        sa.Column("credibility_score", sa.Float, server_default="0.5"),
        sa.Column("credibility_reasons", sa.Text, nullable=True),
    )

    op.create_table(
        "claims",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("run_id", sa.String(32), sa.ForeignKey("research_runs.id"), index=True),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("question_id", sa.String(32), server_default=""),
        sa.Column("confidence", sa.Float, server_default="0.5"),
        sa.Column("status", sa.String(20), server_default="unsupported"),
    )

    op.create_table(
        "claim_evidence",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("claim_id", sa.String(32), sa.ForeignKey("claims.id"), index=True),
        sa.Column("source_id", sa.String(32), sa.ForeignKey("sources.id")),
        sa.Column("quote", sa.Text, nullable=False),
        sa.Column("supports_claim", sa.Boolean, server_default="1"),
        sa.Column("notes", sa.Text, nullable=True),
    )

    op.create_table(
        "report_versions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("run_id", sa.String(32), sa.ForeignKey("research_runs.id"), index=True),
        sa.Column("version", sa.Integer, server_default="1"),
        sa.Column("markdown", sa.Text, nullable=False),
        sa.Column("created_by_node", sa.String(50), server_default=""),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("citation_ids", sa.Text, nullable=True),
    )

    op.create_table(
        "reviews",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("run_id", sa.String(32), sa.ForeignKey("research_runs.id"), index=True),
        sa.Column("iteration", sa.Integer, server_default="0"),
        sa.Column("verdict", sa.String(20), nullable=False),
        sa.Column("factuality_score", sa.Integer, server_default="0"),
        sa.Column("citation_score", sa.Integer, server_default="0"),
        sa.Column("coverage_score", sa.Integer, server_default="0"),
        sa.Column("structure_score", sa.Integer, server_default="0"),
        sa.Column("issues_json", sa.Text, nullable=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "human_decisions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("run_id", sa.String(32), sa.ForeignKey("research_runs.id"), index=True),
        sa.Column("action", sa.String(10), nullable=False),
        sa.Column("feedback", sa.Text, nullable=True),
        sa.Column("decided_at", sa.DateTime, server_default=sa.func.now()),
    )

    op.create_table(
        "node_executions",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("run_id", sa.String(32), sa.ForeignKey("research_runs.id"), index=True),
        sa.Column("node_name", sa.String(50), nullable=False),
        sa.Column("status", sa.String(10), server_default="running"),
        sa.Column("model", sa.String(50), server_default=""),
        sa.Column("prompt_tokens", sa.Integer, server_default="0"),
        sa.Column("completion_tokens", sa.Integer, server_default="0"),
        sa.Column("cost_usd", sa.Float, server_default="0.0"),
        sa.Column("error_type", sa.String(50), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("node_executions")
    op.drop_table("human_decisions")
    op.drop_table("reviews")
    op.drop_table("report_versions")
    op.drop_table("claim_evidence")
    op.drop_table("claims")
    op.drop_table("sources")
    op.drop_table("research_runs")
