"""
Regression tests for idempotency and duplicate messaging bug.
PRD Section 6.9 and Acceptance Criteria:
Re-running the pipeline on the same data does not create duplicate actions.
"""

import pytest
from datetime import datetime

from src.db import init_db, get_connection
from src.execute import execute_recovery_actions
from src.constants import ACTION_SEND_REMINDER_SMS

@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_idempotent.db"
    init_db(db_path=db_file, wipe=True)
    return db_file

def test_re_running_pipeline_does_not_duplicate_actions(test_db):
    """
    Regression test for §6.9 bug:
    First run logs action for attempt 1.
    Second run without new events must produce 0 new actions and not advance attempts.
    """
    conn = get_connection(test_db)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Set up 3 failed transactions
    for i in range(1, 4):
        txn_id = f"txn_{i:03d}"
        conn.execute("""
            INSERT INTO transactions (transaction_id, customer_id, customer_name, amount, payment_method, status, failure_code, is_subscription, channel, created_at, retry_count, customer_opted_out, recovered)
            VALUES (?, 'cust_id', 'Test User', 1000, 'upi', 'failed', 'insufficient_funds', 0, 'web', ?, 0, 0, 0)
        """, (txn_id, now_str))

        conn.execute("""
            INSERT INTO diagnoses (diagnosis_id, transaction_id, root_cause, recommended_action, method, confidence)
            VALUES (?, ?, 'Insufficient funds', 'send_reminder_sms', 'rule', 1.0)
        """, (f"diag_{i}", txn_id))

    conn.commit()
    conn.close()

    # Pass 1: Initial execution
    first_run_actions = execute_recovery_actions(db_path=test_db, check_idempotency=True)
    assert len(first_run_actions) == 3

    # Check database count
    conn = get_connection(test_db)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM actions_log")
    count_after_first = cursor.fetchone()[0]
    assert count_after_first == 3
    conn.close()

    # Pass 2: Re-run on unchanged database state
    second_run_actions = execute_recovery_actions(db_path=test_db, check_idempotency=True)
    assert len(second_run_actions) == 0, "Idempotency violated: duplicate actions created on re-run!"

    # Database count must remain unchanged
    conn = get_connection(test_db)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM actions_log")
    count_after_second = cursor.fetchone()[0]
    conn.close()

    assert count_after_second == count_after_first == 3
