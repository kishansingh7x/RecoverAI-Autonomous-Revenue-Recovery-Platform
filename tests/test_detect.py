"""
Unit tests for deterministic risk detection layer.
Tests all four rules defined in PRD Section 6.2.
"""

import pytest
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from src.db import init_db, get_connection
from src.detect import detect_revenue_at_risk
from src.constants import (
    RISK_FAILED_NOT_RETRIED,
    RISK_ABANDONED_CHECKOUT,
    RISK_FAILED_SUBSCRIPTION,
    RISK_OVERDUE_INVOICE,
    FAIL_INSUFFICIENT_FUNDS
)

@pytest.fixture
def test_db(tmp_path):
    """Creates an isolated temporary database for testing."""
    db_file = tmp_path / "test_recovery.db"
    init_db(db_path=db_file, wipe=True)
    return db_file

def test_failed_payment_not_retried_rule(test_db):
    """status = failed AND retry_count = 0 AND age > 24 hours should be flagged."""
    conn = get_connection(test_db)
    now = datetime.now()

    old_failed = (now - timedelta(hours=36)).strftime("%Y-%m-%d %H:%M:%S")
    recent_failed = (now - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")

    conn.executemany("""
        INSERT INTO transactions (transaction_id, customer_id, customer_name, amount, payment_method, status, failure_code, is_subscription, channel, created_at, retry_count, customer_opted_out, recovered)
        VALUES (?, 'cust_01', 'Test Customer', 500, 'upi', ?, ?, 0, 'web', ?, ?, 0, 0)
    """, [
        ("txn_qualifying", "failed", FAIL_INSUFFICIENT_FUNDS, old_failed, 0),
        ("txn_retried", "failed", FAIL_INSUFFICIENT_FUNDS, old_failed, 1),
        ("txn_too_recent", "failed", FAIL_INSUFFICIENT_FUNDS, recent_failed, 0),
        ("txn_success", "success", None, old_failed, 0),
    ])
    conn.commit()
    conn.close()

    flags = detect_revenue_at_risk(db_path=test_db, as_of=now)
    flagged_txns = [f["transaction_id"] for f in flags if f["risk_type"] == RISK_FAILED_NOT_RETRIED]

    assert "txn_qualifying" in flagged_txns
    assert "txn_retried" not in flagged_txns
    assert "txn_too_recent" not in flagged_txns
    assert "txn_success" not in flagged_txns

def test_abandoned_checkout_rule(test_db):
    """status = abandoned should be flagged immediately."""
    conn = get_connection(test_db)
    now = datetime.now()
    created = now.strftime("%Y-%m-%d %H:%M:%S")

    conn.execute("""
        INSERT INTO transactions (transaction_id, customer_id, customer_name, amount, payment_method, status, failure_code, is_subscription, channel, created_at, retry_count, customer_opted_out, recovered)
        VALUES ('txn_abandoned', 'cust_02', 'Abandoner', 1200, 'card', 'abandoned', NULL, 0, 'web', ?, 0, 0, 0)
    """, (created,))
    conn.commit()
    conn.close()

    flags = detect_revenue_at_risk(db_path=test_db, as_of=now)
    flagged_txns = [f["transaction_id"] for f in flags if f["risk_type"] == RISK_ABANDONED_CHECKOUT]

    assert "txn_abandoned" in flagged_txns

def test_failed_subscription_renewal_rule(test_db):
    """is_subscription = 1 AND status = failed should be flagged."""
    conn = get_connection(test_db)
    now = datetime.now()
    created = now.strftime("%Y-%m-%d %H:%M:%S")

    conn.executemany("""
        INSERT INTO transactions (transaction_id, customer_id, customer_name, amount, payment_method, status, failure_code, is_subscription, channel, created_at, retry_count, customer_opted_out, recovered)
        VALUES (?, 'cust_03', 'Sub Customer', 999, 'card', ?, 'mandate_expired', ?, 'app', ?, 0, 0, 0)
    """, [
        ("txn_sub_failed", "failed", 1, created),
        ("txn_sub_success", "success", 1, created),
        ("txn_non_sub_failed", "failed", 0, created),
    ])
    conn.commit()
    conn.close()

    flags = detect_revenue_at_risk(db_path=test_db, as_of=now)
    flagged_txns = [f["transaction_id"] for f in flags if f["risk_type"] == RISK_FAILED_SUBSCRIPTION]

    assert "txn_sub_failed" in flagged_txns
    assert "txn_sub_success" not in flagged_txns
    assert "txn_non_sub_failed" not in flagged_txns

def test_overdue_b2b_invoice_rule(test_db):
    """channel = b2b_invoice AND status = failed AND age > 7 days should be flagged."""
    conn = get_connection(test_db)
    now = datetime.now()

    overdue_dt = (now - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
    recent_dt = (now - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")

    conn.executemany("""
        INSERT INTO transactions (transaction_id, customer_id, customer_name, amount, payment_method, status, failure_code, is_subscription, channel, created_at, retry_count, customer_opted_out, recovered)
        VALUES (?, 'cust_b2b', 'Corp Client', 75000, 'netbanking', ?, NULL, 0, ?, ?, 0, 0, 0)
    """, [
        ("txn_b2b_overdue", "failed", "b2b_invoice", overdue_dt),
        ("txn_b2b_recent", "failed", "b2b_invoice", recent_dt),
        ("txn_web_overdue", "failed", "web", overdue_dt),
    ])
    conn.commit()
    conn.close()

    flags = detect_revenue_at_risk(db_path=test_db, as_of=now)
    flagged_txns = [f["transaction_id"] for f in flags if f["risk_type"] == RISK_OVERDUE_INVOICE]

    assert "txn_b2b_overdue" in flagged_txns
    assert "txn_b2b_recent" not in flagged_txns
    assert "txn_web_overdue" not in flagged_txns
