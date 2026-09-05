"""
Database schema and connection management for RecoverAI.
Uses SQLite for zero-dependency local storage with full auditability.
"""

import sqlite3
import os
from pathlib import Path

def get_default_db_path() -> Path:
    """Returns the appropriate SQLite DB path, using /tmp on Vercel/serverless environments."""
    if os.getenv("VERCEL"):
        return Path("/tmp/recovery.db")
    return Path(__file__).resolve().parent.parent / "recovery.db"

DEFAULT_DB_PATH = get_default_db_path()

def get_connection(db_path=None):
    """Returns a sqlite3 connection with Row factory enabled."""
    target_path = Path(db_path) if db_path else DEFAULT_DB_PATH
    if os.getenv("VERCEL") and not target_path.exists():
        target_path.parent.mkdir(parents=True, exist_ok=True)
        ensure_db_schema(target_path)
    conn = sqlite3.connect(target_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

import hashlib
from typing import Dict, Any, Optional

GENESIS_HASH = "0" * 64

def compute_event_hash(
    timestamp: str,
    transaction_id: str,
    action_type: str,
    reasoning: str,
    attempt_number: int,
    previous_hash: Optional[str]
) -> str:
    """
    Computes a canonical SHA-256 hash for a tamper-evident audit ledger entry.
    Canonical format: timestamp|transaction_id|action_type|reasoning|attempt_number|previous_hash
    Links each event cryptographically to the preceding event hash.
    """
    prev = previous_hash or GENESIS_HASH
    payload = f"{timestamp}|{transaction_id}|{action_type}|{reasoning or ''}|{attempt_number}|{prev}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def get_last_audit_hash(cursor) -> str:
    """Returns the event_hash of the most recently inserted audit entry, or GENESIS_HASH."""
    cursor.execute("SELECT event_hash FROM actions_log WHERE event_hash IS NOT NULL ORDER BY rowid DESC LIMIT 1")
    row = cursor.fetchone()
    if row and row["event_hash"]:
        return row["event_hash"]
    return GENESIS_HASH

def verify_audit_chain(db_path=None) -> Dict[str, Any]:
    """
    Verifies the tamper-evident append-only SHA-256 audit ledger.
    Measures and reports verification runtime.
    Checks:
    1. Every record's previous_hash correctly references the preceding record's event_hash.
    2. Recalculated canonical SHA-256 hash matches the stored event_hash exactly.
    """
    import time
    from datetime import datetime, timezone
    start_time = time.perf_counter()

    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT action_id, transaction_id, action_type, reasoning, message_sent,
               attempt_number, stopped_reason, timestamp, previous_hash, event_hash
        FROM actions_log
        ORDER BY rowid ASC
    """)
    rows = cursor.fetchall()
    conn.close()

    elapsed_ms = (time.perf_counter() - start_time) * 1000.0
    now_iso = datetime.now(timezone.utc).isoformat()

    if not rows:
        return {
            "status": "verified",
            "events_checked": 0,
            "chain_valid": True,
            "first_invalid_event": None,
            "verification_timestamp": now_iso,
            "measured_runtime_ms": round(elapsed_ms, 2),
            "message": "Audit ledger is empty; genesis state valid."
        }

    expected_prev = GENESIS_HASH
    checked_count = 0

    for idx, row in enumerate(rows):
        action_id = row["action_id"]
        stored_prev = row["previous_hash"]
        stored_event = row["event_hash"]

        # If hashes are not populated yet
        if not stored_event:
            return {
                "status": "compromised",
                "events_checked": checked_count,
                "chain_valid": False,
                "first_invalid_event": {
                    "index": idx,
                    "action_id": action_id,
                    "transaction_id": row["transaction_id"],
                    "error": "Missing event_hash"
                },
                "verification_timestamp": now_iso,
                "measured_runtime_ms": round(elapsed_ms, 2),
                "message": f"Integrity check failed: missing hash at event {idx+1}."
            }

        # Check chain link
        if stored_prev != expected_prev:
            return {
                "status": "compromised",
                "events_checked": checked_count,
                "chain_valid": False,
                "first_invalid_event": {
                    "index": idx,
                    "action_id": action_id,
                    "transaction_id": row["transaction_id"],
                    "error": f"Previous hash mismatch (expected {expected_prev[:12]}..., found {stored_prev[:12] if stored_prev else 'None'}...)"
                },
                "verification_timestamp": now_iso,
                "measured_runtime_ms": round(elapsed_ms, 2),
                "message": f"Integrity check failed: broken previous_hash link at event {idx+1}."
            }

        # Recalculate hash
        recalc = compute_event_hash(
            timestamp=row["timestamp"],
            transaction_id=row["transaction_id"],
            action_type=row["action_type"],
            reasoning=row["reasoning"],
            attempt_number=row["attempt_number"],
            previous_hash=stored_prev
        )

        if recalc != stored_event:
            return {
                "status": "compromised",
                "events_checked": checked_count,
                "chain_valid": False,
                "first_invalid_event": {
                    "index": idx,
                    "action_id": action_id,
                    "transaction_id": row["transaction_id"],
                    "error": f"Hash recalculation mismatch (stored {stored_event[:12]}..., computed {recalc[:12]}...)"
                },
                "verification_timestamp": now_iso,
                "measured_runtime_ms": round(elapsed_ms, 2),
                "message": f"Integrity check failed: tampering detected at record {action_id}."
            }

        expected_prev = stored_event
        checked_count += 1

    total_elapsed_ms = (time.perf_counter() - start_time) * 1000.0

    return {
        "status": "verified",
        "events_checked": checked_count,
        "chain_valid": True,
        "first_invalid_event": None,
        "latest_hash": expected_prev,
        "verification_timestamp": now_iso,
        "measured_runtime_ms": round(total_elapsed_ms, 2),
        "message": f"Successfully verified {checked_count} consecutive audit records without tampering."
    }

def init_db(db_path=None, wipe=False):
    """
    Initializes database tables.
    If wipe=True, drops all tables and rebuilds fresh schema.
    """
    conn = get_connection(db_path)
    cursor = conn.cursor()

    if wipe:
        cursor.executescript("""
            DROP TABLE IF EXISTS promises_to_pay;
            DROP TABLE IF EXISTS actions_log;
            DROP TABLE IF EXISTS diagnoses;
            DROP TABLE IF EXISTS risk_flags;
            DROP TABLE IF EXISTS transactions;
            DROP TABLE IF EXISTS support_callbacks;
        """)

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS transactions (
            transaction_id TEXT PRIMARY KEY,
            customer_id TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            amount REAL NOT NULL,
            payment_method TEXT NOT NULL,
            status TEXT NOT NULL, -- 'success', 'failed', 'abandoned'
            failure_code TEXT,    -- nullable
            is_subscription BOOLEAN NOT NULL DEFAULT 0,
            channel TEXT NOT NULL, -- 'web', 'app', 'b2b_invoice'
            created_at DATETIME NOT NULL,
            retry_count INTEGER NOT NULL DEFAULT 0,
            customer_opted_out BOOLEAN NOT NULL DEFAULT 0,
            recovered BOOLEAN NOT NULL DEFAULT 0,
            recovery_state TEXT NOT NULL DEFAULT 'FAILED',
            verified_at DATETIME,
            verification_source TEXT
        );

        CREATE TABLE IF NOT EXISTS risk_flags (
            flag_id TEXT PRIMARY KEY,
            transaction_id TEXT NOT NULL,
            risk_type TEXT NOT NULL,
            detected_at DATETIME NOT NULL,
            FOREIGN KEY (transaction_id) REFERENCES transactions (transaction_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS diagnoses (
            diagnosis_id TEXT PRIMARY KEY,
            transaction_id TEXT NOT NULL,
            root_cause TEXT NOT NULL,
            recommended_action TEXT NOT NULL,
            method TEXT NOT NULL, -- 'rule' or 'llm_fallback'
            confidence REAL NOT NULL DEFAULT 1.0,
            FOREIGN KEY (transaction_id) REFERENCES transactions (transaction_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS actions_log (
            action_id TEXT PRIMARY KEY,
            transaction_id TEXT NOT NULL,
            action_type TEXT NOT NULL,
            reasoning TEXT NOT NULL,
            message_sent TEXT,
            attempt_number INTEGER NOT NULL,
            stopped_reason TEXT, -- 'max_attempts_reached', 'customer_opted_out', null
            timestamp DATETIME NOT NULL,
            previous_hash TEXT,
            event_hash TEXT,
            FOREIGN KEY (transaction_id) REFERENCES transactions (transaction_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS promises_to_pay (
            promise_id TEXT PRIMARY KEY,
            transaction_id TEXT NOT NULL,
            promised_date DATE NOT NULL,
            fulfilled BOOLEAN NOT NULL DEFAULT 0,
            follow_up_sent BOOLEAN NOT NULL DEFAULT 0,
            FOREIGN KEY (transaction_id) REFERENCES transactions (transaction_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS support_callbacks (
            ticket_id TEXT PRIMARY KEY,
            customer_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            transaction_id TEXT,
            preferred_slot TEXT NOT NULL,
            issue_summary TEXT,
            status TEXT NOT NULL DEFAULT 'queued',
            created_at DATETIME NOT NULL
        );
    """)

    create_indices(cursor)
    conn.commit()
    conn.close()

def create_indices(cursor):
    """Creates database indices safely after all tables and columns exist."""
    indices = [
        "CREATE INDEX IF NOT EXISTS idx_txn_status ON transactions(status);",
        "CREATE INDEX IF NOT EXISTS idx_txn_created ON transactions(created_at);",
        "CREATE INDEX IF NOT EXISTS idx_txn_state ON transactions(recovery_state);",
        "CREATE INDEX IF NOT EXISTS idx_flags_txn ON risk_flags(transaction_id);",
        "CREATE INDEX IF NOT EXISTS idx_diag_txn ON diagnoses(transaction_id);",
        "CREATE INDEX IF NOT EXISTS idx_actions_txn ON actions_log(transaction_id);",
        "CREATE INDEX IF NOT EXISTS idx_actions_hash ON actions_log(event_hash);",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_actions_idempotency ON actions_log(transaction_id, attempt_number, action_type);",
        "CREATE INDEX IF NOT EXISTS idx_ptp_txn ON promises_to_pay(transaction_id);",
        "CREATE INDEX IF NOT EXISTS idx_callbacks_created ON support_callbacks(created_at);"
    ]
    for idx_sql in indices:
        try:
            cursor.execute(idx_sql)
        except Exception:
            pass

def create_support_callback(
    ticket_id: str,
    customer_name: str,
    phone: str,
    transaction_id: str = None,
    preferred_slot: str = "Immediate",
    issue_summary: str = None,
    db_path=None
) -> dict:
    """Inserts a new support callback request into the database."""
    from datetime import datetime, timezone
    conn = get_connection(db_path)
    cursor = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    cursor.execute("""
        INSERT INTO support_callbacks (
            ticket_id, customer_name, phone, transaction_id, preferred_slot, issue_summary, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)
    """, (
        ticket_id,
        customer_name,
        phone,
        transaction_id,
        preferred_slot,
        issue_summary,
        now_iso
    ))
    conn.commit()
    conn.close()
    return {
        "ticket_id": ticket_id,
        "customer_name": customer_name,
        "phone": phone,
        "transaction_id": transaction_id,
        "preferred_slot": preferred_slot,
        "issue_summary": issue_summary,
        "status": "queued",
        "created_at": now_iso
    }

def get_support_callbacks(limit: int = 20, db_path=None) -> list:
    """Retrieves recent support callback requests."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ticket_id, customer_name, phone, transaction_id, preferred_slot, issue_summary, status, created_at
        FROM support_callbacks
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def ensure_db_schema(db_path=None):
    """Ensures all tables and migration columns exist without wiping existing data."""
    conn = get_connection(db_path)
    cursor = conn.cursor()

    # Create tables if not exist
    init_db(db_path=db_path, wipe=False)

    # Migrate transactions table if missing recovery_state or verification fields
    cursor.execute("PRAGMA table_info(transactions);")
    columns = [row["name"] for row in cursor.fetchall()]
    if "recovery_state" not in columns:
        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN recovery_state TEXT NOT NULL DEFAULT 'FAILED'")
        except Exception:
            pass
    if "verified_at" not in columns:
        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN verified_at DATETIME")
        except Exception:
            pass
    if "verification_source" not in columns:
        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN verification_source TEXT")
        except Exception:
            pass

    # Migrate actions_log table if missing hash columns
    cursor.execute("PRAGMA table_info(actions_log);")
    action_columns = [row["name"] for row in cursor.fetchall()]
    if "previous_hash" not in action_columns:
        try:
            cursor.execute("ALTER TABLE actions_log ADD COLUMN previous_hash TEXT")
        except Exception:
            pass
    if "event_hash" not in action_columns:
        try:
            cursor.execute("ALTER TABLE actions_log ADD COLUMN event_hash TEXT")
        except Exception:
            pass

    # Safely create all indices now that all columns exist
    create_indices(cursor)

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db(wipe=True)
    print("Database initialized successfully at", DEFAULT_DB_PATH)
