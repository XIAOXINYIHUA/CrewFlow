"""全局状态定义 - CrewFlow 中所有 Agent 共享的数据结构"""

from typing import TypedDict, List, Optional
from langgraph.graph import MessagesState


class CrewState(MessagesState):
    """研究团队协作的全局状态"""
    topic: str                          # 研究课题
    search_results: Optional[str]       # Researcher 搜索结果
    analysis: Optional[str]             # Analyst 分析报告
    draft: Optional[str]                # Writer 初稿
    review_feedback: Optional[str]      # Reviewer 审查意见
    final_report: Optional[str]         # 最终报告
    step: str                           # 当前步骤名称
    iteration: int                      # 审查迭代次数
    human_feedback: Optional[str]       # 人工反馈
