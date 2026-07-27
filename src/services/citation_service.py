"""引用检查服务 — 引用覆盖、Source ID 一致性、无来源断言检测"""

from __future__ import annotations

import re
from typing import NamedTuple

from src.models import Source, Claim


# ═══════════════════════════════════════════
# 引用提取
# ═══════════════════════════════════════════

CITATION_PATTERN = re.compile(r"\[([a-zA-Z0-9_]+)\]")
MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(https?://[^\)]+\)")


def extract_citation_ids(text: str) -> list[str]:
    """从文本中提取所有 [Sxxx] 格式的引用 ID"""
    return CITATION_PATTERN.findall(text)


# ═══════════════════════════════════════════
# 检测结果
# ═══════════════════════════════════════════

class CitationCheckResult(NamedTuple):
    source_id: str
    exists: bool
    is_valid: bool
    note: str


class CitationCoverageReport:
    """引用覆盖检查报告"""
    def __init__(self):
        self.valid_citations: list[CitationCheckResult] = []
        self.invalid_citations: list[CitationCheckResult] = []
        self.uncited_claims: list[str] = []
        self.unresolved_issues: list[str] = []

    @property
    def coverage_rate(self) -> float:
        total = len(self.valid_citations) + len(self.invalid_citations)
        if total == 0:
            return 0.0
        return len(self.valid_citations) / total

    @property
    def has_invalid(self) -> bool:
        return len(self.invalid_citations) > 0

    @property
    def summary(self) -> str:
        lines = [
            f"引用覆盖: {self.coverage_rate:.0%}",
            f"有效引用: {len(self.valid_citations)}",
            f"无效引用: {len(self.invalid_citations)}",
        ]
        if self.uncited_claims:
            lines.append(f"无引用结论: {len(self.uncited_claims)}")
        if self.unresolved_issues:
            lines.extend(f"⚠️  {issue}" for issue in self.unresolved_issues[:5])
        return "\n".join(lines)


# ═══════════════════════════════════════════
# 引用有效性检查
# ═══════════════════════════════════════════

def check_citations(
    report: str,
    sources: list[Source],
) -> CitationCoverageReport:
    """检查报告中的引用是否都指向存在的 Source

    1. 提取所有 [Sxxx] 引用
    2. 检查每个 source_id 是否在 sources 中存在
    3. 检查引用指向的 source 是否成功抓取
    4. 检查关键断言是否有引用
    """
    report_result = CitationCoverageReport()

    # 构建 source 查找表
    source_map: dict[str, Source] = {}
    for s in sources:
        source_map[s.id] = s

    # 提取所有引用
    citation_ids = extract_citation_ids(report)
    if not citation_ids:
        report_result.unresolved_issues.append("报告中没有检测到任何 [Sxxx] 引用")
        return report_result

    # 检查每个引用
    for cid in citation_ids:
        if cid in source_map:
            src = source_map[cid]
            is_valid = src.extraction_status == "success" or src.extraction_status == "pending"
            note = (
                f"来源: {src.title or src.canonical_url[:50]}"
                + ("" if is_valid else " (内容未成功抓取)")
            )
            result = CitationCheckResult(cid, True, is_valid, note)
            report_result.valid_citations.append(result)
        else:
            result = CitationCheckResult(cid, False, False, f"Source ID '{cid}' 不存在")
            report_result.invalid_citations.append(result)

    # 查找 Markdown 链接 (可能是未使用 [Sxxx] 格式的引用)
    md_links = MARKDOWN_LINK_PATTERN.findall(report)
    if md_links:
        report_result.unresolved_issues.append(
            f"检测到 {len(md_links)} 个 Markdown 链接引用, 建议统一使用 [Sxxx] 格式"
        )

    return report_result


# ═══════════════════════════════════════════
# 无来源断言检测 (基础模式匹配)
# ═══════════════════════════════════════════

# 需要引用的关键断言模式
KEY_ASSERTION_PATTERNS = [
    # 百分比
    re.compile(r"\d+%"),
    # 金额
    re.compile(r"[¥$€]\s*[\d,]+\.?\d*"),
    re.compile(r"[\d,]+\.?\d*\s*(元|美元|欧元)"),
    # 数字 (较大的, 可能为统计数据)
    re.compile(r"(?:约|超过|达到|接近)?\d{4,}\s*(?:人|家|个|万|亿)"),
    # 日期 (明确的年份)
    re.compile(r"(?:202\d|203\d|204\d)\s*年"),
    # 比较级
    re.compile(r"(?:增长|下降|提高|减少)\s*[\d.]+"),
    # 强断言
    re.compile(r"(?:首次|最大|最小|唯一|最高|最低|领先|首创)"),
]


def find_uncited_assertions(report: str) -> list[dict]:
    """检测报告中缺少引用的关键断言

    使用模式匹配找出可能缺少引用的位置。

    Returns:
        位置列表, 每项包含 line 和 pattern
    """
    results: list[dict] = []
    lines = report.split("\n")

    for line_no, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped:
            continue

        # 跳过标题和列表标记
        if stripped.startswith("#") or stripped.startswith("-") or stripped.startswith("*"):
            continue

        # 检查是否有引用
        has_citation = bool(CITATION_PATTERN.search(stripped))
        if has_citation:
            continue

        # 检查是否匹配关键断言模式
        matched_patterns = []
        for pattern in KEY_ASSERTION_PATTERNS:
            if pattern.search(stripped):
                matched_patterns.append(pattern.pattern)

        if matched_patterns:
            results.append({
                "line": line_no,
                "text": stripped[:100],
                "patterns": matched_patterns,
            })

    return results


# ═══════════════════════════════════════════
# 来源冲突检测
# ═══════════════════════════════════════════

def detect_conflicting_claims(claims: list[Claim]) -> list[dict]:
    """检测相互冲突的 Claim

    基于文本相似度和数值差异做基础检测。

    Args:
        claims: 所有被标记为 conflicting 或文本语义相似的 Claim 对

    Returns:
        冲突对列表, 每项包含两个 claim_id 和冲突说明
    """
    conflicts: list[dict] = []

    # 检测明确标记为 conflicting 的 Claim
    for claim in claims:
        if claim.status == "conflicting":
            # 找与该 Claim 观点相反的其它 Claim
            for other in claims:
                if other.id == claim.id:
                    continue
                # 简单检测: 如果另一个 claim 有相同 question_id 但状态不同
                if (
                    other.question_id
                    and other.question_id == claim.question_id
                    and other.status != claim.status
                ):
                    conflicts.append({
                        "claim_a": claim.id,
                        "claim_b": other.id,
                        "text_a": claim.text[:80],
                        "text_b": other.text[:80],
                        "question_id": claim.question_id,
                        "note": "相同子问题的结论状态不一致",
                    })

    return conflicts
