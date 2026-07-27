"""来源处理服务测试 — URL 规范化、SSRF、去重、可信度评估"""

import pytest

from src.models import Source, SearchResult
from src.services.source_service import (
    normalize_url,
    is_safe_url,
    content_hash,
    deduplicate_sources,
    url_to_source_type,
    evaluate_credibility,
)


class TestNormalizeURL:
    """URL 规范化测试"""

    def test_basic_normalization(self):
        """基本规范化"""
        assert normalize_url("https://Example.com/Path") == "https://example.com/Path"

    def test_strip_fragment(self):
        """移除 #fragment"""
        assert normalize_url("https://example.com/page#section") == "https://example.com/page"

    def test_strip_trailing_slash(self):
        """移除末尾 /"""
        assert normalize_url("https://example.com/") == "https://example.com"

    def test_strip_utm_params(self):
        """移除 utm_ 参数"""
        url = "https://example.com/page?utm_source=twitter&id=123"
        result = normalize_url(url)
        assert "utm_source" not in result
        assert "id=123" in result

    def test_default_scheme(self):
        """无协议时自动添加 https"""
        assert normalize_url("example.com") == "https://example.com"

    def test_invalid_scheme(self):
        """非 http/https 应报错"""
        with pytest.raises(ValueError):
            normalize_url("ftp://example.com")

    def test_https_port_removal(self):
        """移除默认 443 端口"""
        assert normalize_url("https://example.com:443/path") == "https://example.com/path"

    def test_keep_custom_port(self):
        """保留非默认端口"""
        assert normalize_url("https://example.com:8080/path") == "https://example.com:8080/path"


class TestSSRFProtection:
    """SSRF 防护测试"""

    def test_localhost_blocked(self):
        """禁止 localhost"""
        safe, reason = is_safe_url("http://localhost:8080/")
        assert not safe
        assert "localhost" in reason

    def test_127_0_0_1_blocked(self):
        """禁止 127.0.0.1"""
        safe, _ = is_safe_url("http://127.0.0.1/")
        assert not safe

    def test_cloud_metadata_blocked(self):
        """禁止云服务元数据地址"""
        safe, _ = is_safe_url("http://169.254.169.254/latest/meta-data/")
        assert not safe

        safe, _ = is_safe_url("http://metadata.google.internal/")
        assert not safe

    def test_private_ip_blocked(self):
        """禁止私有 IP"""
        safe, _ = is_safe_url("http://10.0.0.1/")
        assert not safe

        safe, _ = is_safe_url("http://192.168.1.1/")
        assert not safe

    def test_normal_url_allowed(self):
        """正常 URL 应放行"""
        safe, reason = is_safe_url("https://www.example.com/article")
        assert safe
        assert reason == ""

    def test_ftp_blocked(self):
        """非 http/https 应拒绝"""
        safe, _ = is_safe_url("ftp://example.com/")
        assert not safe


class TestSourceTypeDetection:
    """来源类型检测测试"""

    def test_gov_domain(self):
        assert url_to_source_type("https://www.gov.cn/policy") == "official"

    def test_edu_domain(self):
        assert url_to_source_type("https://mit.edu/research") == "paper"

    def test_arxiv_domain(self):
        assert url_to_source_type("https://arxiv.org/abs/2301") == "paper"

    def test_news_domain(self):
        assert url_to_source_type("https://reuters.com/article") == "news"
        assert url_to_source_type("https://bbc.com/news") == "news"

    def test_forum_domain(self):
        assert url_to_source_type("https://github.com/repo") == "forum"
        assert url_to_source_type("https://reddit.com/r/python") == "forum"

    def test_unknown_domain(self):
        assert url_to_source_type("https://some-random-blog.example/article") == "unknown"


class TestContentHash:
    """内容哈希测试"""

    def test_consistent_hash(self):
        """相同内容应产生相同哈希"""
        h1 = content_hash("Hello World")
        h2 = content_hash("Hello World")
        assert h1 == h2

    def test_different_content(self):
        """不同内容应产生不同哈希"""
        h1 = content_hash("Hello World")
        h2 = content_hash("Hello world")  # 大小写不同
        assert h1 != h2

    def test_empty_string(self):
        """空字符串应产生确定的哈希"""
        h = content_hash("")
        assert isinstance(h, str)
        assert len(h) == 16


class TestDeduplicateSources:
    """来源去重测试"""

    def test_empty_existing(self):
        """无已有来源时, 全部为新来源"""
        results = [
            SearchResult(url="https://example.com/1", title="Title 1", snippet="Snip 1"),
            SearchResult(url="https://example.com/2", title="Title 2", snippet="Snip 2"),
        ]
        sources = deduplicate_sources([], results)
        assert len(sources) == 2

    def test_duplicate_url(self):
        """相同 URL 应去重"""
        existing = [Source(canonical_url="https://example.com/1", title="Old")]
        results = [
            SearchResult(url="https://example.com/1", title="New", snippet="Snip"),
            SearchResult(url="https://example.com/2", title="New 2", snippet="Snip"),
        ]
        sources = deduplicate_sources(existing, results)
        assert len(sources) == 1
        assert sources[0].canonical_url == "https://example.com/2"

    def test_normalized_duplicate(self):
        """规范化后相同的 URL 应去重"""
        existing = [Source(canonical_url="https://example.com/page/", title="Existing")]
        results = [
            SearchResult(url="https://Example.com/page", title="New", snippet="Snip"),
        ]
        sources = deduplicate_sources(existing, results)
        assert len(sources) == 0

    def test_empty_url_skipped(self):
        """空 URL 应跳过"""
        results = [
            SearchResult(url="", title="No URL", snippet="Snip"),
            SearchResult(url="https://example.com/1", title="Real", snippet="Snip"),
        ]
        sources = deduplicate_sources([], results)
        assert len(sources) == 1

    def test_all_duplicates(self):
        """全部重复时返回空列表"""
        existing = [Source(canonical_url="https://example.com/1", title="A")]
        results = [SearchResult(url="https://example.com/1", title="A", snippet="Snip")]
        sources = deduplicate_sources(existing, results)
        assert len(sources) == 0


class TestCredibilityEvaluation:
    """可信度评估测试"""

    def test_default_score(self):
        """默认应为 0.5"""
        source = Source(canonical_url="https://example.com")
        score, reasons = evaluate_credibility(source, "")
        assert score == 0.3  # -0.2 for empty content

    def test_long_content_boost(self):
        """长内容应加分"""
        source = Source(canonical_url="https://example.com")
        content = "word " * 600
        score, reasons = evaluate_credibility(source, content)
        assert score > 0.5

    def test_short_content_penalty(self):
        """短内容应扣分"""
        source = Source(canonical_url="https://example.com")
        content = "short text"
        score, reasons = evaluate_credibility(source, content)
        # 0.5 (base) - 0.1 (short) + source_type unknown 0.0 = 0.4
        assert score == 0.4

    def test_official_source_boost(self):
        """官方来源应加分"""
        source = Source(
            canonical_url="https://www.gov.cn/policy",
            source_type="official",
        )
        score, reasons = evaluate_credibility(source, "word " * 600)
        # base 0.5 + official 0.3 + long_content 0.1 = 0.9
        assert abs(score - 0.9) < 0.01

    def test_forum_source_penalty(self):
        """论坛来源应有较低分"""
        source = Source(
            canonical_url="https://reddit.com/r/python",
            source_type="forum",
        )
        score, reasons = evaluate_credibility(source, "word " * 600)
        # base 0.5 + forum -0.2 + long_content 0.1 = 0.4
        assert abs(score - 0.4) < 0.01
