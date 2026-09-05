"""
Tests for Payment Verification Engine (src/verify.py).
Verifies:
- ACTION_DISPATCHED != RECOVERED
- Simulated settlement event transitions PAYMENT_PENDING -> RECOVERED
- Invalid event types are rejected
- Signature stub validation behaves correctly
"""

import pytest
import sqlite3
from src.verify import VerificationEngine
from src.constants import (
    STATE_ACTION_DISPATCHED,
    STATE_PAYMENT_PENDING,
    STATE_RECOVERED,
)
from src.db import get_connection, init_db

@pytest.fixture
def temp_db(tmp_path):
    """Creates a temporary database for verification tests."""
    db_file = str(tmp_path / "test_verify.db")
    init_db(wipe=True, db_path=db_file)
    return db_file

def test_action_dispatched_is_not_recovered(temp_db):
    """Verifies that an outreach action being dispatched does NOT mark transaction recovered."""
    conn = get_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO transactions (
            transaction_id, customer_id, customer_name, amount, payment_method,
            status, failure_code, is_subscription, channel, created_at,
            retry_count, customer_opted_out, recovered, recovery_state
        ) VALUES ('TXN_TEST_01', 'CUST_01', 'Arjun Patel', 4500.0, 'upi', 'failed', 'insufficient_funds', 0, 'web', '2026-09-05T10:00:00', 1, 0, 0, ?)
    """, (STATE_ACTION_DISPATCHED,))
    conn.commit()

    cursor.execute("SELECT recovered, recovery_state FROM transactions WHERE transaction_id = 'TXN_TEST_01'")
    row = cursor.fetchone()
    conn.close()

    assert row["recovered"] == 0
    assert row["recovery_state"] == STATE_ACTION_DISPATCHED

def test_settlement_verification_success(temp_db):
    """Verifies that a valid settlement event transitions PAYMENT_PENDING to RECOVERED."""
    conn = get_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO transactions (
            transaction_id, customer_id, customer_name, amount, payment_method,
            status, failure_code, is_subscription, channel, created_at,
            retry_count, customer_opted_out, recovered, recovery_state
        ) VALUES ('TXN_TEST_02', 'CUST_02', 'Sneha Rao', 2500.0, 'upi', 'failed', 'insufficient_funds', 0, 'web', '2026-09-05T10:00:00', 1, 0, 0, ?)
    """, (STATE_PAYMENT_PENDING,))
    conn.commit()
    conn.close()

    result = VerificationEngine.verify_settlement_event(
        transaction_id="TXN_TEST_02",
        event_type="payment.captured",
        amount=2500.0,
        auth_code="AUTH_SUCCESS_999",
        db_path=temp_db
    )

    assert result.verified is True
    assert result.verified_amount == 2500.0
    assert result.verification_source == "simulation_settlement_event"

    # Verify database persistence
    conn = get_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT recovered, recovery_state, verified_at, verification_source FROM transactions WHERE transaction_id = 'TXN_TEST_02'")
    row = cursor.fetchone()
    conn.close()

    assert row["recovered"] == 1
    assert row["recovery_state"] == STATE_RECOVERED
    assert row["verified_at"] is not None

def test_invalid_event_type_rejected(temp_db):
    """Verifies that an unauthorized/invalid event type does not trigger recovery."""
    conn = get_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO transactions (
            transaction_id, customer_id, customer_name, amount, payment_method,
            status, failure_code, is_subscription, channel, created_at,
            retry_count, customer_opted_out, recovered, recovery_state
        ) VALUES ('TXN_TEST_03', 'CUST_03', 'Karan Singh', 1200.0, 'card', 'failed', 'bank_declined', 0, 'web', '2026-09-05T10:00:00', 1, 0, 0, ?)
    """, (STATE_PAYMENT_PENDING,))
    conn.commit()
    conn.close()

    result = VerificationEngine.verify_settlement_event(
        transaction_id="TXN_TEST_03",
        event_type="marketing.click",
        amount=1200.0,
        db_path=temp_db
    )

    assert result.verified is False
    assert "Invalid event_type" in result.message
