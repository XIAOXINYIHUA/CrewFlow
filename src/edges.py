"""条件路由逻辑 — 决定图中下一步走哪个节点

关键修复:
- 不再让模型自由选择路由目标
- 所有路由规则由代码确定
- 清晰的状态机: reviewed → revision_router → writer/publisher/human_review
"""

from __future__ import annotations

from src.config import settings
from src.models import ReviewResult
from src.state import CrewState


def should_revise_or_end(state: CrewState) -> str:
    """审查后的路由决策

    纯代码逻辑, 不依赖模型输出:
    - critical 事实问题 → 回到 writer 修改
    - approved + 不需要人工审批 → 到 publisher 发布
    - approved + 需要人工审批 → 到 human_review
    - 有 critical 问题或 iteration 超限 → 到 human_review (强制人工)
    - 其他 → 回到 writer 修改
    """
    review: ReviewResult | None = state.get("review")
    iteration: int = state.get("iteration", 0)

    if not review:
        # 没有审查结果 → 人工介入
        return "human_review"

    # 检查是否有 critical 事实问题
    has_critical_fact = (
        any(
            i.severity == "critical" and i.category in ("factuality", "citation")
            for i in review.issues
        )
        if review.issues
        else False
    )

    # 已达最大迭代次数
    maxed_out = iteration >= settings.MAX_ITERATIONS

    if has_critical_fact and not maxed_out:
        # 严重事实问题, 但还能修改 → 回 writer
        print(f"  [Router] 严重事实问题, 退回修改 (第{iteration}轮)")
        return "writer"

    if review.verdict == "approved" or (review.factuality_score >= 70 and not has_critical_fact):
        if state.get("require_human_approval", True):
            print("  [Router] 审查通过, 进入人工审批")
            return "human_review"
        else:
            print("  [Router] 审查通过, 准备发布")
            return "publisher"

    if maxed_out:
        # 超限 → 强制人工审批
        print(f"  [Router] 已达最大迭代次数 ({settings.MAX_ITERATIONS}), 强制人工审批")
        return "human_review"

    # 默认: 退回修改
    print(f"  [Router] 需要修改 (第{iteration}轮)")
    return "writer"


def after_human_review(state: CrewState) -> str:
    """人工审批后的路由

    人工选择了 approve / revise / cancel:
    - approve → publisher 发布
    - revise → writer 修改
    - cancel → end
    """
    decision = state.get("human_decision")
    if not decision:
        return "human_review"

    action = decision.action
    print(f"  [Router] 人工决策: {action}")

    if action == "approve":
        return "publisher"
    elif action == "cancel":
        return "end"
    else:
        return "writer"
