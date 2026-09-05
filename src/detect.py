"""
Deterministic Revenue-at-Risk Detection Layer.
Purely deterministic rules (no AI).
Identifies transactions at risk and logs flags to the risk_flags table.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import uuid
from datetime import datetime
from typing import List, Dict, Any
from src.db import get_connection
from src.constants import (
    RISK_FAILED_NOT_RETRIED,
    RISK_ABANDONED_CHECKOUT,
    RISK_FAILED_SUBSCRIPTION,
    RISK_OVERDUE_INVOICE
)

def detect_revenue_at_risk(db_path=None, as_of: datetime = None) -> List[Dict[str, Any]]:
    """
    Scans the transactions table and flags transactions matching risk criteria.
    Rules (PRD Section 6.2):
    1. failed_payment_not_retried: status = 'failed' AND retry_count = 0 AND age > 24 hours
    2. abandoned_checkout: status = 'abandoned'
    3. failed_subscription_renewal: is_subscription = 1 AND status = 'failed'
    4. overdue_invoice: channel = 'b2b_invoice' AND status = 'failed' AND age > 7 days
    """
    now = as_of or datetime.now()
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # Clear existing risk flags to maintain run idempotency
    cursor.execute("DELETE FROM risk_flags;")

    cursor.execute("""
        SELECT transaction_id, customer_id, amount, status, failure_code,
               is_subscription, channel, created_at, retry_count
        FROM transactions
    """)
    transactions = cursor.fetchall()

    detected_flags = []
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    for txn in transactions:
        txn_id = txn["transaction_id"]
        status = txn["status"]
        retry_count = txn["retry_count"]
        is_sub = bool(txn["is_subscription"])
        channel = txn["channel"]
        created_at_dt = datetime.strptime(txn["created_at"], "%Y-%m-%d %H:%M:%S")
        age_hours = (now - created_at_dt).total_seconds() / 3600.0
        age_days = age_hours / 24.0

        # Rule 1: Failed payment not retried
        if status == "failed" and retry_count == 0 and age_hours > 24.0:
            detected_flags.append({
                "flag_id": f"flg_{txn_id}_fnr",
                "transaction_id": txn_id,
                "risk_type": RISK_FAILED_NOT_RETRIED,
                "detected_at": now_str
            })

        # Rule 2: Abandoned checkout
        if status == "abandoned":
            detected_flags.append({
                "flag_id": f"flg_{txn_id}_ac",
                "transaction_id": txn_id,
                "risk_type": RISK_ABANDONED_CHECKOUT,
                "detected_at": now_str
            })

        # Rule 3: Failed subscription renewal
        if is_sub and status == "failed":
            detected_flags.append({
                "flag_id": f"flg_{txn_id}_fsr",
                "transaction_id": txn_id,
                "risk_type": RISK_FAILED_SUBSCRIPTION,
                "detected_at": now_str
            })

        # Rule 4: Overdue B2B invoice
        if channel == "b2b_invoice" and status == "failed" and age_days > 7.0:
            detected_flags.append({
                "flag_id": f"flg_{txn_id}_oi",
                "transaction_id": txn_id,
                "risk_type": RISK_OVERDUE_INVOICE,
                "detected_at": now_str
            })

    # Insert into database
    if detected_flags:
        cursor.executemany("""
            INSERT INTO risk_flags (flag_id, transaction_id, risk_type, detected_at)
            VALUES (:flag_id, :transaction_id, :risk_type, :detected_at)
        """, detected_flags)

    conn.commit()
    conn.close()

    return detected_flags

if __name__ == "__main__":
    flags = detect_revenue_at_risk()
    print(f"Detected {len(flags)} risk flags across transactions.")
    from collections import Counter
    counts = Counter(f["risk_type"] for f in flags)
    for risk_type, count in counts.items():
        print(f"  - {risk_type}: {count}")
