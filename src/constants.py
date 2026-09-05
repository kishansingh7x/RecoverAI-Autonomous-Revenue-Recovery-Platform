"""
Constants and fixed lookup tables for RecoverAI.
Guarantees strict bounds and deterministic behavior across detection, diagnosis, and execution.
"""

from typing import Dict, Any, List

# Fixed Action Menu (PRD Section 6.4)
# System strictly forbids actions outside this list.
ACTION_SEND_REMINDER_SMS = "send_reminder_sms"
ACTION_SEND_UPDATE_CARD_LINK = "send_update_card_link"
ACTION_SUGGEST_ALTERNATE_METHOD = "suggest_alternate_payment_method"
ACTION_RETRY_SILENTLY = "retry_silently"
ACTION_SEND_MANDATE_RENEWAL_LINK = "send_mandate_renewal_link"
ACTION_SEND_B2B_REMINDER = "send_b2b_payment_reminder"
ACTION_ESCALATE_TO_HUMAN = "escalate_to_human"
ACTION_STOP_CONTACT = "stop_contact"

FIXED_ACTION_MENU: List[str] = [
    ACTION_SEND_REMINDER_SMS,
    ACTION_SEND_UPDATE_CARD_LINK,
    ACTION_SUGGEST_ALTERNATE_METHOD,
    ACTION_RETRY_SILENTLY,
    ACTION_SEND_MANDATE_RENEWAL_LINK,
    ACTION_SEND_B2B_REMINDER,
    ACTION_ESCALATE_TO_HUMAN,
    ACTION_STOP_CONTACT,
]

# Actions that are technical/silent and do not increment customer-facing contact count
SILENT_ACTIONS = {
    ACTION_RETRY_SILENTLY,
}

# Recovery State Machine States (Closed-Loop Lifecycle)
STATE_FAILED = "FAILED"
STATE_RISK_FLAGGED = "RISK_FLAGGED"
STATE_DIAGNOSED = "DIAGNOSED"
STATE_ACTION_SELECTED = "ACTION_SELECTED"
STATE_ACTION_DISPATCHED = "ACTION_DISPATCHED"
STATE_PAYMENT_PENDING = "PAYMENT_PENDING"
STATE_RECOVERED = "RECOVERED"
STATE_FOLLOW_UP_ELIGIBLE = "FOLLOW_UP_ELIGIBLE"
STATE_STOPPED = "STOPPED"
STATE_ESCALATED = "ESCALATED"

ALL_RECOVERY_STATES: List[str] = [
    STATE_FAILED,
    STATE_RISK_FLAGGED,
    STATE_DIAGNOSED,
    STATE_ACTION_SELECTED,
    STATE_ACTION_DISPATCHED,
    STATE_PAYMENT_PENDING,
    STATE_RECOVERED,
    STATE_FOLLOW_UP_ELIGIBLE,
    STATE_STOPPED,
    STATE_ESCALATED,
]

# Configurable Simulation Economic Model
# Note: These represent modeled recovery cost assumptions for comparative benchmarking,
# not fixed actual provider billing statements.
SIMULATION_SMS_COST_INR: float = 0.25
SIMULATION_WHATSAPP_COST_INR: float = 0.50
SIMULATION_RETRY_COST_INR: float = 0.10
SIMULATION_LLM_COST_INR: float = 0.04
SIMULATION_ESCALATION_COST_INR: float = 15.00

SIMULATION_ECONOMIC_MODEL: Dict[str, Any] = {
    "type": "simulation_assumptions",
    "description": "Configurable simulation assumptions used for comparative economic evaluation",
    "sms_cost_inr": SIMULATION_SMS_COST_INR,
    "whatsapp_cost_inr": SIMULATION_WHATSAPP_COST_INR,
    "retry_cost_inr": SIMULATION_RETRY_COST_INR,
    "llm_cost_inr": SIMULATION_LLM_COST_INR,
    "escalation_cost_inr": SIMULATION_ESCALATION_COST_INR,
}

# Modeled Action Costs in INR (Configurable simulation assumptions)
ACTION_COSTS: Dict[str, float] = {
    ACTION_SEND_REMINDER_SMS: SIMULATION_SMS_COST_INR,
    ACTION_SEND_UPDATE_CARD_LINK: SIMULATION_WHATSAPP_COST_INR,
    ACTION_SUGGEST_ALTERNATE_METHOD: 0.35,
    ACTION_RETRY_SILENTLY: SIMULATION_RETRY_COST_INR,
    ACTION_SEND_MANDATE_RENEWAL_LINK: SIMULATION_WHATSAPP_COST_INR,
    ACTION_SEND_B2B_REMINDER: 1.00,
    ACTION_ESCALATE_TO_HUMAN: SIMULATION_ESCALATION_COST_INR,
    ACTION_STOP_CONTACT: 0.00,
}

# Customer Friction Penalty in INR (fatigue / unsubscribe risk penalty)
CUSTOMER_FRICTION_BASE: Dict[str, float] = {
    ACTION_SEND_REMINDER_SMS: 2.00,
    ACTION_SEND_UPDATE_CARD_LINK: 1.50,
    ACTION_SUGGEST_ALTERNATE_METHOD: 2.50,
    ACTION_RETRY_SILENTLY: 0.00,
    ACTION_SEND_MANDATE_RENEWAL_LINK: 2.00,
    ACTION_SEND_B2B_REMINDER: 3.00,
    ACTION_ESCALATE_TO_HUMAN: 0.00,
    ACTION_STOP_CONTACT: 0.00,
}

# LLM Inference Cost per Call in INR (Configurable simulation assumption)
LLM_INFERENCE_COST_INR = SIMULATION_LLM_COST_INR

# Communication Policy Window (Quiet Hours: 21:00 - 09:00 IST)
QUIET_HOURS_START = 21
QUIET_HOURS_END = 9

# Terminal states / Stop conditions
STOPPED_REASON_MAX_ATTEMPTS = "max_attempts_reached"
STOPPED_REASON_OPTED_OUT = "customer_opted_out"
STOPPED_REASON_ALREADY_RECOVERED = "already_recovered"
STOPPED_REASON_QUIET_HOURS = "quiet_hours_restriction"
STOPPED_REASON_POLICY_VIOLATION = "policy_violation"

# Attempt Caps
MAX_CONTACT_ATTEMPTS = 3

# Risk Flag Types (PRD Section 6.2)
RISK_FAILED_NOT_RETRIED = "failed_payment_not_retried"
RISK_ABANDONED_CHECKOUT = "abandoned_checkout"
RISK_FAILED_SUBSCRIPTION = "failed_subscription_renewal"
RISK_OVERDUE_INVOICE = "overdue_invoice"

VALID_RISK_TYPES = [
    RISK_FAILED_NOT_RETRIED,
    RISK_ABANDONED_CHECKOUT,
    RISK_FAILED_SUBSCRIPTION,
    RISK_OVERDUE_INVOICE,
]

# Failure Codes (PRD Section 5 / 6.1)
FAIL_INSUFFICIENT_FUNDS = "insufficient_funds"
FAIL_BANK_DECLINED = "bank_declined"
FAIL_GATEWAY_TIMEOUT = "gateway_timeout"
FAIL_CARD_EXPIRED = "card_expired"
FAIL_OTP_TIMEOUT = "otp_timeout"
FAIL_MANDATE_EXPIRED = "mandate_expired"

# Deterministic Lookup Table (Failure Code -> Root Cause & Recommended Action)
# PRD Section 6.3 - Resolves >=80% of transactions deterministically
RULE_LOOKUP_TABLE: Dict[str, Dict[str, str]] = {
    FAIL_INSUFFICIENT_FUNDS: {
        "root_cause": "Customer bank account had insufficient funds to complete transaction.",
        "recommended_action": ACTION_SEND_REMINDER_SMS,
        "action_description": "Schedule a friendly payment reminder SMS in 2 days allowing customer to top up account."
    },
    FAIL_BANK_DECLINED: {
        "root_cause": "Issuing bank declined the transaction due to temporary limit or internal risk policy.",
        "recommended_action": ACTION_SUGGEST_ALTERNATE_METHOD,
        "action_description": "Notify customer of bank decline and provide a one-click link to pay with UPI or another card."
    },
    FAIL_GATEWAY_TIMEOUT: {
        "root_cause": "Network latency or gateway timeout occurred between payment aggregator and bank switch.",
        "recommended_action": ACTION_RETRY_SILENTLY,
        "action_description": "Execute silent background retry after 1 hour without bothering the customer."
    },
    FAIL_CARD_EXPIRED: {
        "root_cause": "Card expiration date has passed or card validity expired.",
        "recommended_action": ACTION_SEND_UPDATE_CARD_LINK,
        "action_description": "Send a secure link for customer to update card credentials or switch payment method."
    },
    FAIL_OTP_TIMEOUT: {
        "root_cause": "Two-factor authentication / OTP expired before customer entered it.",
        "recommended_action": ACTION_RETRY_SILENTLY,
        "action_description": "Silent technical retry attempt once after 1 hour."
    },
    FAIL_MANDATE_EXPIRED: {
        "root_cause": "Recurring subscription e-mandate has expired or was revoked.",
        "recommended_action": ACTION_SEND_MANDATE_RENEWAL_LINK,
        "action_description": "Send customer an instant recurring mandate re-authorization link."
    },
}

# Special rule for B2B invoices
B2B_INVOICE_ACTION = ACTION_SEND_B2B_REMINDER
B2B_INVOICE_ROOT_CAUSE = "B2B commercial invoice payment is overdue past payment terms."

# Methods
METHOD_RULE = "rule"
METHOD_LLM_FALLBACK = "llm_fallback"
