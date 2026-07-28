"""CrewFlow 单元测试 — 模型校验"""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.models import (
    Claim,
    Evidence,
    HumanDecision,
    ReportVersion,
    ResearchPlan,
    ResearchQuestion,
    ResearchRequirements,
    ReviewIssue,
    ReviewResult,
    SearchQuery,
)


class TestResearchRequirements:
    """ResearchRequirements 输入校验测试"""

    def test_valid_requirements(self):
        """正常输入应通过校验"""
        req = ResearchRequirements(
            topic="AI Agent 发展趋势",
            purpose="技术调研",
            audience="工程师",
            target_words=3000,
            max_iterations=5,
        )
        assert req.topic == "AI Agent 发展趋势"
        assert req.target_words == 3000

    def test_topic_empty(self):
        """主题不能为空"""
        with pytest.raises(ValidationError):
            ResearchRequirements(topic="")

    def test_topic_too_long(self):
        """主题过长应拒绝"""
        with pytest.raises(ValidationError):
            ResearchRequirements(topic="x" * 501)

    def test_target_words_out_of_range(self):
        """超限字数应拒绝"""
        with pytest.raises(ValidationError):
            ResearchRequirements(topic="test", target_words=100)

        with pytest.raises(ValidationError):
            ResearchRequirements(topic="test", target_words=25000)

    def test_date_range_valid(self):
        """日期范围不能颠倒"""
        with pytest.raises(ValidationError):
            ResearchRequirements(
                topic="test",
                date_from=date(2025, 6, 1),
                date_to=date(2024, 1, 1),
            )

    def test_date_range_valid_order(self):
        """正确的日期顺序应通过"""
        req = ResearchRequirements(
            topic="test",
            date_from=date(2024, 1, 1),
            date_to=date(2025, 6, 1),
        )
        assert req.date_from == date(2024, 1, 1)
        assert req.date_to == date(2025, 6, 1)

    def test_domain_normalization(self):
        """域名应被规范化"""
        req = ResearchRequirements(
            topic="test",
            preferred_domains=[
                "https://www.example.com/path",
                "HTTP://GOV.CN/",
            ],
        )
        assert "www.example.com" in req.preferred_domains
        assert "gov.cn" in req.preferred_domains

    def test_negative_budget(self):
        """负数预算应拒绝"""
        with pytest.raises(ValidationError):
            ResearchRequirements(topic="test", max_cost_usd=Decimal("-1"))

    def test_max_iterations_limit(self):
        """超限迭代次数应拒绝"""
        with pytest.raises(ValidationError):
            ResearchRequirements(topic="test", max_iterations=20)

    def test_max_sources_limit(self):
        """超限来源数应拒绝"""
        with pytest.raises(ValidationError):
            ResearchRequirements(topic="test", max_sources=200)


class TestReviewResult:
    """ReviewResult 结构化输出测试"""

    def test_valid_approved(self):
        """正常的批准结果"""
        result = ReviewResult(
            verdict="approved",
            factuality_score=85,
            citation_score=80,
            coverage_score=75,
            structure_score=90,
            issues=[],
        )
        assert result.verdict == "approved"

    def test_valid_with_issues(self):
        """带问题的审查结果"""
        result = ReviewResult(
            verdict="revise",
            factuality_score=60,
            citation_score=50,
            coverage_score=70,
            structure_score=65,
            issues=[
                ReviewIssue(
                    category="citation",
                    severity="high",
                    description="缺少官方统计引用",
                    suggestion="补充国家统计局数据",
                ),
                ReviewIssue(
                    category="factuality",
                    severity="critical",
                    description="市场规模数据与来源不一致",
                    suggestion="核对原始数据口径",
                    claim_ids=["C001"],
                ),
            ],
        )
        assert len(result.issues) == 2
        assert result.issues[0].severity == "high"
        assert result.issues[1].category == "factuality"

    def test_human_review_verdict(self):
        """需人工审查的结果"""
        result = ReviewResult(
            verdict="human_review",
            factuality_score=40,
            citation_score=45,
            coverage_score=50,
            structure_score=60,
            issues=[
                ReviewIssue(
                    category="factuality",
                    severity="critical",
                    description="不确定数据准确性",
                    suggestion="请人工验证",
                ),
            ],
        )
        assert result.verdict == "human_review"

    def test_invalid_verdict(self):
        """非法的 verdict 应拒绝"""
        with pytest.raises(ValidationError):
            ReviewResult(
                verdict="unknown",  # type: ignore
                factuality_score=0,
                citation_score=0,
                coverage_score=0,
                structure_score=0,
            )

    def test_score_bounds(self):
        """评分应在 0-100 范围内"""
        with pytest.raises(ValidationError):
            ReviewResult(
                verdict="approved",
                factuality_score=-1,
                citation_score=0,
                coverage_score=0,
                structure_score=0,
            )

        with pytest.raises(ValidationError):
            ReviewResult(
                verdict="approved",
                factuality_score=0,
                citation_score=0,
                coverage_score=101,
                structure_score=0,
            )


class TestClaim:
    """Claim 模型测试"""

    def test_valid_claim(self):
        """正常的结论"""
        claim = Claim(
            text="AI Agent 能提升开发效率",
            evidence=[
                Evidence(
                    source_id="S001",
                    quote="使用 AI Agent 的开发团队效率提升 30%",
                ),
            ],
            confidence=0.8,
            status="supported",
        )
        assert claim.status == "supported"
        assert len(claim.evidence) == 1

    def test_claim_status_valid(self):
        """非法的 status 应拒绝"""
        with pytest.raises(ValidationError):
            Claim(
                text="test",
                status="unknown",  # type: ignore
            )


class TestHumanDecision:
    """HumanDecision 模型测试"""

    def test_approve_decision(self):
        """批准决策"""
        decision = HumanDecision(action="approve", feedback="报告质量合格")
        assert decision.action == "approve"

    def test_revise_decision(self):
        """修改决策"""
        decision = HumanDecision(action="revise", feedback="请补充更多数据")
        assert decision.action == "revise"

    def test_cancel_decision(self):
        """取消决策"""
        decision = HumanDecision(action="cancel")
        assert decision.action == "cancel"

    def test_invalid_action(self):
        """非法动作应拒绝"""
        with pytest.raises(ValidationError):
            HumanDecision(action="delete")  # type: ignore


class TestReportVersion:
    """ReportVersion 模型测试"""

    def test_version_auto_increment(self):
        """版本号应递增"""
        v1 = ReportVersion(run_id="run_001", version=1, markdown="# Report")
        v2 = ReportVersion(run_id="run_001", version=2, markdown="# Report v2")
        assert v2.version > v1.version
        assert v2.based_on_version is None

    def test_version_link(self):
        """版本应可追溯来源"""
        v2 = ReportVersion(
            run_id="run_001",
            version=2,
            markdown="# Report",
            based_on_version="R_abc123",
        )
        assert v2.based_on_version == "R_abc123"

    def test_citation_ids(self):
        """引用 ID 列表"""
        v = ReportVersion(
            run_id="run_001",
            version=1,
            markdown="# Report",
            citation_ids=["S001", "S002", "S003"],
        )
        assert len(v.citation_ids) == 3


class TestResearchPlan:
    """ResearchPlan 模型测试"""

    def test_valid_plan(self):
        """正常的研究计划"""
        plan = ResearchPlan(
            thesis="AI Agent 将改变软件开发方式",
            questions=[
                ResearchQuestion(
                    question="AI Agent 目前的能力边界",
                    importance=8,
                ),
                ResearchQuestion(
                    question="采用 AI Agent 的风险",
                    importance=7,
                ),
            ],
            queries=[
                SearchQuery(
                    question_id="q_001",
                    query="AI Agent capabilities 2025",
                    language="en",
                ),
            ],
            required_perspectives=["技术", "经济", "安全"],
            completion_criteria=["至少 5 个独立来源"],
        )
        assert len(plan.questions) == 2
        assert len(plan.queries) == 1
        assert "技术" in plan.required_perspectives
