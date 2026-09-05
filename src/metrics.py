"""
Metrics Engine for RecoverAI.
Calculates headline financial KPIs, recovery rates, AI-vs-Rule discipline split,
and compliance guardrail metrics.
Exports results to report.json.
PRD Section 6.7.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import os
import json
from typing import Dict, Any
from src.db import get_connection
from src.constants import (
    METHOD_RULE,
    METHOD_LLM_FALLBACK,
    ACTION_STOP_CONTACT,
    STOPPED_REASON_OPTED_OUT,
    STOPPED_REASON_MAX_ATTEMPTS,
    SILENT_ACTIONS
)

def get_default_report_path() -> Path:
    if os.getenv("VERCEL"):
        return Path("/tmp/report.json")
    return PROJECT_ROOT / "report.json"

REPORT_PATH = get_default_report_path()

def calculate_metrics(db_path=None, export_path=None) -> Dict[str, Any]:
    """
    Computes all PRD required metrics from recovery.db:
    - Total batch transactions & revenue at risk
    - Total recovered revenue & recovery rate (%)
    - Recovery rate by failure_code
    - AI-vs-Rule diagnosis distribution
    - Compliance stopping counts (opt-out vs max-attempts)
    - Average attempts to recovery
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # Total batch transactions
    cursor.execute("SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM transactions")
    row = cursor.fetchone()
    total_txns = row[0]
    total_batch_volume = round(row[1], 2)

    # Flagged / Revenue at Risk
    cursor.execute("""
        SELECT COUNT(DISTINCT t.transaction_id), COALESCE(SUM(t.amount), 0)
        FROM transactions t
        WHERE t.transaction_id IN (SELECT DISTINCT transaction_id FROM risk_flags)
    """)
    row = cursor.fetchone()
    flagged_txn_count = row[0]
    revenue_at_risk = round(row[1], 2)

    # Recovered Transactions
    cursor.execute("""
        SELECT COUNT(*), COALESCE(SUM(amount), 0)
        FROM transactions
        WHERE recovered = 1
    """)
    row = cursor.fetchone()
    recovered_txn_count = row[0]
    amount_recovered = round(row[1], 2)

    # Dual Recovery Rates
    revenue_recovery_rate_pct = round((amount_recovered / revenue_at_risk * 100), 2) if revenue_at_risk > 0 else 0.0
    transaction_recovery_rate_pct = round((recovered_txn_count / flagged_txn_count * 100), 2) if flagged_txn_count > 0 else 0.0

    # Diagnoses split (Deterministic Rules vs LLM Fallback)
    cursor.execute("SELECT method, COUNT(*) FROM diagnoses GROUP BY method")
    method_counts = dict(cursor.fetchall())
    rule_count = method_counts.get(METHOD_RULE, 0)
    llm_count = method_counts.get(METHOD_LLM_FALLBACK, 0)
    total_diagnoses = rule_count + llm_count
    rule_pct = round((rule_count / total_diagnoses * 100), 1) if total_diagnoses > 0 else 0.0
    llm_pct = round((llm_count / total_diagnoses * 100), 1) if total_diagnoses > 0 else 0.0

    # Modeled Recovery Cost Accounting (Configurable Simulation Assumptions)
    from src.constants import (
        SIMULATION_ECONOMIC_MODEL,
        SIMULATION_SMS_COST_INR,
        SIMULATION_WHATSAPP_COST_INR,
        SIMULATION_RETRY_COST_INR,
        SIMULATION_LLM_COST_INR,
        SIMULATION_ESCALATION_COST_INR,
    )
    cursor.execute("SELECT action_type, COUNT(*) FROM actions_log GROUP BY action_type")
    action_counts = dict(cursor.fetchall())
    
    sms_cost = action_counts.get("send_reminder_sms", 0) * SIMULATION_SMS_COST_INR
    wa_cost = (action_counts.get("send_update_card_link", 0) + action_counts.get("send_mandate_renewal_link", 0)) * SIMULATION_WHATSAPP_COST_INR
    retry_cost = action_counts.get("retry_silently", 0) * SIMULATION_RETRY_COST_INR
    llm_cost = llm_count * SIMULATION_LLM_COST_INR
    esc_cost = action_counts.get("escalate_to_human", 0) * SIMULATION_ESCALATION_COST_INR
    
    total_modeled_cost = round(sms_cost + wa_cost + retry_cost + llm_cost + esc_cost, 2)
    net_recovered_val = round(amount_recovered - total_modeled_cost, 2)
    cost_per_payment = round(total_modeled_cost / recovered_txn_count, 2) if recovered_txn_count > 0 else 0.0

    # Compliance Stopping Rules Breakdown
    cursor.execute("""
        SELECT stopped_reason, COUNT(*)
        FROM actions_log
        WHERE action_type = ? AND stopped_reason IS NOT NULL
        GROUP BY stopped_reason
    """, (ACTION_STOP_CONTACT,))
    stop_counts = dict(cursor.fetchall())
    total_stopped = sum(stop_counts.values())

    # Recovery Breakdown by Failure Code
    cursor.execute("""
        SELECT 
            COALESCE(t.failure_code, 'abandoned_or_unclassified') AS code,
            COUNT(*) AS at_risk_count,
            COALESCE(SUM(t.amount), 0) AS at_risk_amount,
            SUM(CASE WHEN t.recovered = 1 THEN 1 ELSE 0 END) AS recovered_count,
            COALESCE(SUM(CASE WHEN t.recovered = 1 THEN t.amount ELSE 0 END), 0) AS recovered_amount
        FROM transactions t
        WHERE t.transaction_id IN (SELECT DISTINCT transaction_id FROM risk_flags)
        GROUP BY COALESCE(t.failure_code, 'abandoned_or_unclassified')
        ORDER BY at_risk_amount DESC
    """)
    breakdown_rows = cursor.fetchall()
    by_failure_code = []
    for r in breakdown_rows:
        code = r["code"]
        at_risk_amt = round(r["at_risk_amount"], 2)
        rec_amt = round(r["recovered_amount"], 2)
        rate = round((rec_amt / at_risk_amt * 100), 1) if at_risk_amt > 0 else 0.0
        by_failure_code.append({
            "failure_code": code,
            "at_risk_count": r["at_risk_count"],
            "at_risk_amount": at_risk_amt,
            "recovered_count": r["recovered_count"],
            "recovered_amount": rec_amt,
            "recovery_rate_pct": rate
        })

    # Average attempts to recovery
    cursor.execute("""
        SELECT a.transaction_id, MAX(a.attempt_number) as max_attempt
        FROM actions_log a
        JOIN transactions t ON a.transaction_id = t.transaction_id
        WHERE t.recovered = 1 AND a.action_type NOT IN (?, ?)
        GROUP BY a.transaction_id
    """, (tuple(SILENT_ACTIONS) + (ACTION_STOP_CONTACT,)))
    attempts_rows = cursor.fetchall()
    if attempts_rows:
        avg_attempts = round(sum(r["max_attempt"] for r in attempts_rows) / len(attempts_rows), 2)
    else:
        avg_attempts = 1.0

    conn.close()

    metrics = {
        "summary": {
            "total_transactions": total_txns,
            "total_batch_volume_inr": total_batch_volume,
            "transactions_at_risk": flagged_txn_count,
            "revenue_at_risk_inr": revenue_at_risk,
            # Dual Recovery Rates (Correction 1)
            "verified_recovered_transactions": recovered_txn_count,
            "transactions_recovered": recovered_txn_count,
            "transaction_recovery_rate_pct": transaction_recovery_rate_pct,
            "verified_recovered_revenue_inr": amount_recovered,
            "revenue_recovered_inr": amount_recovered,
            "revenue_recovery_rate_pct": revenue_recovery_rate_pct,
            "overall_recovery_rate_pct": revenue_recovery_rate_pct,
            # Economic metrics (Correction 11)
            "net_recovered_value_inr": net_recovered_val,
            "total_modeled_recovery_cost_inr": total_modeled_cost,
            "cost_per_recovered_payment_inr": cost_per_payment,
            "average_attempts_to_recovery": avg_attempts
        },
        "recovery_economics": {
            "gross_verified_recovered_revenue_inr": amount_recovered,
            "total_modeled_recovery_cost_inr": total_modeled_cost,
            "net_recovered_value_inr": net_recovered_val,
            "cost_per_recovered_payment_inr": cost_per_payment,
            "cost_breakdown": {
                "sms_cost_inr": round(sms_cost, 2),
                "whatsapp_cost_inr": round(wa_cost, 2),
                "retry_cost_inr": round(retry_cost, 2),
                "llm_cost_inr": round(llm_cost, 2),
                "escalation_cost_inr": round(esc_cost, 2)
            },
            "economic_model": SIMULATION_ECONOMIC_MODEL
        },
        "ai_judgment_discipline": {
            "total_diagnoses": total_diagnoses,
            "deterministic_diagnosis_share_pct": rule_pct,
            "resolved_by_rules": rule_count,
            "resolved_by_rules_pct": rule_pct,
            "llm_fallback_share_pct": llm_pct,
            "resolved_by_llm_fallback": llm_count,
            "resolved_by_llm_fallback_pct": llm_pct,
            "llm_calls_avoided": rule_count,
            "target_rule_resolution_achieved": rule_pct >= 80.0
        },
        "compliance_guardrails": {
            "total_stopped": total_stopped,
            "stopped_for_opt_out": stop_counts.get(STOPPED_REASON_OPTED_OUT, 0),
            "stopped_for_max_attempts": stop_counts.get(STOPPED_REASON_MAX_ATTEMPTS, 0),
            "other_stops": sum(v for k, v in stop_counts.items() if k not in (STOPPED_REASON_OPTED_OUT, STOPPED_REASON_MAX_ATTEMPTS))
        },
        "by_failure_code": by_failure_code
    }

    target_export = Path(export_path) if export_path else REPORT_PATH
    try:
        target_export.parent.mkdir(parents=True, exist_ok=True)
        with open(target_export, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)
    except Exception:
        pass

    return metrics

if __name__ == "__main__":
    m = calculate_metrics()
    print("=== RECOVERAI METRICS REPORT ===")
    print(f"Total Transactions: {m['summary']['total_transactions']}")
    print(f"Revenue At Risk:    INR {m['summary']['revenue_at_risk_inr']:,.2f} ({m['summary']['transactions_at_risk']} transactions)")
    print(f"Revenue Recovered:  INR {m['summary']['revenue_recovered_inr']:,.2f} ({m['summary']['transactions_recovered']} transactions)")
    print(f"Recovery Rate:      {m['summary']['overall_recovery_rate_pct']}%")
    print(f"Rule vs LLM Split:  {m['ai_judgment_discipline']['resolved_by_rules_pct']}% Rule / {m['ai_judgment_discipline']['resolved_by_llm_fallback_pct']}% LLM")
    print(f"Compliance Stops:   {m['compliance_guardrails']['total_stopped']} (Opt-Outs: {m['compliance_guardrails']['stopped_for_opt_out']}, Max Attempts: {m['compliance_guardrails']['stopped_for_max_attempts']})")
    print(f"Avg Attempts to Recovery: {m['summary']['average_attempts_to_recovery']}")
    print(f"\nReport exported to {REPORT_PATH}")
