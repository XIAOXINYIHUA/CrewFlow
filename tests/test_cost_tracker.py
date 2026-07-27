"""Token/成本跟踪测试"""

from decimal import Decimal
import pytest

from src.services.cost_tracker import TokenUsage, CostBudget, estimate_run_cost


class TestTokenUsage:
    """Token 用量计算测试"""

    def test_basic_calculation(self):
        usage = TokenUsage(model="gpt-4o-mini", prompt_tokens=1000, completion_tokens=500)
        assert usage.total_tokens == 1500
        assert usage.prompt_tokens == 1000
        assert usage.completion_tokens == 500

    def test_cost_estimation_gpt4o_mini(self):
        # input: 1000 * 0.00015/1K = 0.00015
        # output: 500 * 0.0006/1K = 0.0003
        usage = TokenUsage(model="gpt-4o-mini", prompt_tokens=1000, completion_tokens=500)
        assert usage.cost_usd == Decimal("0.00045")

    def test_cost_estimation_gpt4o(self):
        # input: 2000 * 0.0025/1K = 0.005
        # output: 500 * 0.01/1K = 0.005
        usage = TokenUsage(model="gpt-4o", prompt_tokens=2000, completion_tokens=500)
        assert usage.cost_usd == Decimal("0.01")

    def test_unknown_model_fallback(self):
        usage = TokenUsage(model="unknown", prompt_tokens=1000, completion_tokens=1000)
        # 使用 DEFAULT_PRICE
        assert usage.cost_usd > Decimal("0")

    def test_zero_tokens(self):
        usage = TokenUsage(model="gpt-4o-mini", prompt_tokens=0, completion_tokens=0)
        assert usage.cost_usd == Decimal("0")

    def test_to_dict(self):
        usage = TokenUsage(model="gpt-4o", prompt_tokens=100, completion_tokens=50)
        d = usage.to_dict()
        assert d["model"] == "gpt-4o"
        assert d["total_tokens"] == 150
        assert isinstance(d["cost_usd"], float)


class TestCostBudget:
    """预算跟踪测试"""

    def test_empty_budget(self):
        budget = CostBudget()
        assert budget.spent == Decimal("0")
        assert budget.total_calls == 0
        assert not budget.exceeded

    def test_record_usage(self):
        budget = CostBudget()
        budget.record(TokenUsage(model="gpt-4o-mini", prompt_tokens=1000, completion_tokens=500))
        assert budget.total_calls == 1
        assert budget.total_tokens == 1500

    def test_budget_exceeded(self):
        budget = CostBudget(max_cost_usd=Decimal("0.001"))
        budget.record(TokenUsage(model="gpt-4o", prompt_tokens=1000, completion_tokens=1000))
        assert budget.exceeded

    def test_budget_not_exceeded(self):
        budget = CostBudget(max_cost_usd=Decimal("1.0"))
        usage = TokenUsage(model="gpt-4o-mini", prompt_tokens=1000, completion_tokens=500)
        budget.record(usage)
        budget.record(usage)
        assert not budget.exceeded

    def test_no_budget_limit(self):
        budget = CostBudget(max_cost_usd=None)
        for _ in range(100):
            budget.record(TokenUsage(model="gpt-4o", prompt_tokens=10000, completion_tokens=5000))
        assert not budget.exceeded

    def test_summary(self):
        budget = CostBudget(max_cost_usd=Decimal("0.5"))
        budget.record(TokenUsage(model="gpt-4o-mini", prompt_tokens=1000, completion_tokens=500))
        summary = budget.summary()
        assert summary["total_calls"] == 1
        assert summary["max_cost_usd"] == 0.5
        assert summary["exceeded"] is False


class TestEstimateRunCost:
    """运行总成本估算测试"""

    def test_multiple_calls(self):
        records = [
            {"model": "gpt-4o-mini", "prompt_tokens": 1000, "completion_tokens": 500},
            {"model": "gpt-4o", "prompt_tokens": 2000, "completion_tokens": 1000},
            {"model": "gpt-4o-mini", "prompt_tokens": 500, "completion_tokens": 200},
        ]
        result = estimate_run_cost(records)
        assert result["total_calls"] == 3
        assert result["total_tokens"] > 0
        assert result["cost_usd"] > 0

    def test_empty(self):
        result = estimate_run_cost([])
        assert result["total_calls"] == 0
        assert result["cost_usd"] == 0.0
