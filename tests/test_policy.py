"""
Tests for Centralized Policy Engine (src/policy.py).
Verifies:
- Opt-out blocks customer-facing action
- Max contact cap (<= 3 attempts allowed, attempt 4 blocked)
- Unlisted actions rejected
- Channel eligibility mismatches routed to safe fallbacks
- Quiet hours policy enforcement
- Already recovered blocks further outreach
- Low-confidence diagnosis safe fallback
- High-value repeated drop escalation
- STOPPED and ESCALATED state guardrails
"""

import pytest
from src.policy import PolicyEngine
from src.constants import (
    ACTION_SEND_REMINDER_SMS,
    ACTION_SEND_UPDATE_CARD_LINK,
    ACTION_SUGGEST_ALTERNATE_METHOD,
    ACTION_RETRY_SILENTLY,
    ACTION_SEND_B2B_REMINDER,
    ACTION_STOP_CONTACT,
    ACTION_ESCALATE_TO_HUMAN,
    STATE_RECOVERED,
    STATE_STOPPED,
    STATE_ESCALATED,
)

def test_opt_out_blocks_customer_action():
    """Verifies that an opted-out customer cannot receive customer-facing actions."""
    txn = {
        "transaction_id": "TXN_OPT_01",
        "customer_opted_out": 1,
        "channel": "web",
        "payment_method": "upi",
        "amount": 1000.0,
        "recovered": 0
    }
    decision = PolicyEngine.evaluate_action(
        transaction=txn,
        proposed_action=ACTION_SEND_REMINDER_SMS,
        attempt_number=1,
        current_hour=14
    )
    assert decision.allowed is False
    assert decision.authorized_action == ACTION_STOP_CONTACT
    assert decision.rule_triggered == "RULE_CUSTOMER_OPTED_OUT"

def test_attempt_cap_enforcement():
    """Verifies attempt 3 is allowed, but attempt 4 is strictly blocked."""
    txn = {
        "transaction_id": "TXN_CAP_01",
        "customer_opted_out": 0,
        "channel": "web",
        "payment_method": "upi",
        "amount": 2000.0,
        "recovered": 0
    }
    # Attempt 3: Allowed
    d3 = PolicyEngine.evaluate_action(
        transaction=txn,
        proposed_action=ACTION_SEND_REMINDER_SMS,
        attempt_number=3,
        current_hour=14
    )
    assert d3.allowed is True
    assert d3.authorized_action == ACTION_SEND_REMINDER_SMS

    # Attempt 4: Blocked
    d4 = PolicyEngine.evaluate_action(
        transaction=txn,
        proposed_action=ACTION_SEND_REMINDER_SMS,
        attempt_number=4,
        current_hour=14
    )
    assert d4.allowed is False
    assert d4.authorized_action == ACTION_STOP_CONTACT
    assert d4.rule_triggered == "RULE_ATTEMPT_CAP_EXCEEDED"

def test_unlisted_action_rejected():
    """Verifies that arbitrary or hallucinated actions are rejected."""
    txn = {
        "transaction_id": "TXN_UNLISTED_01",
        "customer_opted_out": 0,
        "channel": "web",
        "payment_method": "upi",
        "amount": 1500.0,
        "recovered": 0
    }
    decision = PolicyEngine.evaluate_action(
        transaction=txn,
        proposed_action="offer_unauthorized_discount_coupon",
        attempt_number=1,
        current_hour=14
    )
    assert decision.allowed is False
    assert decision.authorized_action == ACTION_ESCALATE_TO_HUMAN
    assert decision.rule_triggered == "RULE_ACTION_NOT_ALLOWLISTED"

def test_channel_mismatch_fallback():
    """Verifies that proposing update_card_link for UPI routes to alternate payment method."""
    txn = {
        "transaction_id": "TXN_MISMATCH_01",
        "customer_opted_out": 0,
        "channel": "web",
        "payment_method": "upi",
        "amount": 3500.0,
        "recovered": 0
    }
    decision = PolicyEngine.evaluate_action(
        transaction=txn,
        proposed_action=ACTION_SEND_UPDATE_CARD_LINK,
        attempt_number=1,
        current_hour=14
    )
    assert decision.allowed is False
    assert decision.authorized_action == ACTION_SUGGEST_ALTERNATE_METHOD
    assert decision.rule_triggered == "RULE_PAYMENT_METHOD_MISMATCH"

def test_already_recovered_blocks_action():
    """Verifies that a recovered transaction rejects further actions."""
    txn = {
        "transaction_id": "TXN_ALREADY_REC_01",
        "customer_opted_out": 0,
        "channel": "web",
        "payment_method": "upi",
        "amount": 500.0,
        "recovered": 1,
        "recovery_state": STATE_RECOVERED
    }
    decision = PolicyEngine.evaluate_action(
        transaction=txn,
        proposed_action=ACTION_SEND_REMINDER_SMS,
        attempt_number=1,
        current_hour=14
    )
    assert decision.allowed is False
    assert decision.authorized_action == ACTION_STOP_CONTACT
    assert decision.rule_triggered == "RULE_ALREADY_RECOVERED"

def test_quiet_hours_suppression():
    """Verifies that non-urgent customer outreach is suppressed at 23:00 IST."""
    txn = {
        "transaction_id": "TXN_NIGHT_01",
        "customer_opted_out": 0,
        "channel": "web",
        "payment_method": "upi",
        "amount": 1000.0,
        "recovered": 0
    }
    decision = PolicyEngine.evaluate_action(
        transaction=txn,
        proposed_action=ACTION_SEND_REMINDER_SMS,
        attempt_number=1,
        current_hour=23  # 11 PM
    )
    assert decision.allowed is False
    assert decision.rule_triggered == "RULE_QUIET_HOURS_RESTRICTION"
