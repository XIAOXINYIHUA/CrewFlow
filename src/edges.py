"""条件路由逻辑 - 决定图中下一步走哪个节点"""

from .state import CrewState

MAX_ITERATIONS = 3  # 最大审查迭代次数


def should_review(state: CrewState) -> str:
    """写完初稿后：进入审查 or 人工审查"""
    if state.get("step") == "writer":
        return "reviewer"
    return "reviewer"


def should_revise_or_end(state: CrewState) -> str:
    """审查后：修改 or 结束"""
    # 已通过审查
    if state.get("step") == "approved":
        return "end"

    # 超过最大迭代次数，强制结束
    if state.get("iteration", 0) >= MAX_ITERATIONS:
        print(f"⚠️ 已达最大迭代次数 ({MAX_ITERATIONS})，使用当前版本")
        return "end"

    # 需要修改，回到 Writer
    return "writer"
