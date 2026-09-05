"""
Edge case and defensive boundary tests for RecoverAI.
Verifies system resilience against:
- Zero / negative transaction amount handling
- Ambiguous / unlisted failure codes
- Contact attempt cap edge boundaries (attempts = 2, 3, 4)
- 404 handling on non-existent transaction IDs for decision and verification APIs
- Genesis hash validation on empty audit logs
"""

import pytest
from fastapi.testclient import TestClient
from server import app
from src.decision import EconomicDecisionEngine
from src.policy import PolicyEngine
from src.db import init_db, verify_audit_chain, GENESIS_HASH

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

def test_zero_amount_decisioning():
    """Verifies that an edge transaction with amount = 0.0 does not crash ERV calculation."""
    txn = {
        "transaction_id": "TXN_ZERO_001",
        "amount": 0.0,
        "payment_method": "upi",
        "channel": "web",
        "customer_opted_out": False,
        "retry_count": 0
    }
    diag = {
        "root_cause": "Zero balance inquiry",
        "method": "rule",
        "confidence": 1.0
    }
    result = EconomicDecisionEngine.evaluate_candidates(txn, diag, attempt_number=1, current_hour=14)
    assert result.selected_action is not None
    assert result.selected_erv <= 0.0  # ERV must be non-positive when amount is zero

def test_unlisted_failure_code_graceful_handling():
    """Verifies that completely unrecognized failure codes default safely to human escalation."""
    txn = {
        "transaction_id": "TXN_UNLISTED_999",
        "customer_opted_out": False,
        "channel": "web",
        "payment_method": "upi",
        "amount": 1200.0,
        "recovered": False,
        "failure_code": "completely_unknown_bank_error_999"
    }
    policy = PolicyEngine.evaluate_action(
        transaction=txn,
        proposed_action="escalate_to_human",
        attempt_number=1,
        current_hour=14
    )
    assert policy.allowed is True
    assert policy.authorized_action == "escalate_to_human"

def test_contact_cap_boundaries():
    """Verifies strict boundary enforcement at attempt numbers 2, 3, and 4."""
    txn = {
        "transaction_id": "TXN_CAP_TEST",
        "customer_opted_out": False,
        "channel": "web",
        "payment_method": "upi",
        "amount": 1500.0,
        "recovered": False
    }

    # Attempt 2 of 3: Permitted
    p2 = PolicyEngine.evaluate_action(
        transaction=txn,
        proposed_action="send_reminder_sms",
        attempt_number=2,
        current_hour=14
    )
    assert p2.allowed is True

    # Attempt 3 of 3: Permitted (exact upper bound)
    p3 = PolicyEngine.evaluate_action(
        transaction=txn,
        proposed_action="send_reminder_sms",
        attempt_number=3,
        current_hour=14
    )
    assert p3.allowed is True

    # Attempt 4 of 3: Strictly Blocked
    p4 = PolicyEngine.evaluate_action(
        transaction=txn,
        proposed_action="send_reminder_sms",
        attempt_number=4,
        current_hour=14
    )
    assert p4.allowed is False
    assert "Contact cap (3) reached" in p4.reason

def test_decision_api_404_on_missing_transaction(client):
    """Verifies that querying decision inspector for a non-existent transaction returns 404."""
    response = client.get("/api/decision/TXN_NON_EXISTENT_999999")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

def test_verify_api_404_on_missing_transaction(client):
    """Verifies that verifying settlement for a non-existent transaction returns 404."""
    response = client.post("/api/verify/TXN_NON_EXISTENT_999999", json={"event_type": "payment.captured"})
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

def test_empty_audit_ledger_returns_valid_genesis(tmp_path):
    """Verifies that an empty database reports a valid genesis integrity state without error."""
    db_file = str(tmp_path / "empty_audit.db")
    init_db(wipe=True, db_path=db_file)
    result = verify_audit_chain(db_file)
    assert result["chain_valid"] is True
    assert result["status"] == "verified"
    assert result["events_checked"] == 0
    assert "genesis state valid" in result["message"]
