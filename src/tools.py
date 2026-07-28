"""工具集 — Agent 可调用的外部工具

当前: 模拟搜索 (PR 2 将替换为真实 SearchProvider)
"""

from __future__ import annotations

from datetime import datetime

from src.config import settings

# ═══════════════════════════════════════════
# 搜索结果模型 (类型提示用, 运行时由 models 提供)
# ═══════════════════════════════════════════


class SearchResult:
    """轻量搜索结果 (正式实现见 models.SearchResult)"""

    def __init__(
        self,
        url: str,
        title: str,
        snippet: str,
        publisher: str | None = None,
        author: str | None = None,
    ):
        self.url = url
        self.title = title
        self.snippet = snippet
        self.publisher = publisher
        self.author = author


# ═══════════════════════════════════════════
# 搜索 (模拟)
# ═══════════════════════════════════════════


def web_search(query: str) -> str:
    """模拟搜索工具

    占位实现: 返回模拟结果文本。
    PR 2 将替换为 SearchProvider 接口 + Tavily/SerpAPI 实现。

    Args:
        query: 搜索查询

    Returns:
        格式化的搜索结果文本
    """
    return (
        f"搜索结果: {query}\n\n"
        f"1. 关于 '{query}' 的相关信息...\n"
        f"2. {query} 的核心数据...\n"
        f"3. {query} 的实践案例分析...\n\n"
        f"[注: 此为模拟结果。生产环境请配置 TAVILY_API_KEY]"
    )


# ═══════════════════════════════════════════
# 来源抓取
# ═══════════════════════════════════════════


def fetch_webpage(url: str, timeout: int = 15) -> dict:
    """抓取网页正文

    当前为占位实现。PR 2 将使用 httpx + trafilatura 实现:
    - 普通 HTML: httpx + trafilatura
    - JS 页面: playwright 后备
    - PDF: pdfminer.six

    Args:
        url: 目标 URL
        timeout: 超时秒数

    Returns:
        {"content": str, "error": str | None}
    """
    return {
        "content": f"[占位抓取: {url}]",
        "error": None,
    }


# ═══════════════════════════════════════════
# 报告保存
# ═══════════════════════════════════════════


def save_report(content: str, topic: str) -> str:
    """将报告保存到配置化的 output/ 目录

    使用 settings.OUTPUT_DIR 而非硬编码的相对路径。

    Args:
        content: 报告正文
        topic: 课题名称 (用于文件名)

    Returns:
        保存路径字符串
    """
    output_dir = settings.OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    # 生成安全的文件名
    safe_topic = "".join(c if c.isalnum() or c in "-_" else "_" for c in topic[:30])
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{safe_topic}_{timestamp}.md"
    filepath = output_dir / filename

    filepath.write_text(content, encoding="utf-8")
    return str(filepath)
