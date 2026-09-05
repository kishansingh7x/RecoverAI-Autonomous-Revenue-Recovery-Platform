"""
Unit tests for bounded execution and compliance stopping rules.
Tests PRD Section 6.4 and 6.5:
- Fixed action menu boundaries
- Strict opt-out halting
- Max 3 customer attempts cap
- Silent retry non-incrementing behavior
"""

import pytest
from datetime import datetime, timedelta

from src.db import init_db, get_connection
from src.execute import execute_recovery_actions
from src.constants import (
    FIXED_ACTION_MENU,
    ACTION_STOP_CONTACT,
    ACTION_RETRY_SILENTLY,
    ACTION_SEND_REMINDER_SMS,
    STOPPED_REASON_OPTED_OUT,
    STOPPED_REASON_MAX_ATTEMPTS,
    FAIL_INSUFFICIENT_FUNDS,
    FAIL_GATEWAY_TIMEOUT,
    METHOD_RULE
)

@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_exec.db"
    init_db(db_path=db_file, wipe=True)
    return db_file

def test_opt_out_immediately_halts_action(test_db):
    """If customer_opted_out = 1, executor must halt with stop_contact and no message."""
    conn = get_connection(test_db)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn.execute("""
        INSERT INTO transactions (transaction_id, customer_id, customer_name, amount, payment_method, status, failure_code, is_subscription, channel, created_at, retry_count, customer_opted_out, recovered)
        VALUES ('txn_opted_out', 'cust_01', 'Opted Out User', 1500, 'upi', 'failed', 'insufficient_funds', 0, 'web', ?, 0, 1, 0)
    """, (now_str,))

    conn.execute("""
        INSERT INTO diagnoses (diagnosis_id, transaction_id, root_cause, recommended_action, method, confidence)
        VALUES ('diag_01', 'txn_opted_out', 'Insufficient funds', 'send_reminder_sms', 'rule', 1.0)
    """)
    conn.commit()
    conn.close()

    actions = execute_recovery_actions(db_path=test_db)
    assert len(actions) == 1
    action = actions[0]
    assert action["action_type"] == ACTION_STOP_CONTACT
    assert action["stopped_reason"] == STOPPED_REASON_OPTED_OUT
    assert action["message_sent"] is None

def test_max_attempts_cap_enforced(test_db):
    """When a transaction has 3 customer contact attempts, attempt 4 must force stop_contact."""
    conn = get_connection(test_db)
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    conn.execute("""
        INSERT INTO transactions (transaction_id, customer_id, customer_name, amount, payment_method, status, failure_code, is_subscription, channel, created_at, retry_count, customer_opted_out, recovered)
        VALUES ('txn_maxed', 'cust_02', 'Spam Risk User', 2000, 'card', 'failed', 'insufficient_funds', 0, 'web', ?, 0, 0, 0)
    """, (now_str,))

    conn.execute("""
        INSERT INTO diagnoses (diagnosis_id, transaction_id, root_cause, recommended_action, method, confidence)
        VALUES ('diag_02', 'txn_maxed', 'Insufficient funds', 'send_reminder_sms', 'rule', 1.0)
    """)

    # Populate 3 prior attempts in actions_log
    for i in range(1, 4):
        ts = (now - timedelta(days=4 - i)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("""
            INSERT INTO actions_log (action_id, transaction_id, action_type, reasoning, message_sent, attempt_number, stopped_reason, timestamp)
            VALUES (?, 'txn_maxed', 'send_reminder_sms', 'Attempt', 'Msg', ?, NULL, ?)
        """, (f"act_{i}", i, ts))

    conn.commit()
    conn.close()

    actions = execute_recovery_actions(db_path=test_db)
    assert len(actions) == 1
    action = actions[0]
    assert action["action_type"] == ACTION_STOP_CONTACT
    assert action["stopped_reason"] == STOPPED_REASON_MAX_ATTEMPTS
    assert action["attempt_number"] == 4

def test_silent_retry_does_not_increment_customer_contact_cap(test_db):
    """retry_silently must not increment customer-facing attempt count."""
    conn = get_connection(test_db)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn.execute("""
        INSERT INTO transactions (transaction_id, customer_id, customer_name, amount, payment_method, status, failure_code, is_subscription, channel, created_at, retry_count, customer_opted_out, recovered)
        VALUES ('txn_silent', 'cust_03', 'Tech User', 3000, 'upi', 'failed', 'gateway_timeout', 0, 'web', ?, 0, 0, 0)
    """, (now_str,))

    conn.execute("""
        INSERT INTO diagnoses (diagnosis_id, transaction_id, root_cause, recommended_action, method, confidence)
        VALUES ('diag_03', 'txn_silent', 'Gateway timeout', 'retry_silently', 'rule', 1.0)
    """)
    conn.commit()
    conn.close()

    actions = execute_recovery_actions(db_path=test_db)
    assert len(actions) == 1
    action = actions[0]
    assert action["action_type"] == ACTION_RETRY_SILENTLY
    assert action["attempt_number"] == 0  # Does not increment customer attempt count

def test_fixed_action_menu_compliance(test_db):
    """Every executed action must belong strictly to FIXED_ACTION_MENU."""
    conn = get_connection(test_db)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn.execute("""
        INSERT INTO transactions (transaction_id, customer_id, customer_name, amount, payment_method, status, failure_code, is_subscription, channel, created_at, retry_count, customer_opted_out, recovered)
        VALUES ('txn_menu', 'cust_04', 'Menu Tester', 500, 'upi', 'failed', 'insufficient_funds', 0, 'web', ?, 0, 0, 0)
    """, (now_str,))

    conn.execute("""
        INSERT INTO diagnoses (diagnosis_id, transaction_id, root_cause, recommended_action, method, confidence)
        VALUES ('diag_04', 'txn_menu', 'Insufficient funds', 'send_reminder_sms', 'rule', 1.0)
    """)
    conn.commit()
    conn.close()

    actions = execute_recovery_actions(db_path=test_db)
    for act in actions:
        assert act["action_type"] in FIXED_ACTION_MENU
