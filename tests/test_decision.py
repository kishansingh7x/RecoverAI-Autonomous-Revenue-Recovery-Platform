"""
Tests for Economic Decision Engine (src/decision.py).
Verifies:
- Accurate ERV computation
- Candidate ranking by descending ERV
- Selection of highest policy-authorized action
- Counterfactual analysis generation
- Safe fallback when high-ERV action is policy-disallowed
"""

import pytest
from src.decision import EconomicDecisionEngine
from src.constants import (
    ACTION_SUGGEST_ALTERNATE_METHOD,
    ACTION_SEND_REMINDER_SMS,
    ACTION_RETRY_SILENTLY,
    ACTION_STOP_CONTACT,
)

def test_erv_ranking_and_selection():
    """Verifies that candidate actions are ranked and the highest policy-eligible ERV is chosen."""
    txn = {
        "transaction_id": "TXN_ERV_01",
        "amount": 5000.0,
        "failure_code": "insufficient_funds",
        "channel": "web",
        "payment_method": "upi",
        "customer_opted_out": 0,
        "recovered": 0
    }
    diagnosis = {
        "root_cause": "insufficient_funds",
        "method": "rule",
        "confidence": 1.0
    }

    result = EconomicDecisionEngine.evaluate_candidates(
        transaction=txn,
        diagnosis=diagnosis,
        attempt_number=1,
        current_hour=14
    )

    assert result.selected_action in [ACTION_SUGGEST_ALTERNATE_METHOD, ACTION_SEND_REMINDER_SMS]
    assert result.selected_erv > 0
    assert len(result.counterfactuals) > 1

    # Verify sorting: each candidate's ERV should be <= preceding candidate
    all_ervs = [c.erv for c in result.counterfactuals]
    assert all_ervs == sorted(all_ervs, reverse=True)

    # Verify explanation mentions selected ERV and alternatives
    assert "was selected with the highest expected recovery value" in result.explanation

def test_policy_rejected_high_erv_action_falls_back():
    """Verifies that if an action has high ERV but is policy-rejected, next valid action is selected."""
    # Propose an opted-out customer
    txn = {
        "transaction_id": "TXN_OPTED_OUT_ERV",
        "amount": 10000.0,
        "failure_code": "bank_declined",
        "channel": "web",
        "payment_method": "upi",
        "customer_opted_out": 1,  # Opted out!
        "recovered": 0
    }
    diagnosis = {
        "root_cause": "bank_declined",
        "method": "rule",
        "confidence": 1.0
    }

    result = EconomicDecisionEngine.evaluate_candidates(
        transaction=txn,
        diagnosis=diagnosis,
        attempt_number=1,
        current_hour=14
    )

    # Customer is opted out: customer-facing actions must be rejected, leading to stop_contact
    assert result.selected_action == ACTION_STOP_CONTACT
    assert "Outreach halted" in result.explanation
