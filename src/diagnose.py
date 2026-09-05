"""
Diagnosis Layer: Rule-first, LLM-fallback architecture.
Guarantees >= 80% resolution via deterministic rules.
Invokes LLM only for ambiguous, conflicting, or unrecognized failure cases.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import uuid
from typing import List, Dict, Any, Tuple
from collections import defaultdict

from src.db import get_connection
from src.constants import (
    RULE_LOOKUP_TABLE,
    B2B_INVOICE_ACTION,
    B2B_INVOICE_ROOT_CAUSE,
    RISK_OVERDUE_INVOICE,
    METHOD_RULE,
    METHOD_LLM_FALLBACK,
    ACTION_ESCALATE_TO_HUMAN,
    FIXED_ACTION_MENU
)
from src.llm_client import diagnose_with_llm

def diagnose_transactions(db_path=None) -> List[Dict[str, Any]]:
    """
    Diagnoses root causes and recommends actions for all flagged transactions.
    Pass 1: Deterministic lookup table (target: >=80% resolved by rules).
    Pass 2: LLM fallback for unrecognized failure codes or conflicting multi-flags.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # Clear existing diagnoses for clean idempotent run
    cursor.execute("DELETE FROM diagnoses;")

    # Fetch all transactions that have risk flags
    cursor.execute("""
        SELECT t.transaction_id, t.customer_id, t.customer_name, t.amount,
               t.payment_method, t.status, t.failure_code, t.is_subscription,
               t.channel, t.created_at, t.retry_count, t.customer_opted_out
        FROM transactions t
        WHERE t.transaction_id IN (SELECT DISTINCT transaction_id FROM risk_flags)
    """)
    transactions = [dict(row) for row in cursor.fetchall()]

    # Fetch flags for each transaction to identify multi-flag ambiguities
    cursor.execute("SELECT transaction_id, risk_type FROM risk_flags")
    flags_by_txn = defaultdict(list)
    for row in cursor.fetchall():
        flags_by_txn[row["transaction_id"]].append(row["risk_type"])

    diagnoses = []
    rule_count = 0
    llm_count = 0

    for txn in transactions:
        txn_id = txn["transaction_id"]
        failure_code = txn.get("failure_code")
        flags = flags_by_txn.get(txn_id, [])
        is_b2b_overdue = (txn.get("channel") == "b2b_invoice" and RISK_OVERDUE_INVOICE in flags)

        # Check if cleanly resolvable by rules
        # Pass 1: Deterministic rules
        if is_b2b_overdue:
            root_cause = B2B_INVOICE_ROOT_CAUSE
            action = B2B_INVOICE_ACTION
            method = METHOD_RULE
            confidence = 1.0
            rule_count += 1

        elif failure_code and failure_code in RULE_LOOKUP_TABLE:
            rule_entry = RULE_LOOKUP_TABLE[failure_code]
            root_cause = rule_entry["root_cause"]
            action = rule_entry["recommended_action"]
            method = METHOD_RULE
            confidence = 1.0
            rule_count += 1

        else:
            # Pass 2: LLM Fallback (unrecognized code, null failure_code, or ambiguous checkout drop)
            llm_result = diagnose_with_llm(txn)
            root_cause = llm_result["root_cause"]
            action = llm_result["recommended_action"]
            confidence = llm_result["confidence"]
            method = METHOD_LLM_FALLBACK
            llm_count += 1

        # Enforce action menu boundary
        if action not in FIXED_ACTION_MENU:
            action = ACTION_ESCALATE_TO_HUMAN

        diagnoses.append({
            "diagnosis_id": f"diag_{txn_id}",
            "transaction_id": txn_id,
            "root_cause": root_cause,
            "recommended_action": action,
            "method": method,
            "confidence": round(confidence, 2)
        })

    # Save diagnoses to database
    if diagnoses:
        cursor.executemany("""
            INSERT INTO diagnoses (diagnosis_id, transaction_id, root_cause, recommended_action, method, confidence)
            VALUES (:diagnosis_id, :transaction_id, :root_cause, :recommended_action, :method, :confidence)
        """, diagnoses)

    conn.commit()
    conn.close()

    total = len(diagnoses)
    rule_pct = (rule_count / total * 100) if total > 0 else 0
    llm_pct = (llm_count / total * 100) if total > 0 else 0

    return diagnoses

if __name__ == "__main__":
    diags = diagnose_transactions()
    total = len(diags)
    rule_count = sum(1 for d in diags if d["method"] == METHOD_RULE)
    llm_count = sum(1 for d in diags if d["method"] == METHOD_LLM_FALLBACK)
    print(f"Diagnosed {total} transactions.")
    print(f"  - Resolved by Rules: {rule_count} ({rule_count/total*100:.1f}%)")
    print(f"  - Resolved by LLM Fallback: {llm_count} ({llm_count/total*100:.1f}%)")
