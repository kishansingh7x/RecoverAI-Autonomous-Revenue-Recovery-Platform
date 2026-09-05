"""
Bounded Action Execution & Stopping Rules Layer.
Enforces compliance constraints:
- Immediate stop on customer opt-out
- Strict cap of 3 customer-facing contact attempts (stop on attempt 4)
- retry_silently does not count toward customer contact cap
- Complete audit trail logging with explainable reasoning
- Idempotency protection to prevent duplicate messaging
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from src.db import get_connection, compute_event_hash, get_last_audit_hash
from src.constants import (
    FIXED_ACTION_MENU,
    SILENT_ACTIONS,
    ACTION_STOP_CONTACT,
    ACTION_RETRY_SILENTLY,
    ACTION_ESCALATE_TO_HUMAN,
    STOPPED_REASON_OPTED_OUT,
    STOPPED_REASON_MAX_ATTEMPTS,
    STOPPED_REASON_ALREADY_RECOVERED,
    MAX_CONTACT_ATTEMPTS,
    RULE_LOOKUP_TABLE,
    B2B_INVOICE_ACTION
)
from src.llm_client import generate_recovery_message

def execute_recovery_actions(db_path=None, check_idempotency: bool = True) -> List[Dict[str, Any]]:
    """
    Executes bounded recovery actions for all diagnosed transactions.
    Enforces compliance stopping rules, attempt caps, and logs the full audit trail.
    
    If check_idempotency is True, checks whether an action for (transaction_id, attempt_number)
    has already been executed, preventing duplicate customer contact.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # Retrieve all diagnosed transactions with customer and diagnosis details
    cursor.execute("""
        SELECT t.transaction_id, t.customer_id, t.customer_name, t.amount,
               t.payment_method, t.status, t.failure_code, t.is_subscription,
               t.channel, t.created_at, t.retry_count, t.customer_opted_out,
               t.recovered,
               d.diagnosis_id, d.root_cause, d.recommended_action, d.method, d.confidence
        FROM transactions t
        JOIN diagnoses d ON t.transaction_id = d.transaction_id
    """)
    records = [dict(row) for row in cursor.fetchall()]

    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    executed_actions = []

    for rec in records:
        txn_id = rec["transaction_id"]
        is_opted_out = bool(rec["customer_opted_out"])
        is_recovered = bool(rec["recovered"])
        rec_action = rec["recommended_action"]
        root_cause = rec["root_cause"]
        method = rec["method"]
        amount = rec["amount"]
        customer_name = rec["customer_name"]

        # Action timestamp follows transaction creation (e.g. 25 hours after failure)
        created_at_dt = datetime.strptime(rec["created_at"], "%Y-%m-%d %H:%M:%S")
        action_dt = min(created_at_dt + timedelta(hours=25), now)
        action_ts_str = action_dt.strftime("%Y-%m-%d %H:%M:%S")

        # Fetch existing actions history for this transaction
        cursor.execute("""
            SELECT action_id, action_type, attempt_number, stopped_reason
            FROM actions_log
            WHERE transaction_id = ?
            ORDER BY attempt_number ASC, timestamp ASC
        """, (txn_id,))
        history = [dict(r) for r in cursor.fetchall()]

        # Count previous customer-facing contact attempts
        # Silent retries and stop_contact do not increment contact attempts
        customer_facing_attempts = sum(
            1 for h in history if h["action_type"] not in SILENT_ACTIONS and h["action_type"] != ACTION_STOP_CONTACT
        )
        has_stopped = any(h["action_type"] == ACTION_STOP_CONTACT for h in history)

        # Check if already terminated by a prior stop_contact
        if has_stopped:
            continue

        # Check if transaction is already recovered
        if is_recovered:
            action_entry = {
                "action_id": f"act_{txn_id}_rec",
                "transaction_id": txn_id,
                "action_type": ACTION_STOP_CONTACT,
                "reasoning": "Transaction was previously recovered; stopping any further contact.",
                "message_sent": None,
                "attempt_number": len(history),
                "stopped_reason": STOPPED_REASON_ALREADY_RECOVERED,
                "timestamp": action_ts_str
            }
            executed_actions.append(action_entry)
            continue

        # Rule 1: Immediate Opt-Out Stop Check (Compliance Guardrail)
        if is_opted_out:
            attempt_num = customer_facing_attempts + 1
            action_entry = {
                "action_id": f"act_{txn_id}_{attempt_num}_opt",
                "transaction_id": txn_id,
                "action_type": ACTION_STOP_CONTACT,
                "reasoning": f"Customer opted out of notifications (customer_opted_out=True). "
                             f"Compliance rule immediately halts all recovery outreach.",
                "message_sent": None,
                "attempt_number": attempt_num,
                "stopped_reason": STOPPED_REASON_OPTED_OUT,
                "timestamp": action_ts_str
            }
            # Idempotency guard check
            if check_idempotency:
                cursor.execute("""
                    SELECT 1 FROM actions_log 
                    WHERE transaction_id = ? AND attempt_number = ? AND action_type = ?
                """, (txn_id, attempt_num, ACTION_STOP_CONTACT))
                if cursor.fetchone():
                    continue

            executed_actions.append(action_entry)
            continue

        # Rule 2: Max 3 Attempts Cap Check (Attempt Cap Guardrail)
        if customer_facing_attempts >= MAX_CONTACT_ATTEMPTS:
            attempt_num = customer_facing_attempts + 1
            action_entry = {
                "action_id": f"act_{txn_id}_{attempt_num}_max",
                "transaction_id": txn_id,
                "action_type": ACTION_STOP_CONTACT,
                "reasoning": f"Max customer contact attempts ({MAX_CONTACT_ATTEMPTS}) reached. "
                             f"Compliance rule halts outreach to prevent spamming/harassment.",
                "message_sent": None,
                "attempt_number": attempt_num,
                "stopped_reason": STOPPED_REASON_MAX_ATTEMPTS,
                "timestamp": action_ts_str
            }
            if check_idempotency:
                cursor.execute("""
                    SELECT 1 FROM actions_log 
                    WHERE transaction_id = ? AND attempt_number = ? AND action_type = ?
                """, (txn_id, attempt_num, ACTION_STOP_CONTACT))
                if cursor.fetchone():
                    continue

            executed_actions.append(action_entry)
            continue

        # Check if an initial action was already dispatched for this transaction in the current cycle
        if history:
            # If silent retry already logged, skip
            if rec_action in SILENT_ACTIONS and any(h["action_type"] == rec_action for h in history):
                continue
            # If an initial customer-facing action was already taken, do not spontaneously fire attempt 2
            if customer_facing_attempts > 0:
                continue

        # Rule 3: Technical / Silent Retry (Non customer-facing)
        if rec_action in SILENT_ACTIONS:
            # Does not count against customer contact attempt cap
            attempt_num = customer_facing_attempts  # Keep current customer count
            action_entry = {
                "action_id": f"act_{txn_id}_silent_{len(history)+1}",
                "transaction_id": txn_id,
                "action_type": rec_action,
                "reasoning": f"Technical issue ({root_cause}) identified via {method} engine. "
                             f"Executing silent backend retry after 1 hr without customer contact.",
                "message_sent": "[SIMULATED INTERNAL] Gateway retry queued silently; no customer notification sent.",
                "attempt_number": attempt_num,
                "stopped_reason": None,
                "timestamp": action_ts_str
            }
            if check_idempotency:
                cursor.execute("""
                    SELECT 1 FROM actions_log 
                    WHERE transaction_id = ? AND action_type = ?
                """, (txn_id, rec_action))
                if cursor.fetchone():
                    continue

            executed_actions.append(action_entry)
            continue

        # Rule 4: Customer-Facing Recovery Action
        next_attempt = customer_facing_attempts + 1

        # Description for messaging prompt
        action_desc = RULE_LOOKUP_TABLE.get(rec.get("failure_code"), {}).get(
            "action_description",
            f"Please follow the link to complete payment of ₹{amount:,.0f}."
        )

        # Generate personalized copy (English or friendly Hinglish)
        message_copy = generate_recovery_message(
            amount=amount,
            root_cause=root_cause,
            recommended_action=rec_action,
            action_description=action_desc,
            customer_name=customer_name,
            tone="friendly Hinglish" if rec.get("channel") != "b2b_invoice" else "professional"
        )

        reasoning = (
            f"{root_cause} diagnosed via {method} engine. "
            f"Executing bounded action '{rec_action}'. "
            f"Contact attempt {next_attempt} of {MAX_CONTACT_ATTEMPTS}. "
            f"Simulated message generated for customer."
        )

        action_entry = {
            "action_id": f"act_{txn_id}_{next_attempt}",
            "transaction_id": txn_id,
            "action_type": rec_action,
            "reasoning": reasoning,
            "message_sent": message_copy,
            "attempt_number": next_attempt,
            "stopped_reason": None,
            "timestamp": action_ts_str
        }

        # Idempotency check: Don't send double message for the exact same transaction and attempt
        if check_idempotency:
            cursor.execute("""
                SELECT 1 FROM actions_log 
                WHERE transaction_id = ? AND attempt_number = ? AND action_type = ?
            """, (txn_id, next_attempt, rec_action))
            if cursor.fetchone():
                continue

        executed_actions.append(action_entry)

    # Persist executed actions to actions_log with tamper-evident SHA-256 hash chaining
    if executed_actions:
        last_hash = get_last_audit_hash(cursor)
        for act in executed_actions:
            act["previous_hash"] = last_hash
            act["event_hash"] = compute_event_hash(
                timestamp=act["timestamp"],
                transaction_id=act["transaction_id"],
                action_type=act["action_type"],
                reasoning=act["reasoning"],
                attempt_number=act["attempt_number"],
                previous_hash=last_hash
            )
            last_hash = act["event_hash"]

        cursor.executemany("""
            INSERT INTO actions_log (
                action_id, transaction_id, action_type, reasoning, message_sent,
                attempt_number, stopped_reason, timestamp, previous_hash, event_hash
            ) VALUES (
                :action_id, :transaction_id, :action_type, :reasoning, :message_sent,
                :attempt_number, :stopped_reason, :timestamp, :previous_hash, :event_hash
            )
        """, executed_actions)

    conn.commit()
    conn.close()

    return executed_actions

if __name__ == "__main__":
    actions = execute_recovery_actions()
    print(f"Executed {len(actions)} recovery actions.")
    from collections import Counter
    type_counts = Counter(a["action_type"] for a in actions)
    stop_counts = Counter(a["stopped_reason"] for a in actions if a["stopped_reason"])
    print("Action distribution:")
    for a_type, count in type_counts.items():
        print(f"  - {a_type}: {count}")
    print("Stopped reasons:")
    for s_type, count in stop_counts.items():
        print(f"  - {s_type}: {count}")
