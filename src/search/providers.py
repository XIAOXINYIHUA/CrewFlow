"""Tavily 搜索提供商实现"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from src.config import settings
from src.search import (
    SearchResultItem,
    SearchTimeoutError,
    SearchRateLimitError,
    SearchAuthError,
    SearchNoResultsError,
    SearchProviderError,
    classify_search_error,
)


class TavilySearchProvider:
    """Tavily API 搜索实现

    需要设置 TAVILY_API_KEY 环境变量。
    API 文档: https://docs.tavily.com/
    """

    BASE_URL = "https://api.tavily.com"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.TAVILY_API_KEY
        if not self.api_key:
            raise SearchAuthError(
                "TAVILY_API_KEY 未设置。请在 .env 中配置或设置环境变量。",
                provider="tavily",
            )

    async def search(
        self,
        query: str,
        *,
        max_results: int = 10,
        time_range: str | None = None,
        domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> list[SearchResultItem]:
        """执行 Tavily 搜索"""
        import httpx

        if not query.strip():
            return []

        payload: dict[str, Any] = {
            "api_key": self.api_key,
            "query": query,
            "max_results": min(max_results, 20),
            "include_answer": False,
            "include_raw_content": False,
            "include_domains": domains or [],
            "exclude_domains": exclude_domains or [],
        }

        if time_range:
            payload["time_range"] = time_range  # d, w, m, y

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.BASE_URL}/search",
                    json=payload,
                )

                if response.status_code == 429:
                    raise SearchRateLimitError(
                        "Tavily 限流, 请稍后重试",
                        provider="tavily",
                        query=query,
                    )
                if response.status_code == 401:
                    raise SearchAuthError(
                        "Tavily API Key 无效",
                        provider="tavily",
                        query=query,
                    )
                if response.status_code != 200:
                    raise SearchProviderError(
                        f"Tavily 返回状态码 {response.status_code}: {response.text}",
                        provider="tavily",
                        query=query,
                    )

                data = response.json()
                results = data.get("results", [])

                if not results:
                    return []

                return [
                    SearchResultItem(
                        query=query,
                        url=item.get("url", ""),
                        title=item.get("title", ""),
                        snippet=item.get("content", ""),
                        publisher=item.get("domain", None),
                        retrieved_at=datetime.now(),
                    )
                    for item in results
                    if item.get("url")
                ]

        except httpx.TimeoutException:
            raise SearchTimeoutError(
                f"Tavily 搜索超时: {query[:50]}",
                provider="tavily",
                query=query,
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise SearchRateLimitError(
                    "Tavily 限流", provider="tavily", query=query
                )
            raise SearchProviderError(
                f"Tavily HTTP 错误: {e}", provider="tavily", query=query
            )
        except (httpx.HTTPError, httpx.ConnectError) as e:
            raise SearchProviderError(
                f"Tavily 连接错误: {e}", provider="tavily", query=query
            )
        except Exception as e:
            raise classify_search_error(e, query=query)
