"""
End-to-End Pipeline Runner for RecoverAI.
Executes the full pipeline:
generate_data -> detect -> diagnose -> execute -> ptp_tracker -> metrics.
Prints clean summary and exports report.json.
"""

import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.generate_data import generate_transactions
from src.detect import detect_revenue_at_risk
from src.diagnose import diagnose_transactions
from src.execute import execute_recovery_actions
from src.ptp_tracker import process_promises_to_pay
from src.metrics import calculate_metrics

def run_full_pipeline(count: int = 200, db_path=None, seed: int = 42, generate_new: bool = True):
    """
    Executes the autonomous payment recovery pipeline end-to-end.
    """
    print("=" * 60)
    print("   RECOVERAI: AUTONOMOUS REVENUE RECOVERY AGENT PIPELINE")
    print("=" * 60)

    # Step 1: Generate synthetic transactions batch
    if generate_new:
        print(f"\n[Step 1/5] Generating fresh batch of {count} synthetic transactions...")
        df = generate_transactions(count=count, db_path=db_path, seed=seed)
        print(f"  -> Generated {len(df)} transactions in SQLite & CSV.")
    else:
        print("\n[Step 1/5] Using existing transactions batch in database.")

    # Step 2: Deterministic Risk Detection
    print("\n[Step 2/5] Running deterministic detection layer...")
    flags = detect_revenue_at_risk(db_path=db_path)
    print(f"  -> Detected {len(flags)} risk flags across transactions.")

    # Step 3: Root-Cause Diagnosis (Rule-First + LLM Fallback)
    print("\n[Step 3/5] Diagnosing root causes & recommended actions...")
    diagnoses = diagnose_transactions(db_path=db_path)
    rule_count = sum(1 for d in diagnoses if d["method"] == "rule")
    llm_count = sum(1 for d in diagnoses if d["method"] == "llm_fallback")
    print(f"  -> Diagnosed {len(diagnoses)} transactions:")
    print(f"     - Rule-Engine: {rule_count} ({rule_count/len(diagnoses)*100:.1f}%)" if diagnoses else "     - 0")
    print(f"     - LLM-Fallback: {llm_count} ({llm_count/len(diagnoses)*100:.1f}%)" if diagnoses else "     - 0")

    # Step 4: Bounded Action Execution & Stopping Rules
    print("\n[Step 4/5] Executing bounded recovery actions & stopping rules...")
    actions = execute_recovery_actions(db_path=db_path)
    stopped_count = sum(1 for a in actions if a["action_type"] == "stop_contact")
    print(f"  -> Executed {len(actions)} recovery actions ({stopped_count} halted by compliance/guardrails).")

    # Step 5: Promise-to-Pay Tracking & Automatic Follow-Up
    print("\n[Step 5/5] Processing promises-to-pay and follow-up reminders...")
    ptp_res = process_promises_to_pay(db_path=db_path, seed=seed)
    print(f"  -> New promises: {ptp_res['new_promises_count']}")
    print(f"  -> Fulfilled & Recovered: {ptp_res['fulfilled_count']}")
    print(f"  -> Follow-ups dispatched: {ptp_res['follow_ups_sent']}")

    # Metrics Engine
    print("\n[Summary] Computing metrics and generating report.json...")
    metrics = calculate_metrics(db_path=db_path)

    summary = metrics["summary"]
    ai = metrics["ai_judgment_discipline"]
    guard = metrics["compliance_guardrails"]

    print("\n" + "=" * 60)
    print("                  HEADLINE RESULTS")
    print("=" * 60)
    print(f" Total Transactions Batch:     {summary['total_transactions']}")
    print(f" Total Batch Volume:           INR {summary['total_batch_volume_inr']:,.2f}")
    print(f" Revenue At Risk:              INR {summary['revenue_at_risk_inr']:,.2f} ({summary['transactions_at_risk']} transactions)")
    print(f" Revenue Successfully Recovered: INR {summary['revenue_recovered_inr']:,.2f} ({summary['transactions_recovered']} transactions)")
    print(f" Overall Recovery Rate:        {summary['overall_recovery_rate_pct']}%")
    print(f" AI Judgment Discipline Split: {ai['resolved_by_rules_pct']}% Rules | {ai['resolved_by_llm_fallback_pct']}% LLM")
    print(f" Compliance Stops Enforced:    {guard['total_stopped']} (Opt-Outs: {guard['stopped_for_opt_out']}, Max-Attempts: {guard['stopped_for_max_attempts']})")
    print(f" Average Attempts to Recovery: {summary['average_attempts_to_recovery']}")
    print("=" * 60)

    return metrics

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run RecoverAI end-to-end recovery pipeline")
    parser.add_argument("--count", type=int, default=200, help="Number of synthetic transactions to generate (150-300)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for repeatable batches")
    parser.add_argument("--no-generate", action="store_true", help="Skip data generation and use existing database")

    args = parser.parse_args()
    run_full_pipeline(count=args.count, seed=args.seed, generate_new=not args.no_generate)
