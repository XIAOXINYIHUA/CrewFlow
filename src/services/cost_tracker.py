"""Token 与成本跟踪 — 记录每次 LLM 调用的 token 用量和估算费用"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any


# ── 模型定价 (每 1K token, USD) ──
# 来源: OpenAI 2025-06 定价
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4o-2024-08-06": {"input": 0.0025, "output": 0.01},
    "gpt-4o-mini-2024-07-18": {"input": 0.00015, "output": 0.0006},
    # 扩展模型 (claude, gemini, deepseek)
    "claude-sonnet-4-20250514": {"input": 0.003, "output": 0.015},
    "claude-haiku-3-5-sonnet-20241022": {"input": 0.0008, "output": 0.004},
    "deepseek-chat": {"input": 0.00014, "output": 0.00028},
}

DEFAULT_PRICE = {"input": 0.001, "output": 0.002}  # 未知模型的保守估算


@dataclass
class TokenUsage:
    """单次 LLM 调用的 token 用量"""
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_prompt_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def cost_usd(self) -> Decimal:
        """估算调用费用"""
        pricing = MODEL_PRICING.get(self.model, DEFAULT_PRICE)
        input_cost = (self.prompt_tokens / 1000) * pricing["input"]
        output_cost = (self.completion_tokens / 1000) * pricing["output"]
        return Decimal(str(round(input_cost + output_cost, 6)))

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": float(self.cost_usd),
        }


@dataclass
class CostBudget:
    """运行预算跟踪"""
    max_cost_usd: Decimal | None = None
    _spent: Decimal = Decimal("0")
    _calls: list[TokenUsage] = field(default_factory=list)

    def record(self, usage: TokenUsage) -> None:
        """记录一次调用"""
        self._spent += usage.cost_usd
        self._calls.append(usage)

    @property
    def spent(self) -> Decimal:
        return self._spent

    @property
    def total_calls(self) -> int:
        return len(self._calls)

    @property
    def total_prompt_tokens(self) -> int:
        return sum(c.prompt_tokens for c in self._calls)

    @property
    def total_completion_tokens(self) -> int:
        return sum(c.completion_tokens for c in self._calls)

    @property
    def total_tokens(self) -> int:
        return self.total_prompt_tokens + self.total_completion_tokens

    @property
    def exceeded(self) -> bool:
        if self.max_cost_usd is None:
            return False
        return self._spent >= self.max_cost_usd

    def summary(self) -> dict:
        return {
            "total_calls": self.total_calls,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": float(self._spent),
            "max_cost_usd": float(self.max_cost_usd) if self.max_cost_usd else None,
            "exceeded": self.exceeded,
        }


def estimate_run_cost(token_counts: list[dict]) -> dict:
    """从记录列表估算总成本"""
    budget = CostBudget()
    for tc in token_counts:
        usage = TokenUsage(
            model=tc.get("model", "unknown"),
            prompt_tokens=tc.get("prompt_tokens", 0),
            completion_tokens=tc.get("completion_tokens", 0),
        )
        budget.record(usage)
    return budget.summary()
