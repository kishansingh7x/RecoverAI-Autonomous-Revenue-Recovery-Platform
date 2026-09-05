"""
Tests for Tamper-Evident SHA-256 Audit Chain (src/db.py).
Verifies:
- Linear valid hash chain passes verification
- Tampering with an audit record payload causes verification failure and detects exact row
- Corrupted previous_hash causes verification failure
- Measured runtime is reported
"""

import pytest
from src.db import (
    get_connection,
    init_db,
    compute_event_hash,
    verify_audit_chain,
    GENESIS_HASH
)

@pytest.fixture
def audit_db(tmp_path):
    """Creates a fresh test database with schema initialized."""
    db_file = str(tmp_path / "test_audit.db")
    init_db(wipe=True, db_path=db_file)
    return db_file

def test_valid_hash_chain_passes(audit_db):
    """Verifies that sequentially chained records produce a valid integrity report."""
    conn = get_connection(audit_db)
    cursor = conn.cursor()

    # Create dummy transaction
    cursor.execute("""
        INSERT INTO transactions (
            transaction_id, customer_id, customer_name, amount, payment_method,
            status, channel, created_at
        ) VALUES ('TXN_AUDIT_01', 'CUST_01', 'Vikram Mehra', 3200.0, 'upi', 'failed', 'web', '2026-09-05T10:00:00')
    """)

    # Insert 5 sequentially chained actions
    prev_hash = GENESIS_HASH
    for i in range(1, 6):
        action_id = f"act_audit_{i}"
        action_type = "send_reminder_sms" if i % 2 == 1 else "suggest_alternate_payment_method"
        reasoning = f"Reasoning for event {i}"
        ts = f"2026-09-05T10:0{i}:00"
        event_hash = compute_event_hash(ts, "TXN_AUDIT_01", action_type, reasoning, i, prev_hash)

        cursor.execute("""
            INSERT INTO actions_log (
                action_id, transaction_id, action_type, reasoning, attempt_number,
                timestamp, previous_hash, event_hash
            ) VALUES (?, 'TXN_AUDIT_01', ?, ?, ?, ?, ?, ?)
        """, (action_id, action_type, reasoning, i, ts, prev_hash, event_hash))

        prev_hash = event_hash

    conn.commit()
    conn.close()

    result = verify_audit_chain(audit_db)
    assert result["chain_valid"] is True
    assert result["events_checked"] == 5
    assert result["first_invalid_event"] is None
    assert result["measured_runtime_ms"] >= 0.0

def test_tampered_payload_detected(audit_db):
    """Verifies that modifying reasoning or action in an existing audit row triggers tamper detection."""
    conn = get_connection(audit_db)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO transactions (
            transaction_id, customer_id, customer_name, amount, payment_method,
            status, channel, created_at
        ) VALUES ('TXN_AUDIT_02', 'CUST_02', 'Ananya Roy', 4500.0, 'card', 'failed', 'web', '2026-09-05T10:00:00')
    """)

    # Insert 3 chained records
    prev_hash = GENESIS_HASH
    for i in range(1, 4):
        action_id = f"act_tamper_{i}"
        action_type = "send_reminder_sms"
        reasoning = f"Original reasoning {i}"
        ts = f"2026-09-05T11:0{i}:00"
        event_hash = compute_event_hash(ts, "TXN_AUDIT_02", action_type, reasoning, i, prev_hash)

        cursor.execute("""
            INSERT INTO actions_log (
                action_id, transaction_id, action_type, reasoning, attempt_number,
                timestamp, previous_hash, event_hash
            ) VALUES (?, 'TXN_AUDIT_02', ?, ?, ?, ?, ?, ?)
        """, (action_id, action_type, reasoning, i, ts, prev_hash, event_hash))
        prev_hash = event_hash

    conn.commit()

    # Intentionally tamper with record 2: modify the reasoning directly in SQLite
    cursor.execute("""
        UPDATE actions_log
        SET reasoning = 'MALICIOUS_UNAUTHORIZED_EDIT'
        WHERE action_id = 'act_tamper_2'
    """)
    conn.commit()
    conn.close()

    result = verify_audit_chain(audit_db)
    assert result["chain_valid"] is False
    assert result["status"] == "compromised"
    assert result["first_invalid_event"] is not None
    assert result["first_invalid_event"]["action_id"] == "act_tamper_2"
    assert "tampering detected" in result["message"].lower()

def test_broken_hash_link_detected(audit_db):
    """Verifies that an altered previous_hash triggers link mismatch detection."""
    conn = get_connection(audit_db)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO transactions (
            transaction_id, customer_id, customer_name, amount, payment_method,
            status, channel, created_at
        ) VALUES ('TXN_AUDIT_03', 'CUST_03', 'Rajesh Gupta', 1200.0, 'upi', 'failed', 'web', '2026-09-05T10:00:00')
    """)

    prev_hash = GENESIS_HASH
    for i in range(1, 3):
        action_id = f"act_link_{i}"
        ts = f"2026-09-05T12:0{i}:00"
        event_hash = compute_event_hash(ts, "TXN_AUDIT_03", "send_reminder_sms", "reason", i, prev_hash)

        cursor.execute("""
            INSERT INTO actions_log (
                action_id, transaction_id, action_type, reasoning, attempt_number,
                timestamp, previous_hash, event_hash
            ) VALUES (?, 'TXN_AUDIT_03', 'send_reminder_sms', 'reason', ?, ?, ?, ?)
        """, (action_id, i, ts, prev_hash, event_hash))
        prev_hash = event_hash

    conn.commit()

    # Alter previous_hash of record 2
    cursor.execute("UPDATE actions_log SET previous_hash = 'corrupted_hash_value' WHERE action_id = 'act_link_2'")
    conn.commit()
    conn.close()

    result = verify_audit_chain(audit_db)
    assert result["chain_valid"] is False
    assert result["first_invalid_event"]["action_id"] == "act_link_2"
    assert "broken previous_hash" in result["message"].lower()
