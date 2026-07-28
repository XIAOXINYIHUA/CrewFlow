"""引用检查服务测试 — 引用提取、有效性验证、无来源断言检测、冲突检测"""

from src.models import Claim, Evidence, Source
from src.services.citation_service import (
    CitationCoverageReport,
    check_citations,
    detect_conflicting_claims,
    extract_citation_ids,
    find_uncited_assertions,
)


class TestExtractCitationIDs:
    """引用 ID 提取测试"""

    def test_basic_extraction(self):
        """基本引用提取"""
        text = "AI 能提升效率 [S001]。"
        assert extract_citation_ids(text) == ["S001"]

    def test_multiple_citations(self):
        """多个引用"""
        text = "据研究 [S001][S002] 显示, 市场增长 [S003]。"
        assert extract_citation_ids(text) == ["S001", "S002", "S003"]

    def test_no_citations(self):
        """无引用返回空列表"""
        assert extract_citation_ids("这是一段没有引用的文本。") == []

    def test_citation_in_mixed_text(self):
        """混合文本中的引用"""
        text = "根据[S001]的统计, 2024年市场规模[S002]达到新高。"
        ids = extract_citation_ids(text)
        assert "S001" in ids
        assert "S002" in ids

    def test_underscore_ids(self):
        """支持下划线的引用 ID"""
        text = "数据来源 [S_src_01]。"
        assert "_" in extract_citation_ids(text)[0]

    def test_empty_text(self):
        """空文本返回空列表"""
        assert extract_citation_ids("") == []


class TestCheckCitations:
    """引用有效性检查测试"""

    def test_all_valid(self):
        """全部有效引用"""
        sources = [Source(id="S001", canonical_url="https://a.com", title="A")]
        report = "内容 [S001]。"
        result = check_citations(report, sources)
        assert len(result.valid_citations) == 1
        assert len(result.invalid_citations) == 0
        assert result.coverage_rate == 1.0

    def test_invalid_source_id(self):
        """无效的 Source ID"""
        sources = [Source(id="S001", canonical_url="https://a.com")]
        report = "内容 [S999]。"
        result = check_citations(report, sources)
        assert len(result.invalid_citations) == 1
        assert result.invalid_citations[0].source_id == "S999"
        assert not result.invalid_citations[0].exists

    def test_mixed_valid_invalid(self):
        """混合有效和无效引用"""
        sources = [
            Source(id="S001", canonical_url="https://a.com"),
            Source(id="S002", canonical_url="https://b.com"),
        ]
        report = "引用 [S001] 和 [S999] 和 [S002]。"
        result = check_citations(report, sources)
        assert len(result.valid_citations) == 2
        assert len(result.invalid_citations) == 1

    def test_no_citations_in_report(self):
        """报告中无引用"""
        sources = [Source(id="S001", canonical_url="https://a.com")]
        report = "没有任何引用。"
        result = check_citations(report, sources)
        assert len(result.unresolved_issues) > 0

    def test_source_failed_extraction(self):
        """引用指向抓取失败的来源"""
        sources = [
            Source(
                id="S001",
                canonical_url="https://a.com",
                extraction_status="failed",
            )
        ]
        report = "引用 [S001]。"
        result = check_citations(report, sources)
        # S001 存在但抓取失败, 应标为无效
        valid_exists = any(c.source_id == "S001" and not c.is_valid for c in result.valid_citations)
        assert valid_exists

    def test_empty_sources(self):
        """空来源列表"""
        report = "引用 [S001]。"
        result = check_citations(report, [])
        assert len(result.invalid_citations) == 1


class TestFindUncitedAssertions:
    """无引用断言检测测试"""

    def test_percentage_needs_citation(self):
        """百分比需要引用"""
        text = "效率提升了 30%。"
        results = find_uncited_assertions(text)
        assert len(results) > 0

    def test_percentage_with_citation(self):
        """已有引用的百分比不触发"""
        text = "效率提升了 30% [S001]。"
        results = find_uncited_assertions(text)
        # 有引用, 不触发
        assert len(results) == 0

    def test_currency_amount(self):
        """金额需要引用"""
        text = "市场规模达到 5000 万元。"
        results = find_uncited_assertions(text)
        assert len(results) > 0

    def test_strong_claim(self):
        """强断言需要引用"""
        text = "该公司是行业首次实现此技术。"
        results = find_uncited_assertions(text)
        assert len(results) > 0

    def test_headings_ignored(self):
        """标题不触发告警"""
        text = "## 背景介绍"
        results = find_uncited_assertions(text)
        matching = [r for r in results if r["text"] == "## 背景介绍"]
        assert len(matching) == 0

    def test_list_items_ignored(self):
        """列表项不触发告警"""
        text = "- 效率提升 30%"
        results = find_uncited_assertions(text)
        matching = [r for r in results if r["text"] == "- 效率提升 30%"]
        assert len(matching) == 0

    def test_empty_text(self):
        """空文本无告警"""
        assert find_uncited_assertions("") == []

    def test_multiple_lines(self):
        """多行文本检测"""
        text = """# 报告标题
## 背景
这是背景介绍。
## 数据
市场规模达到 5000 万元。
效率提升 50% [S001]。"""
        results = find_uncited_assertions(text)
        # "市场规模达到 5000 万元" 无引用
        assert len(results) >= 1


class TestDetectConflictingClaims:
    """来源冲突检测测试"""

    def test_no_conflicts(self):
        """无冲突时返回空列表"""
        claims = [
            Claim(text="AI 提升效率", status="supported"),
            Claim(text="AI 降低成本", status="supported"),
        ]
        assert detect_conflicting_claims(claims) == []

    def test_conflicting_claims(self):
        """检测到冲突"""
        claims = [
            Claim(id="C001", text="AI 提升效率 30%", status="supported", question_id="q1"),
            Claim(
                id="C002",
                text="AI 只提升效率 5%",
                status="conflicting",
                question_id="q1",
                evidence=[Evidence(source_id="S001", quote="test")],
            ),
        ]
        conflicts = detect_conflicting_claims(claims)
        assert len(conflicts) > 0
        assert conflicts[0]["claim_a"] == "C001" or conflicts[0]["claim_b"] == "C001"

    def test_different_questions_no_conflict(self):
        """不同子问题的不同状态不视为冲突"""
        claims = [
            Claim(id="C001", text="A", status="supported", question_id="q1"),
            Claim(
                id="C002",
                text="B",
                status="conflicting",
                question_id="q2",
                evidence=[Evidence(source_id="S001", quote="test")],
            ),
        ]
        assert detect_conflicting_claims(claims) == []


class TestCitationCoverageReport:
    """CitationCoverageReport 测试"""

    def test_empty_report(self):
        """空报告"""
        report = CitationCoverageReport()
        assert report.coverage_rate == 0.0
        assert not report.has_invalid

    def test_full_coverage(self):
        """全覆盖"""
        report = CitationCoverageReport()
        report.valid_citations = [
            ("S001", True, True, "OK"),  # type: ignore
            ("S002", True, True, "OK"),  # type: ignore
        ]
        assert report.coverage_rate == 1.0

    def test_partial_coverage(self):
        """部分覆盖"""
        report = CitationCoverageReport()
        report.valid_citations = [("S001", True, True, "OK")]  # type: ignore
        report.invalid_citations = [("S999", False, False, "不存在")]  # type: ignore
        assert report.coverage_rate == 0.5
        assert report.has_invalid

    def test_summary_format(self):
        """摘要格式"""
        report = CitationCoverageReport()
        report.valid_citations = [("S001", True, True, "OK")]  # type: ignore
        summary = report.summary
        assert "引用覆盖" in summary
        assert "100%" in summary or "有效引用" in summary
