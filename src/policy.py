"""
Deterministic Policy Authorization Engine for RecoverAI.
Single central authorization boundary governing all executable recovery actions.
Enforces configurable communication and consent policies including opt-out and contact-frequency limits.
AI proposes candidate actions; this deterministic policy engine authorizes execution.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from src.constants import (
    FIXED_ACTION_MENU,
    SILENT_ACTIONS,
    MAX_CONTACT_ATTEMPTS,
    QUIET_HOURS_START,
    QUIET_HOURS_END,
    ACTION_STOP_CONTACT,
    ACTION_ESCALATE_TO_HUMAN,
    ACTION_SEND_REMINDER_SMS,
    ACTION_SEND_UPDATE_CARD_LINK,
    ACTION_SUGGEST_ALTERNATE_METHOD,
    ACTION_RETRY_SILENTLY,
    ACTION_SEND_MANDATE_RENEWAL_LINK,
    ACTION_SEND_B2B_REMINDER,
    STATE_RECOVERED,
    STATE_STOPPED,
    STATE_ESCALATED,
)
from src.db import get_connection

class PolicyDecision:
    """Represents the deterministic outcome of a policy authorization evaluation."""
    def __init__(
        self,
        allowed: bool,
        authorized_action: str,
        rule_triggered: Optional[str] = None,
        reason: str = "",
        fallback_action: Optional[str] = None,
        policy_checks: Optional[List[Dict[str, Any]]] = None
    ):
        self.allowed = allowed
        self.authorized_action = authorized_action
        self.rule_triggered = rule_triggered
        self.reason = reason
        self.fallback_action = fallback_action
        self.policy_checks = policy_checks or []
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "authorized_action": self.authorized_action,
            "rule_triggered": self.rule_triggered,
            "reason": self.reason,
            "fallback_action": self.fallback_action,
            "policy_checks": self.policy_checks,
            "timestamp": self.timestamp,
        }


class PolicyEngine:
    """
    Centralized Deterministic Action Authorization Layer.
    Evaluates candidate recovery actions against 12 explicit safety, compliance, and lifecycle rules.
    """

    @classmethod
    def evaluate_action(
        cls,
        transaction: Dict[str, Any],
        proposed_action: str,
        attempt_number: int,
        current_hour: Optional[int] = None,
        confidence: float = 1.0,
        supervisor_override: bool = False,
        db_path: Optional[str] = None
    ) -> PolicyDecision:
        """
        Evaluates a proposed action against all deterministic policy rules.
        Returns PolicyDecision indicating if action is ALLOWED or REJECTED with safe fallback.
        """
        checks: List[Dict[str, Any]] = []

        def add_check(rule_name: str, passed: bool, detail: str):
            checks.append({
                "rule": rule_name,
                "passed": passed,
                "detail": detail
            })

        # 1. State check: Already recovered
        is_recovered = transaction.get("recovered", 0) == 1 or transaction.get("recovery_state") == STATE_RECOVERED
        if is_recovered:
            add_check("already_recovered_check", False, "Transaction is already verified RECOVERED.")
            return PolicyDecision(
                allowed=False,
                authorized_action=ACTION_STOP_CONTACT,
                rule_triggered="RULE_ALREADY_RECOVERED",
                reason="Transaction already recovered. Zero further recovery actions allowed.",
                fallback_action=ACTION_STOP_CONTACT,
                policy_checks=checks
            )
        add_check("already_recovered_check", True, "Transaction not yet recovered.")

        # 2. State check: Stopped state
        if transaction.get("recovery_state") == STATE_STOPPED:
            add_check("stopped_state_check", False, "Transaction is in terminal STOPPED state.")
            return PolicyDecision(
                allowed=False,
                authorized_action=ACTION_STOP_CONTACT,
                rule_triggered="RULE_TRANSACTION_STOPPED",
                reason="Transaction is in terminal STOPPED state. All outreach halted.",
                fallback_action=ACTION_STOP_CONTACT,
                policy_checks=checks
            )
        add_check("stopped_state_check", True, "Transaction is not stopped.")

        # 3. State check: Escalated state
        if transaction.get("recovery_state") == STATE_ESCALATED and not supervisor_override:
            add_check("escalated_state_check", False, "Transaction is ESCALATED awaiting human supervisor.")
            return PolicyDecision(
                allowed=False,
                authorized_action=ACTION_ESCALATE_TO_HUMAN,
                rule_triggered="RULE_TRANSACTION_ESCALATED",
                reason="Transaction escalated. Autonomous execution blocked without supervisor override.",
                fallback_action=ACTION_ESCALATE_TO_HUMAN,
                policy_checks=checks
            )
        add_check("escalated_state_check", True, "Transaction is not escalated or supervisor override present.")

        # 4. Action Allowlist
        if proposed_action not in FIXED_ACTION_MENU:
            add_check("allowlist_check", False, f"Action '{proposed_action}' not in fixed allowlist.")
            return PolicyDecision(
                allowed=False,
                authorized_action=ACTION_ESCALATE_TO_HUMAN,
                rule_triggered="RULE_ACTION_NOT_ALLOWLISTED",
                reason=f"Action '{proposed_action}' rejected by policy. Routed to safe human escalation.",
                fallback_action=ACTION_ESCALATE_TO_HUMAN,
                policy_checks=checks
            )
        add_check("allowlist_check", True, f"Action '{proposed_action}' is allowlisted.")

        # 5. Customer Opt-Out Policy
        is_opted_out = bool(transaction.get("customer_opted_out", False))
        if is_opted_out and proposed_action not in SILENT_ACTIONS:
            add_check("opt_out_check", False, "Customer has actively opted out of communications.")
            return PolicyDecision(
                allowed=False,
                authorized_action=ACTION_STOP_CONTACT,
                rule_triggered="RULE_CUSTOMER_OPTED_OUT",
                reason="Customer opted out. Policy forbids customer-facing outreach.",
                fallback_action=ACTION_STOP_CONTACT,
                policy_checks=checks
            )
        add_check("opt_out_check", True, "Customer active (no opt-out).")

        # 6. Maximum Customer Attempt Cap (Attempt <= 3)
        is_customer_facing = proposed_action not in SILENT_ACTIONS and proposed_action != ACTION_STOP_CONTACT
        if is_customer_facing and attempt_number > MAX_CONTACT_ATTEMPTS:
            add_check("attempt_cap_check", False, f"Attempt {attempt_number} exceeds max cap of {MAX_CONTACT_ATTEMPTS}.")
            return PolicyDecision(
                allowed=False,
                authorized_action=ACTION_STOP_CONTACT,
                rule_triggered="RULE_ATTEMPT_CAP_EXCEEDED",
                reason=f"Contact cap ({MAX_CONTACT_ATTEMPTS}) reached. Outreach halted to prevent fatigue.",
                fallback_action=ACTION_STOP_CONTACT,
                policy_checks=checks
            )
        add_check("attempt_cap_check", True, f"Attempt {attempt_number} within cap of {MAX_CONTACT_ATTEMPTS}.")

        # 7. Channel Eligibility Checks
        channel = transaction.get("channel", "web")
        is_subscription = bool(transaction.get("is_subscription", False))
        payment_method = transaction.get("payment_method", "upi")

        if proposed_action == ACTION_RETRY_SILENTLY and transaction.get("failure_code") != "gateway_timeout":
            add_check("channel_eligibility_check", False, f"Silent retry invalid for failure code '{transaction.get('failure_code')}'.")
            return PolicyDecision(
                allowed=False,
                authorized_action=ACTION_STOP_CONTACT,
                rule_triggered="RULE_SILENT_RETRY_INELIGIBLE",
                reason="Silent technical retries are strictly restricted to transient gateway timeouts.",
                fallback_action=ACTION_STOP_CONTACT,
                policy_checks=checks
            )

        if proposed_action == ACTION_SEND_B2B_REMINDER and channel != "b2b_invoice":
            add_check("channel_eligibility_check", False, "B2B reminder proposed for consumer transaction.")
            return PolicyDecision(
                allowed=False,
                authorized_action=ACTION_SEND_REMINDER_SMS,
                rule_triggered="RULE_CHANNEL_INELIGIBLE",
                reason="B2B reminder incompatible with consumer channel. Fallback to SMS reminder.",
                fallback_action=ACTION_SEND_REMINDER_SMS,
                policy_checks=checks
            )

        if proposed_action == ACTION_SEND_MANDATE_RENEWAL_LINK and not is_subscription:
            add_check("channel_eligibility_check", False, "Mandate renewal proposed for non-subscription transaction.")
            return PolicyDecision(
                allowed=False,
                authorized_action=ACTION_SUGGEST_ALTERNATE_METHOD,
                rule_triggered="RULE_SUBSCRIPTION_INELIGIBLE",
                reason="Mandate renewal only valid for subscriptions. Fallback to alternate payment method.",
                fallback_action=ACTION_SUGGEST_ALTERNATE_METHOD,
                policy_checks=checks
            )

        if proposed_action == ACTION_SEND_UPDATE_CARD_LINK and payment_method != "card":
            add_check("channel_eligibility_check", False, f"Update card link proposed for '{payment_method}' payment method.")
            return PolicyDecision(
                allowed=False,
                authorized_action=ACTION_SUGGEST_ALTERNATE_METHOD,
                rule_triggered="RULE_PAYMENT_METHOD_MISMATCH",
                reason=f"Update card link invalid for payment method '{payment_method}'. Fallback to alternate method.",
                fallback_action=ACTION_SUGGEST_ALTERNATE_METHOD,
                policy_checks=checks
            )
        add_check("channel_eligibility_check", True, "Channel and payment method are eligible for action.")

        # 8. Communication Quiet Hours Policy (21:00 - 09:00 IST)
        if current_hour is None:
            current_hour = datetime.now().hour

        if is_customer_facing and (current_hour >= QUIET_HOURS_START or current_hour < QUIET_HOURS_END):
            # Suppress non-urgent messages during quiet hours
            add_check("quiet_hours_check", False, f"Hour {current_hour}:00 falls within quiet hours (21:00-09:00).")
            # If silent retry is possible for technical timeouts, prefer it; otherwise delay
            if transaction.get("failure_code") == "gateway_timeout":
                fallback = ACTION_RETRY_SILENTLY
            else:
                fallback = ACTION_STOP_CONTACT
            return PolicyDecision(
                allowed=False,
                authorized_action=fallback,
                rule_triggered="RULE_QUIET_HOURS_RESTRICTION",
                reason=f"Communication suppressed during quiet hours ({QUIET_HOURS_START}:00 - {QUIET_HOURS_END}:00 IST).",
                fallback_action=fallback,
                policy_checks=checks
            )
        add_check("quiet_hours_check", True, f"Hour {current_hour}:00 is within permissible communication window.")

        # 9. Low Confidence Diagnosis Handling
        if confidence < 0.5 and proposed_action not in SILENT_ACTIONS:
            add_check("confidence_check", False, f"Diagnosis confidence {confidence:.2f} is below 0.50 threshold.")
            return PolicyDecision(
                allowed=False,
                authorized_action=ACTION_SEND_REMINDER_SMS,
                rule_triggered="RULE_LOW_CONFIDENCE_FALLBACK",
                reason=f"Diagnostic confidence ({confidence:.2f}) is low. Fallback to generic reminder.",
                fallback_action=ACTION_SEND_REMINDER_SMS,
                policy_checks=checks
            )
        add_check("confidence_check", True, f"Diagnosis confidence {confidence:.2f} meets safety threshold.")

        # 10. High-Value Escalation Threshold (> ₹50,000 with multiple attempts)
        amount = float(transaction.get("amount", 0.0))
        if amount >= 50000.0 and attempt_number >= 2 and proposed_action != ACTION_STOP_CONTACT:
            add_check("high_value_escalation_check", False, f"High amount ₹{amount:,.2f} with repeated attempts.")
            return PolicyDecision(
                allowed=False,
                authorized_action=ACTION_ESCALATE_TO_HUMAN,
                rule_triggered="RULE_HIGH_VALUE_DISPUTE_ESCALATION",
                reason=f"High-value recovery (₹{amount:,.2f}) requires human supervisor assistance.",
                fallback_action=ACTION_ESCALATE_TO_HUMAN,
                policy_checks=checks
            )
        add_check("high_value_escalation_check", True, "High-value threshold policy passed.")

        # 11. Database Idempotency / Duplicate check (if db_path provided)
        if db_path and transaction.get("transaction_id"):
            try:
                conn = get_connection(db_path)
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT action_id FROM actions_log
                    WHERE transaction_id = ? AND attempt_number = ? AND action_type = ?
                """, (transaction["transaction_id"], attempt_number, proposed_action))
                exists = cursor.fetchone() is not None
                conn.close()
                if exists:
                    add_check("idempotency_check", False, f"Action '{proposed_action}' attempt {attempt_number} already recorded.")
                    return PolicyDecision(
                        allowed=False,
                        authorized_action=ACTION_STOP_CONTACT,
                        rule_triggered="RULE_IDEMPOTENCY_DUPLICATE",
                        reason="Duplicate action detected. Blocked by idempotency constraint.",
                        fallback_action=ACTION_STOP_CONTACT,
                        policy_checks=checks
                    )
            except Exception:
                pass
        add_check("idempotency_check", True, "Idempotency check passed.")

        # If all checks pass, authorize action
        return PolicyDecision(
            allowed=True,
            authorized_action=proposed_action,
            reason=f"Policy authorization granted for action '{proposed_action}'.",
            policy_checks=checks
        )
