"""
Promise-to-Pay (PTP) Tracker for RecoverAI.
Simulates customer commitments, fulfillment, and automatic compliant follow-ups.
PRD Section 6.6.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import random
from datetime import datetime, timedelta
from typing import List, Dict, Any

from src.db import get_connection
from src.constants import (
    ACTION_SEND_REMINDER_SMS,
    ACTION_SUGGEST_ALTERNATE_METHOD,
    ACTION_SEND_B2B_REMINDER,
    ACTION_STOP_CONTACT,
    STOPPED_REASON_MAX_ATTEMPTS,
    STOPPED_REASON_OPTED_OUT,
    MAX_CONTACT_ATTEMPTS,
    SILENT_ACTIONS
)
from src.llm_client import generate_recovery_message

ELIGIBLE_PTP_ACTIONS = {
    ACTION_SEND_REMINDER_SMS,
    ACTION_SUGGEST_ALTERNATE_METHOD,
    ACTION_SEND_B2B_REMINDER
}

def process_promises_to_pay(db_path=None, seed: int = 42, as_of: datetime = None) -> Dict[str, Any]:
    """
    1. Identifies transactions that received eligible recovery contact.
    2. Simulates ~40% making a promise to pay (2-10 days out).
    3. For due dates on/before as_of date:
       - ~65% are fulfilled -> mark transaction recovered.
       - ~35% are unfulfilled -> send follow-up reminder if under attempt cap.
    """
    random.seed(seed)
    now = as_of or datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    conn = get_connection(db_path)
    cursor = conn.cursor()

    # Find transactions that received eligible contact actions (one per transaction)
    cursor.execute("""
        SELECT a.transaction_id, a.action_type, MAX(a.timestamp) as timestamp,
               t.customer_name, t.amount, t.channel, t.customer_opted_out
        FROM actions_log a
        JOIN transactions t ON a.transaction_id = t.transaction_id
        WHERE a.action_type IN (?, ?, ?)
          AND a.transaction_id NOT IN (SELECT transaction_id FROM promises_to_pay)
        GROUP BY a.transaction_id
    """, tuple(ELIGIBLE_PTP_ACTIONS))
    eligible_txns = [dict(r) for r in cursor.fetchall()]

    new_promises = []
    for item in eligible_txns:
        # ~40% customer response rate
        if random.random() < 0.40:
            txn_id = item["transaction_id"]
            action_dt = datetime.strptime(item["timestamp"], "%Y-%m-%d %H:%M:%S")

            # Promise date 2 to 10 days after action
            offset_days = random.randint(2, 10)
            promised_dt = action_dt + timedelta(days=offset_days)
            promised_date_str = promised_dt.strftime("%Y-%m-%d")

            # If the promised date is already in the past, evaluate fulfillment
            fulfilled = 0
            if promised_dt <= now:
                # ~65% fulfillment rate
                fulfilled = 1 if random.random() < 0.65 else 0

            new_promises.append({
                "promise_id": f"ptp_{txn_id}",
                "transaction_id": txn_id,
                "promised_date": promised_date_str,
                "fulfilled": fulfilled,
                "follow_up_sent": 0,
                "amount": item["amount"],
                "customer_name": item["customer_name"],
                "channel": item["channel"],
                "opted_out": bool(item["customer_opted_out"]),
                "promised_dt": promised_dt
            })

    # Insert new promises
    for p in new_promises:
        cursor.execute("""
            INSERT INTO promises_to_pay (promise_id, transaction_id, promised_date, fulfilled, follow_up_sent)
            VALUES (?, ?, ?, ?, ?)
        """, (p["promise_id"], p["transaction_id"], p["promised_date"], p["fulfilled"], p["follow_up_sent"]))

        # If fulfilled, mark transaction as recovered
        if p["fulfilled"] == 1:
            cursor.execute("""
                UPDATE transactions
                SET recovered = 1
                WHERE transaction_id = ?
            """, (p["transaction_id"],))

    # Process follow-ups for unfulfilled promises past their due date
    cursor.execute("""
        SELECT p.promise_id, p.transaction_id, p.promised_date, p.fulfilled, p.follow_up_sent,
               t.customer_name, t.amount, t.channel, t.customer_opted_out
        FROM promises_to_pay p
        JOIN transactions t ON p.transaction_id = t.transaction_id
        WHERE p.fulfilled = 0 AND p.follow_up_sent = 0
    """)
    unfulfilled_promises = [dict(r) for r in cursor.fetchall()]

    follow_ups_sent = 0
    for p in unfulfilled_promises:
        promised_dt = datetime.strptime(p["promised_date"], "%Y-%m-%d")
        if promised_dt <= now:
            txn_id = p["transaction_id"]
            is_opted_out = bool(p["customer_opted_out"])

            # Count previous customer-facing attempts
            cursor.execute("""
                SELECT action_id, action_type, attempt_number
                FROM actions_log
                WHERE transaction_id = ?
            """, (txn_id,))
            history = [dict(r) for r in cursor.fetchall()]
            prev_attempts = sum(
                1 for h in history if h["action_type"] not in SILENT_ACTIONS and h["action_type"] != ACTION_STOP_CONTACT
            )

            next_attempt = prev_attempts + 1

            if is_opted_out:
                # Enforce opt out
                cursor.execute("""
                    INSERT INTO actions_log (action_id, transaction_id, action_type, reasoning, message_sent, attempt_number, stopped_reason, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    f"act_{txn_id}_ptp_opt",
                    txn_id,
                    ACTION_STOP_CONTACT,
                    "Customer promised to pay but is opted out of messaging. Halting follow-up outreach.",
                    None,
                    next_attempt,
                    STOPPED_REASON_OPTED_OUT,
                    now_str
                ))
            elif next_attempt > MAX_CONTACT_ATTEMPTS:
                # Enforce max attempts
                cursor.execute("""
                    INSERT INTO actions_log (action_id, transaction_id, action_type, reasoning, message_sent, attempt_number, stopped_reason, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    f"act_{txn_id}_ptp_max",
                    txn_id,
                    ACTION_STOP_CONTACT,
                    f"Unfulfilled promise follow-up exceeded max attempts ({MAX_CONTACT_ATTEMPTS}). Halting outreach.",
                    None,
                    next_attempt,
                    STOPPED_REASON_MAX_ATTEMPTS,
                    now_str
                ))
            else:
                # Send polite follow-up reminder
                cust_name = p["customer_name"]
                amount = p["amount"]
                msg = generate_recovery_message(
                    amount=amount,
                    root_cause=f"Follow-up on promised payment date of {p['promised_date']}",
                    recommended_action=ACTION_SEND_REMINDER_SMS,
                    action_description=f"Reminder regarding payment of ₹{amount:,.0f} promised for {p['promised_date']}.",
                    customer_name=cust_name,
                    tone="friendly Hinglish" if p["channel"] != "b2b_invoice" else "professional"
                )

                reasoning = (
                    f"Promise-to-pay date ({p['promised_date']}) elapsed without payment fulfillment. "
                    f"Sending follow-up reminder. Attempt {next_attempt} of {MAX_CONTACT_ATTEMPTS}."
                )

                cursor.execute("""
                    INSERT INTO actions_log (action_id, transaction_id, action_type, reasoning, message_sent, attempt_number, stopped_reason, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    f"act_{txn_id}_ptp_fup_{next_attempt}",
                    txn_id,
                    ACTION_SEND_REMINDER_SMS,
                    reasoning,
                    msg,
                    next_attempt,
                    None,
                    now_str
                ))
                follow_ups_sent += 1

            # Mark follow_up_sent in promises_to_pay
            cursor.execute("""
                UPDATE promises_to_pay
                SET follow_up_sent = 1
                WHERE promise_id = ?
            """, (p["promise_id"],))

    conn.commit()
    conn.close()

    return {
        "new_promises_count": len(new_promises),
        "fulfilled_count": sum(1 for p in new_promises if p["fulfilled"] == 1),
        "follow_ups_sent": follow_ups_sent
    }

if __name__ == "__main__":
    result = process_promises_to_pay()
    print("Promise-to-pay processing complete:")
    print(f"  - New promises: {result['new_promises_count']}")
    print(f"  - Fulfilled: {result['fulfilled_count']}")
    print(f"  - Follow-ups sent: {result['follow_ups_sent']}")
