"""CrewFlow 单元测试 — 路由逻辑 (edges.py)"""

from src.edges import after_human_review, should_revise_or_end
from src.models import (
    HumanDecision,
    ReviewIssue,
    ReviewResult,
)
from src.state import CrewState, create_initial_state


def _make_state(**overrides) -> CrewState:
    """创建测试用状态的辅助函数"""
    base = create_initial_state(
        topic="test topic",
        run_id="run_test",
        thread_id="thread_test",
    )
    base.update(overrides)
    return base  # type: ignore


class TestShouldReviseOrEnd:
    """审查后路由测试"""

    def test_approved_no_human(self):
        """审查通过 + 不需要人工审批 → publisher"""
        state = _make_state(
            require_human_approval=False,
            review=ReviewResult(
                verdict="approved",
                factuality_score=90,
                citation_score=85,
                coverage_score=80,
                structure_score=85,
            ),
            iteration=1,
        )
        assert should_revise_or_end(state) == "publisher"

    def test_approved_with_human(self):
        """审查通过 + 需要人工审批 → human_review"""
        state = _make_state(
            require_human_approval=True,
            review=ReviewResult(
                verdict="approved",
                factuality_score=85,
                citation_score=80,
                coverage_score=75,
                structure_score=88,
            ),
            iteration=1,
        )
        assert should_revise_or_end(state) == "human_review"

    def test_revise_below_max(self):
        """需要修改, 未达最大次数 → writer"""
        state = _make_state(
            require_human_approval=True,
            review=ReviewResult(
                verdict="revise",
                factuality_score=60,
                citation_score=55,
                coverage_score=70,
                structure_score=65,
                issues=[
                    ReviewIssue(
                        category="citation",
                        severity="high",
                        description="缺少引用",
                        suggestion="补充引用",
                    ),
                ],
            ),
            iteration=1,
        )
        assert should_revise_or_end(state) == "writer"

    def test_critical_fact_below_max(self):
        """严重事实问题, 未达最大次数 → writer"""
        state = _make_state(
            require_human_approval=True,
            review=ReviewResult(
                verdict="revise",
                factuality_score=30,
                citation_score=50,
                coverage_score=60,
                structure_score=70,
                issues=[
                    ReviewIssue(
                        category="factuality",
                        severity="critical",
                        description="数据错误",
                        suggestion="修正",
                    ),
                ],
            ),
            iteration=1,
        )
        assert should_revise_or_end(state) == "writer"

    def test_max_iterations_reached(self):
        """已达最大迭代次数 → human_review"""
        state = _make_state(
            require_human_approval=True,
            review=ReviewResult(
                verdict="revise",
                factuality_score=55,
                citation_score=50,
                coverage_score=60,
                structure_score=65,
            ),
            iteration=3,  # 等于 MAX_ITERATIONS
        )
        assert should_revise_or_end(state) == "human_review"

    def test_no_review_result(self):
        """没有审查结果 → human_review"""
        state = _make_state(
            review=None,
            iteration=0,
        )
        assert should_revise_or_end(state) == "human_review"

    def test_high_score_auto_approve(self):
        """高评分即使 verdict 不是 approved 也通过"""
        state = _make_state(
            require_human_approval=False,
            review=ReviewResult(
                verdict="revise",
                factuality_score=85,
                citation_score=80,
                coverage_score=75,
                structure_score=90,
            ),
            iteration=1,
        )
        # factuality_score=85 >= 70, no critical issues
        assert should_revise_or_end(state) == "publisher"


class TestAfterHumanReview:
    """人工审批后路由测试"""

    def test_approve(self):
        """人工批准 → publisher"""
        state = _make_state(
            human_decision=HumanDecision(action="approve"),
        )
        assert after_human_review(state) == "publisher"

    def test_revise(self):
        """人工退回修改 → writer"""
        state = _make_state(
            human_decision=HumanDecision(
                action="revise",
                feedback="请补充更多数据",
            ),
        )
        assert after_human_review(state) == "writer"

    def test_cancel(self):
        """人工取消 → end"""
        state = _make_state(
            human_decision=HumanDecision(action="cancel"),
        )
        assert after_human_review(state) == "end"

    def test_no_decision(self):
        """没有决策 → 继续等待"""
        state = _make_state(human_decision=None)
        assert after_human_review(state) == "human_review"


class TestEdgeCases:
    """边界条件和错误路径测试"""

    def test_review_citation_critical_maxed(self):
        """严重引用问题 + 已达最大次数 → human_review"""
        state = _make_state(
            require_human_approval=True,
            review=ReviewResult(
                verdict="revise",
                factuality_score=50,
                citation_score=30,
                coverage_score=60,
                structure_score=65,
                issues=[
                    ReviewIssue(
                        category="citation",
                        severity="critical",
                        description="所有关键数据缺少引用",
                        suggestion="补充引用",
                    ),
                ],
            ),
            iteration=3,
        )
        assert should_revise_or_end(state) == "human_review"

    def test_empty_draft_but_approved(self):
        """空草稿但 verdict 为 approved (边缘情况)"""
        state = _make_state(
            require_human_approval=False,
            review=ReviewResult(
                verdict="approved",
                factuality_score=90,
                citation_score=90,
                coverage_score=90,
                structure_score=90,
            ),
            iteration=1,
        )
        # 路由不检查草稿内容 (由 reviewer 保证)
        assert should_revise_or_end(state) == "publisher"
