"""工具集 - Agent 可调用的外部工具"""

import os
from datetime import datetime
from pathlib import Path


def web_search(query: str) -> str:
    """模拟搜索工具（实际使用时接入 Tavily / SerpAPI）

    生产环境中替换为：
    from langchain_community.tools.tavily_search import TavilySearchResults
    """
    return (
        f"搜索查询: {query}\n"
        f"（此为模拟结果，生产环境请接入 Tavily API）\n\n"
        f"1. 关于 '{query}' 的最新研究进展...\n"
        f"2. {query} 的核心技术原理...\n"
        f"3. {query} 在实际应用中的案例分析..."
    )


def save_report(content: str, topic: str) -> str:
    """将最终报告保存到 output/ 目录"""
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    # 生成文件名
    safe_topic = "".join(c if c.isalnum() or c in "-_" else "_" for c in topic[:30])
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{safe_topic}_{timestamp}.md"
    filepath = output_dir / filename

    filepath.write_text(content, encoding="utf-8")
    return f"报告已保存至: {filepath}"
