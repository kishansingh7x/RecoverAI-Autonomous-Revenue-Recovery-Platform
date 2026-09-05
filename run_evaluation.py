#!/usr/bin/env python3
"""
CLI Runner for RecoverAI Reproducible Benchmark.
Usage:
    python run_evaluation.py --seed 42 --count 200
    python run_evaluation.py --seed 123 --count 500 --json
"""

import sys
import argparse
import json
from pathlib import Path

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation import BenchmarkEngine

def main():
    parser = argparse.ArgumentParser(description="RecoverAI Comparative Benchmark Runner")
    parser.add_argument("--seed", type=int, default=42, help="Seed for reproducible transaction generation")
    parser.add_argument("--count", type=int, default=200, help="Number of failed transactions to evaluate")
    parser.add_argument("--json", action="store_true", help="Print raw JSON output")
    args = parser.parse_args()

    engine = BenchmarkEngine(seed=args.seed, count=args.count)
    results = engine.execute_benchmark()

    if args.json:
        print(json.dumps(results, indent=2))
        return

    meta = results["evaluation_metadata"]
    strat = results["strategies"]
    comp = results["comparisons"]

    print("\n" + "=" * 80)
    print(f"RECOVERAI 3-WAY REPRODUCIBLE BENCHMARK EVALUATION")
    print(f"Dataset Seed: {meta['seed']} | Transactions Evaluated: {meta['count']}")
    print(f"Timestamp: {meta['timestamp']}")
    print("=" * 80)

    headers = [
        "Metric / Performance Vector",
        "Naive Retry",
        "Static Rules",
        "RecoverAI"
    ]
    
    rows = [
        ("Revenue at Risk", f"INR {strat['naive_retry']['revenue_at_risk']:,.2f}", f"INR {strat['static_rules']['revenue_at_risk']:,.2f}", f"INR {strat['recoverai']['revenue_at_risk']:,.2f}"),
        ("Verified Recovered Revenue", f"INR {strat['naive_retry']['verified_recovered_revenue']:,.2f}", f"INR {strat['static_rules']['verified_recovered_revenue']:,.2f}", f"INR {strat['recoverai']['verified_recovered_revenue']:,.2f}"),
        ("Revenue Recovery Rate (Primary)", f"{strat['naive_retry']['revenue_recovery_rate_pct']:.2f}%", f"{strat['static_rules']['revenue_recovery_rate_pct']:.2f}%", f"{strat['recoverai']['revenue_recovery_rate_pct']:.2f}%"),
        ("Verified Recovered Txns", f"{strat['naive_retry']['verified_recovered_transactions']}", f"{strat['static_rules']['verified_recovered_transactions']}", f"{strat['recoverai']['verified_recovered_transactions']}"),
        ("Transaction Recovery Rate", f"{strat['naive_retry']['transaction_recovery_rate_pct']:.2f}%", f"{strat['static_rules']['transaction_recovery_rate_pct']:.2f}%", f"{strat['recoverai']['transaction_recovery_rate_pct']:.2f}%"),
        ("Customer Contacts", f"{strat['naive_retry']['customer_contacts']}", f"{strat['static_rules']['customer_contacts']}", f"{strat['recoverai']['customer_contacts']}"),
        ("Avg Contacts / Customer", f"{strat['naive_retry']['average_contacts_per_customer']:.2f}", f"{strat['static_rules']['average_contacts_per_customer']:.2f}", f"{strat['recoverai']['average_contacts_per_customer']:.2f}"),
        ("Policy Violations", f"{strat['naive_retry']['policy_violations']}", f"{strat['static_rules']['policy_violations']}", f"{strat['recoverai']['policy_violations']} (Clean)"),
        ("Blocked Unsafe Actions", "N/A", "N/A", f"{strat['recoverai']['blocked_unsafe_actions']}"),
        ("Deterministic Diagnosis Share", "0.0%", "100.0%", f"{strat['recoverai']['deterministic_diagnosis_share_pct']:.1f}%"),
        ("LLM Fallback Share", "0.0%", "0.0%", f"{strat['recoverai']['llm_fallback_share_pct']:.1f}%"),
        ("Total Modeled Recovery Cost", f"INR {strat['naive_retry']['total_modeled_recovery_cost']:,.2f}", f"INR {strat['static_rules']['total_modeled_recovery_cost']:,.2f}", f"INR {strat['recoverai']['total_modeled_recovery_cost']:,.2f}"),
        ("Net Recovered Value (NRV)", f"INR {strat['naive_retry']['net_recovered_value']:,.2f}", f"INR {strat['static_rules']['net_recovered_value']:,.2f}", f"INR {strat['recoverai']['net_recovered_value']:,.2f}"),
        ("Cost per Recovered Payment", f"INR {strat['naive_retry']['cost_per_recovered_payment']:,.2f}", f"INR {strat['static_rules']['cost_per_recovered_payment']:,.2f}", f"INR {strat['recoverai']['cost_per_recovered_payment']:,.2f}"),
    ]

    col_w = [34, 20, 20, 22]
    header_line = "".join(f"{h:<{col_w[idx]}}" for idx, h in enumerate(headers))
    print(header_line)
    print("-" * 96)
    for r in rows:
        line = "".join(f"{str(val):<{col_w[idx]}}" for idx, val in enumerate(r))
        print(line)

    print("-" * 96)
    print("COMPARATIVE REVENUE UPLIFT & BUSINESS IMPACT:")
    print(f"  * Revenue Uplift vs Naive Retry:  +{comp['revenue_uplift_vs_naive_pct']:.2f}%")
    print(f"  * Revenue Uplift vs Static Rules: +{comp['revenue_uplift_vs_static_pct']:.2f}%")
    print(f"  * Net Value Uplift (NRV):        +INR {comp['net_value_uplift_inr']:,.2f}")
    print(f"  * Modeled Economic Model:        Configurable Simulation Assumptions")
    print("=" * 96 + "\n")

if __name__ == "__main__":
    main()
