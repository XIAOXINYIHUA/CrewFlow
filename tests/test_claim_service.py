"""Claim 服务测试 — 提取模型、合并逻辑、结构化输出"""
import pytest

from src.services.claim_service import (
    ExtractedClaim,
    ExtractedEvidence,
    SourceExtraction,
    BatchExtractionResult,
)


class TestExtractionModels:
    """结构化输出模型测试"""

    def test_valid_extracted_evidence(self):
        ev = ExtractedEvidence(quote="原文引用", supports_claim=True)
        assert ev.quote == "原文引用"
        assert ev.supports_claim is True

    def test_evidence_with_notes(self):
        ev = ExtractedEvidence(
            quote="市场增长30%",
            notes="2024年数据, 同比口径",
        )
        assert "同比" in ev.notes

    def test_valid_extracted_claim(self):
        claim = ExtractedClaim(
            text="AI提升开发效率",
            status="supported",
            confidence=0.85,
            evidence=[
                ExtractedEvidence(quote="效率提升30%"),
            ],
        )
        assert len(claim.evidence) == 1
        assert claim.status == "supported"

    def test_claim_default_values(self):
        claim = ExtractedClaim(text="测试结论")
        assert claim.status == "supported"
        assert claim.confidence == 0.7
        assert claim.evidence == []

    def test_claim_with_question_id(self):
        claim = ExtractedClaim(
            text="测试",
            question_id="q_001",
            evidence=[ExtractedEvidence(quote="quote")],
        )
        assert claim.question_id == "q_001"

    def test_source_extraction_quality(self):
        extraction = SourceExtraction(
            source_id="S001",
            claims=[],
            extraction_quality="failed",
            notes="内容为空",
        )
        assert extraction.extraction_quality == "failed"

    def test_batch_result(self):
        batch = BatchExtractionResult(extractions=[
            SourceExtraction(source_id="S001", claims=[]),
            SourceExtraction(source_id="S002", claims=[]),
        ])
        assert len(batch.extractions) == 2

    def test_claim_quality_default(self):
        extraction = SourceExtraction(source_id="S001")
        assert extraction.extraction_quality == "adequate"
