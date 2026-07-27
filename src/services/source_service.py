"""来源处理服务 — URL 规范化、正文抓取、内容提取、去重、可信度评估"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from src.config import settings
from src.models import Source, SourceType, SearchResult


# ═══════════════════════════════════════════
# URL 规范化
# ═══════════════════════════════════════════

def normalize_url(url: str) -> str:
    """规范化 URL

    - 统一小写域名
    - 移除默认端口
    - 移除 #fragment
    - 统一 https
    - 移除末尾的 /
    - 移除 utm_ 参数
    """
    try:
        parsed = urlparse(url.strip())
        if not parsed.scheme:
            url = "https://" + url
            parsed = urlparse(url)

        # 只允许 http/https
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"不支持的协议: {parsed.scheme}")

        # 移除 fragment
        clean = parsed._replace(fragment="")

        # 统一小写域名
        clean = clean._replace(netloc=parsed.netloc.lower())

        # 移除默认端口
        hostname = clean.hostname or ""
        if clean.port == 443 and clean.scheme == "https":
            clean = clean._replace(netloc=hostname)
        elif clean.port == 80 and clean.scheme == "http":
            clean = clean._replace(netloc=hostname)

        # 移除 utm_ 参数
        query = clean.query
        if query:
            params = [p for p in query.split("&") if not p.startswith("utm_")]
            clean = clean._replace(query="&".join(params))

        result = clean.geturl().rstrip("/")
        return result
    except Exception as e:
        raise ValueError(f"URL 规范化失败: {url[:100]}, {e}")


def url_to_source_type(url: str) -> SourceType:
    """根据 URL 推断来源类型"""
    domain = urlparse(url).hostname or ""

    # .gov / .edu 域名
    if domain.endswith(".gov") or ".gov." in domain:
        return "official"
    if domain.endswith(".edu") or ".edu." in domain:
        return "paper"

    # 学术/论文
    if any(d in domain for d in ["arxiv", "scholar", "doi.", "semanticscholar", "pubmed"]):
        return "paper"

    # 标准组织
    if any(d in domain for d in ["iso.org", "ieee", "w3c", "rfc"]):
        return "standard"

    # 论坛/社区 (排在新闻/公司前, 避免误判)
    if any(d in domain for d in ["reddit", "stackoverflow", "github", "medium", "zhihu", "discourse", "stackexchange"]):
        return "forum"

    # 新闻媒体
    if any(d in domain for d in [
        "news", "reuters", "bloomberg", "bbc", "cnn", "nytimes",
        "wsj", "ft.com", "economist", "ap.org", "xinhua",
    ]):
        return "news"

    # 公司/产品
    if any(d in domain for d in [".com", ".cn", ".io", ".co", ".org"]):
        return "company"

    return "unknown"


# ═══════════════════════════════════════════
# SSRF 防护 — URL 安全检查
# ═══════════════════════════════════════════

PRIVATE_IP_PATTERNS = [
    re.compile(r"^127\.\d+\.\d+\.\d+$"),
    re.compile(r"^10\.\d+\.\d+\.\d+$"),
    re.compile(r"^172\.(1[6-9]|2\d|3[01])\.\d+\.\d+$"),
    re.compile(r"^192\.168\.\d+\.\d+$"),
    re.compile(r"^0\.0\.0\.0$"),
    re.compile(r"^169\.254\.\d+\.\d+$"),
    re.compile(r"^\[::1\]$"),
    re.compile(r"^\[fc00:\|fe80:\]"),
]


def is_safe_url(url: str) -> tuple[bool, str]:
    """SSRF 防护: 检查 URL 是否安全可抓取

    Returns:
        (is_safe, reason)
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "URL 解析失败"

    # 只允许 http/https
    if parsed.scheme not in ("http", "https"):
        return False, f"不支持的协议: {parsed.scheme}"

    hostname = parsed.hostname or ""

    # 禁止 localhost
    if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return False, "禁止访问 localhost"

    # 禁止内部域名
    if hostname.endswith(".local") or hostname.endswith(".internal"):
        return False, f"禁止访问内部域名: {hostname}"

    # 禁止私有 IP 地址
    for pattern in PRIVATE_IP_PATTERNS:
        if pattern.match(hostname):
            return False, f"禁止访问私有 IP: {hostname}"

    # 禁止云服务元数据
    cloud_metadata = [
        "169.254.169.254",  # AWS/GCP/Azure
        "metadata.google.internal",
        "100.100.100.200",  # Alibaba Cloud
    ]
    if hostname in cloud_metadata or any(d in hostname for d in cloud_metadata):
        return False, "禁止访问云服务元数据地址"

    return True, ""


# ═══════════════════════════════════════════
# 网页抓取
# ═══════════════════════════════════════════

def fetch_webpage(url: str, timeout: int = 15) -> dict:
    """抓取网页正文内容

    使用 httpx 获取 + trafilatura 提取正文。
    不依赖无头浏览器 (JS 渲染作为后备)。

    Args:
        url: 目标 URL
        timeout: 超时秒数

    Returns:
        {"content": str, "title": str, "error": str | None}
    """
    import httpx
    import trafilatura

    # SSRF 检查
    safe, reason = is_safe_url(url)
    if not safe:
        return {"content": "", "title": "", "error": f"SSRF 拦截: {reason}"}

    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            max_redirects=5,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            },
        ) as client:
            response = client.get(url)

            if response.status_code != 200:
                return {
                    "content": "",
                    "title": "",
                    "error": f"HTTP {response.status_code}",
                }

            # 限制响应大小 (5MB)
            content = response.content[:5_242_880]
            html = content.decode("utf-8", errors="replace")

            # 使用 trafilatura 提取正文
            text = trafilatura.extract(
                html,
                output_format="txt",
                include_comments=False,
                include_tables=True,
                no_fail=True,
            )

            # 提取标题
            title = ""
            title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
            if title_match:
                title = title_match.group(1).strip()

            return {
                "content": text or "[无法提取正文]",
                "title": title or "",
                "error": None,
            }

    except httpx.TimeoutException:
        return {"content": "", "title": "", "error": "抓取超时"}
    except httpx.ConnectError:
        return {"content": "", "title": "", "error": "连接失败"}
    except Exception as e:
        return {"content": "", "title": "", "error": f"抓取错误: {type(e).__name__}: {e}"}


# ═══════════════════════════════════════════
# 内容哈希
# ═══════════════════════════════════════════

def content_hash(text: str) -> str:
    """计算内容 SHA256 哈希"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ═══════════════════════════════════════════
# 来源去重
# ═══════════════════════════════════════════

def deduplicate_sources(
    existing: list[Source],
    candidates: list[SearchResult],
) -> list[Source]:
    """对新候选来源去重, 返回新增的来源

    去重规则:
    1. 规范化 URL 去重 (主要)
    2. 标题相似度去重 (后备)
    3. 内容哈希去重 (当正文可用时)

    Args:
        existing: 已有来源
        candidates: 新的搜索结果

    Returns:
        去重后新增的 Source 列表
    """
    # 建立已有 URL 集合
    existing_urls = set()
    existing_titles_lower = set()
    for s in existing:
        try:
            existing_urls.add(normalize_url(s.canonical_url))
        except ValueError:
            existing_urls.add(s.canonical_url)
        existing_titles_lower.add(s.title.lower().strip())

    new_sources: list[Source] = []
    seen_urls: set[str] = set()

    for result in candidates:
        if not result.url:
            continue

        try:
            canonical = normalize_url(result.url)
        except ValueError:
            canonical = result.url

        # URL 去重
        if canonical in existing_urls or canonical in seen_urls:
            continue

        # 标题去重 (低阈值, 防同一个文章多个 URL)
        title_lower = result.title.lower().strip()
        if title_lower and title_lower in existing_titles_lower:
            continue

        seen_urls.add(canonical)

        source = Source(
            canonical_url=canonical,
            title=result.title,
            publisher=result.publisher,
            author=result.author,
            published_at=result.published_at,
            retrieved_at=datetime.now(),
            source_type=url_to_source_type(canonical),
            credibility_score=0.5,  # 初始值, 后续根据内容质量调整
            credibility_reasons=["默认初始评分"],
            extraction_status="pending",
        )
        new_sources.append(source)

    return new_sources


# ═══════════════════════════════════════════
# 可信度评估
# ═══════════════════════════════════════════

def evaluate_credibility(source: Source, content: str) -> tuple[float, list[str]]:
    """基于内容和元数据评估来源可信度

    返回 (score 0-1, reasons)
    """
    reasons: list[str] = []
    score = 0.5  # 基础分

    # 来源类型加分
    type_boost = {
        "official": 0.3,
        "paper": 0.25,
        "standard": 0.3,
        "news": 0.1,
        "company": 0.0,
        "blog": -0.1,
        "forum": -0.2,
        "unknown": 0.0,
    }
    boost = type_boost.get(source.source_type, 0.0)
    score += boost
    if boost > 0:
        reasons.append(f"来源类型 {source.source_type} 加分 {boost}")

    # 有作者加分
    if source.author:
        score += 0.05
        reasons.append("包含作者信息")

    # 有发布时间加分
    if source.published_at:
        score += 0.05
        reasons.append("包含发布时间")

    # 正文质量评估
    if content:
        word_count = len(content.split())
        if word_count > 500:
            score += 0.1
            reasons.append("内容充实 (>500词)")
        elif word_count < 50:
            score -= 0.1
            reasons.append("内容过短 (<50词)")
    else:
        score -= 0.2
        reasons.append("未能获取正文")

    return max(0.0, min(1.0, score)), reasons
