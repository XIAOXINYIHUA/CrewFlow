"""CrewFlow 核心数据模型 — 所有结构化数据的 Pydantic 定义"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl, field_validator


# ═══════════════════════════════════════════
# 枚举和字面量类型
# ═══════════════════════════════════════════

RunStatus = Literal[
    "queued",
    "running",
    "waiting_human",
    "completed",
    "failed",
    "cancelled",
]

QualityStatus = Literal[
    "unchecked",
    "passed",
    "failed",
    "needs_human_review",
]

ClaimStatus = Literal[
    "supported",
    "partially_supported",
    "conflicting",
    "unsupported",
]

SourceType = Literal[
    "official",
    "paper",
    "standard",
    "news",
    "company",
    "blog",
    "forum",
    "unknown",
]

ReviewCategory = Literal[
    "factuality",
    "citation",
    "logic",
    "coverage",
    "structure",
    "style",
]

ReviewSeverity = Literal["low", "medium", "high", "critical"]

HumanAction = Literal["approve", "revise", "cancel"]

NodeName = Literal[
    "validate_input",
    "planner",
    "researcher",
    "analyst",
    "writer",
    "reviewer",
    "publisher",
    "human_review",
    "claim_builder",
    "fact_checker",
    "source_processor",
    "coverage_checker",
    "outline_builder",
    "revision_router",
]


# ═══════════════════════════════════════════
# 字符串 ID 生成
# ═══════════════════════════════════════════

def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid4().hex[:12]}"


# ═══════════════════════════════════════════
# 研究要求 (用户输入)
# ═══════════════════════════════════════════

class ResearchRequirements(BaseModel):
    """用户输入的研究要求"""
    topic: str = Field(..., min_length=1, max_length=500, description="研究课题")
    purpose: str | None = Field(None, max_length=1000, description="研究目的")
    audience: str = Field("general", description="目标读者")
    language: str = Field("zh-CN", description="输出语言")
    target_words: int = Field(2500, ge=500, le=20000, description="目标字数")
    date_from: date | None = Field(None, description="时间范围起始")
    date_to: date | None = Field(None, description="时间范围截止")
    regions: list[str] = Field(default_factory=list, description="地域范围")
    preferred_domains: list[str] = Field(default_factory=list, description="首选来源域名")
    excluded_domains: list[str] = Field(default_factory=list, description="排除来源域名")
    require_human_approval: bool = Field(True, description="是否需要人工审批")
    max_iterations: int = Field(3, ge=1, le=10, description="最大修改轮数")
    max_queries: int = Field(12, ge=1, le=50, description="最大搜索查询数")
    max_sources: int = Field(30, ge=1, le=100, description="最大来源数")
    max_cost_usd: Decimal | None = Field(None, ge=0, description="最大预算 (USD)")

    @field_validator("date_to")
    @classmethod
    def date_range_valid(cls, v: date | None, info) -> date | None:
        if v and info.data.get("date_from") and v < info.data["date_from"]:
            raise ValueError("date_to 不能早于 date_from")
        return v

    @field_validator("preferred_domains", "excluded_domains")
    @classmethod
    def normalize_domains(cls, v: list[str]) -> list[str]:
        return [d.strip().lower().removeprefix("http://").removeprefix("https://").split("/")[0] for d in v if d.strip()]


# ═══════════════════════════════════════════
# 研究计划
# ═══════════════════════════════════════════

class ResearchQuestion(BaseModel):
    id: str = Field(default_factory=lambda: new_id("q_"))
    question: str = Field(..., description="子问题")
    importance: int = Field(5, ge=1, le=10, description="重要程度 1-10")
    expected_source_types: list[SourceType] = Field(default_factory=list)


class SearchQuery(BaseModel):
    id: str = Field(default_factory=lambda: new_id("sq_"))
    question_id: str = Field(..., description="关联的子问题 ID")
    query: str = Field(..., description="搜索查询字符串")
    language: str = Field("zh-CN", description="查询语言")
    time_range: str | None = Field(None, description="时间范围")


class ResearchPlan(BaseModel):
    """研究计划 — 由 Planner 节点生成"""
    thesis: str = Field(..., description="核心论点")
    questions: list[ResearchQuestion] = Field(default_factory=list, description="子问题列表")
    queries: list[SearchQuery] = Field(default_factory=list, description="搜索查询列表")
    required_perspectives: list[str] = Field(default_factory=list, description="必须覆盖的视角")
    completion_criteria: list[str] = Field(default_factory=list, description="完成标准")


# ═══════════════════════════════════════════
# 搜索结果
# ═══════════════════════════════════════════

class SearchResult(BaseModel):
    """单个搜索结果项"""
    id: str = Field(default_factory=lambda: new_id("sr_"))
    query_id: str = Field("", description="关联的搜索查询 ID")
    url: str = Field(..., description="URL")
    title: str = Field("", description="标题")
    snippet: str = Field("", description="摘要")
    publisher: str | None = Field(None, description="发布者")
    author: str | None = Field(None, description="作者")
    published_at: datetime | None = Field(None, description="发布时间")
    retrieved_at: datetime = Field(default_factory=datetime.now, description="检索时间")


# ═══════════════════════════════════════════
# 来源
# ═══════════════════════════════════════════

class Source(BaseModel):
    """经过处理的来源"""
    id: str = Field(default_factory=lambda: new_id("S"))
    canonical_url: str = Field(..., description="规范化后的 URL")
    title: str = Field("", description="标题")
    publisher: str | None = Field(None, description="发布者")
    author: str | None = Field(None, description="作者")
    published_at: datetime | None = Field(None, description="发布时间")
    retrieved_at: datetime = Field(default_factory=datetime.now, description="检索时间")
    source_type: SourceType = Field("unknown", description="来源类型")
    content_hash: str = Field("", description="内容 SHA256")
    content_location: str = Field("", description="内容存储位置 (路径或对象键)")
    extraction_status: Literal["pending", "success", "failed"] = Field("pending")
    extraction_error: str | None = Field(None, description="抓取错误信息")
    credibility_score: float = Field(0.5, ge=0.0, le=1.0, description="可信度评分")
    credibility_reasons: list[str] = Field(default_factory=list, description="可信度理由")


# ═══════════════════════════════════════════
# 证据和结论
# ═══════════════════════════════════════════

class Evidence(BaseModel):
    """从来源提取的证据片段"""
    source_id: str = Field(..., description="来源 ID")
    quote: str = Field(..., description="原始引用文本")
    location: str | None = Field(None, description="在来源中的位置")
    supports_claim: bool = Field(True, description="是否支持结论")
    notes: str | None = Field(None, description="备注")


class Claim(BaseModel):
    """研究结论 — 由证据支持的观点"""
    id: str = Field(default_factory=lambda: new_id("C"))
    text: str = Field(..., description="结论描述")
    question_id: str = Field("", description="关联的子问题 ID")
    evidence: list[Evidence] = Field(default_factory=list, description="支持证据")
    confidence: float = Field(0.5, ge=0.0, le=1.0, description="置信度")
    status: ClaimStatus = Field("unsupported", description="结论状态")


# ═══════════════════════════════════════════
# 审查
# ═══════════════════════════════════════════

class ReviewIssue(BaseModel):
    """单个审查问题"""
    category: ReviewCategory = Field(...)
    severity: ReviewSeverity = Field(...)
    description: str = Field(..., description="问题描述")
    suggestion: str = Field("", description="修改建议")
    claim_ids: list[str] = Field(default_factory=list, description="关联的结论 ID")
    paragraph_ref: str | None = Field(None, description="在报告中的段落位置")


class ReviewResult(BaseModel):
    """审查结果 — 结构化输出, 不从字符串解析"""
    verdict: Literal["approved", "revise", "human_review"] = Field(...)
    factuality_score: int = Field(..., ge=0, le=100)
    citation_score: int = Field(..., ge=0, le=100)
    coverage_score: int = Field(..., ge=0, le=100)
    structure_score: int = Field(..., ge=0, le=100)
    issues: list[ReviewIssue] = Field(default_factory=list, description="发现的问题列表")
    summary: str = Field("", description="审查总结")


# ═══════════════════════════════════════════
# 报告版本
# ═══════════════════════════════════════════

class ReportVersion(BaseModel):
    """报告的单个版本 — 每次修改产生新版本, 不覆盖"""
    id: str = Field(default_factory=lambda: new_id("R"))
    run_id: str = Field(..., description="关联的运行 ID")
    version: int = Field(1, ge=1, description="版本号")
    markdown: str = Field("", description="报告正文 (Markdown)")
    outline: dict = Field(default_factory=dict, description="报告大纲结构")
    citation_ids: list[str] = Field(default_factory=list, description="引用到的来源 ID 列表")
    created_by_node: str = Field("", description="创建此版本的节点名称")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    based_on_version: str | None = Field(None, description="基于哪个版本修改")


# ═══════════════════════════════════════════
# 人工决策
# ═══════════════════════════════════════════

class HumanDecision(BaseModel):
    """人类的审批决策"""
    action: HumanAction = Field(...)
    feedback: str = Field("", description="人工反馈/修改意见")
    decided_at: datetime = Field(default_factory=datetime.now)


# ═══════════════════════════════════════════
# 节点执行记录
# ═══════════════════════════════════════════

class NodeExecutionRecord(BaseModel):
    """每个节点执行的跟踪记录"""
    node_name: NodeName = Field(...)
    started_at: datetime = Field(default_factory=datetime.now)
    ended_at: datetime | None = Field(None)
    status: Literal["running", "completed", "failed", "skipped"] = Field("running")
    retry_count: int = Field(0)
    model: str = Field("")
    prompt_tokens: int = Field(0)
    completion_tokens: int = Field(0)
    cost_usd: Decimal = Field(Decimal("0"))
    error_type: str | None = Field(None)
    error_message: str | None = Field(None)
    input_summary: str | None = Field(None)
    output_summary: str | None = Field(None)
