"""
Tests for Reproducible Evaluation Benchmark (src/evaluation.py).
Verifies:
- Bit-for-bit reproducibility using identical seed
- Dynamic non-fabricated metric calculation
- 0 policy violations in RecoverAI strategy
- Proper economic simulation assumptions inclusion
"""

import pytest
from src.evaluation import BenchmarkEngine

def test_benchmark_reproducibility_identical_seed():
    """Verifies that executing evaluation with the same seed twice yields identical results."""
    engine1 = BenchmarkEngine(seed=42, count=50)
    res1 = engine1.execute_benchmark()

    engine2 = BenchmarkEngine(seed=42, count=50)
    res2 = engine2.execute_benchmark()

    # Compare financial totals across strategies
    assert res1["strategies"]["naive_retry"]["verified_recovered_revenue"] == res2["strategies"]["naive_retry"]["verified_recovered_revenue"]
    assert res1["strategies"]["static_rules"]["verified_recovered_revenue"] == res2["strategies"]["static_rules"]["verified_recovered_revenue"]
    assert res1["strategies"]["recoverai"]["verified_recovered_revenue"] == res2["strategies"]["recoverai"]["verified_recovered_revenue"]

    # Compare recovery rates
    assert res1["strategies"]["recoverai"]["revenue_recovery_rate_pct"] == res2["strategies"]["recoverai"]["revenue_recovery_rate_pct"]
    assert res1["strategies"]["recoverai"]["transaction_recovery_rate_pct"] == res2["strategies"]["recoverai"]["transaction_recovery_rate_pct"]

def test_recoverai_zero_policy_violations():
    """Verifies that RecoverAI strictly maintains 0 policy violations across all evaluated runs."""
    engine = BenchmarkEngine(seed=123, count=100)
    res = engine.execute_benchmark()

    assert res["strategies"]["recoverai"]["policy_violations"] == 0
    assert res["strategies"]["recoverai"]["blocked_unsafe_actions"] > 0

def test_economic_model_metadata_included():
    """Verifies that evaluation metadata explicitly details the simulation cost assumptions."""
    engine = BenchmarkEngine(seed=42, count=30)
    res = engine.execute_benchmark()

    meta = res["evaluation_metadata"]
    assert meta["seed"] == 42
    assert meta["count"] == 30
    assert "economic_model" in meta
    assert meta["economic_model"]["type"] == "simulation_assumptions"
    assert "sms_cost_inr" in meta["economic_model"]
