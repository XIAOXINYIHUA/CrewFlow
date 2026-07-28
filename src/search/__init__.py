"""搜索提供商接口 — 所有搜索后端实现同一接口"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import uuid4


def _new_id() -> str:
    return uuid4().hex[:12]


@dataclass
class SearchResultItem:
    """单个搜索结果的标准返回格式"""

    id: str = field(default_factory=_new_id)
    query: str = ""
    url: str = ""
    title: str = ""
    snippet: str = ""
    publisher: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    retrieved_at: datetime = field(default_factory=datetime.now)
    source_type: str = "unknown"


@runtime_checkable
class SearchProvider(Protocol):
    """搜索提供商的协议接口

    所有搜索后端 (Tavily, Brave, Serper, 内部搜索) 实现此接口。
    """

    async def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        time_range: str | None = None,
        domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> list[SearchResultItem]:
        """执行搜索

        Args:
            query: 搜索查询
            max_results: 最大结果数
            time_range: 时间范围 (如 "d", "w", "m", "y", 或具体日期范围)
            domains: 限制搜索的域名列表
            exclude_domains: 排除的域名列表

        Returns:
            搜索结果列表

        Raises:
            SearchTimeoutError: 超时
            SearchRateLimitError: 限流
            SearchAuthError: 认证失败
            SearchNoResultsError: 无结果
            SearchProviderError: 其他提供商错误
        """
        ...


# ═══════════════════════════════════════════
# 自定义异常
# ═══════════════════════════════════════════


class SearchError(Exception):
    """搜索错误基类"""

    def __init__(self, message: str, provider: str = "unknown", query: str = ""):
        self.provider = provider
        self.query = query
        super().__init__(message)


class SearchTimeoutError(SearchError):
    """搜索超时"""

    pass


class SearchRateLimitError(SearchError):
    """API 限流"""

    pass


class SearchAuthError(SearchError):
    """API 认证失败"""

    pass


class SearchNoResultsError(SearchError):
    """搜索无结果"""

    pass


class SearchProviderError(SearchError):
    """提供商其他错误"""

    pass


# ═══════════════════════════════════════════
# 分类函数
# ═══════════════════════════════════════════


def classify_search_error(e: Exception, query: str = "") -> SearchError:
    """将原始异常分类为 SearchError

    确保搜索失败不会导致整个任务崩溃。

    Args:
        e: 原始异常
        query: 搜索查询 (用于错误追踪)

    Returns:
        分类后的 SearchError
    """
    msg = str(e).lower()

    if "timeout" in msg or "timed out" in msg:
        return SearchTimeoutError(str(e), query=query)
    if "rate limit" in msg or "429" in msg or "too many" in msg:
        return SearchRateLimitError(str(e), query=query)
    if "unauthorized" in msg or "401" in msg or "403" in msg or "api key" in msg:
        return SearchAuthError(str(e), query=query)
    if "no result" in msg or "not found" in msg:
        return SearchNoResultsError(str(e), query=query)

    return SearchProviderError(str(e), query=query)
