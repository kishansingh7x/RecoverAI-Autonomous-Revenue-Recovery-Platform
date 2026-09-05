"""
Expected Recovery Value (ERV) and Counterfactual Decisioning Engine for RecoverAI.
Implements:
- Mathematical ERV computation:
  ERV(a) = P(rec|context, a) * amount - cost(a) - friction(a) - escalation_risk(a)
- Multi-candidate action generation from FIXED_ACTION_MENU
- Policy-gated selection: Ranks by ERV, selects the highest policy-authorized action
- Counterfactual explanation generation (Selected vs. Alternatives)
- Strict boundary: AI assists reasoning; this engine mathematically optimizes and policy authorizes.
"""

from typing import Dict, Any, List, Optional
import math

from src.constants import (
    FIXED_ACTION_MENU,
    SILENT_ACTIONS,
    ACTION_COSTS,
    CUSTOMER_FRICTION_BASE,
    ACTION_SEND_REMINDER_SMS,
    ACTION_SEND_UPDATE_CARD_LINK,
    ACTION_SUGGEST_ALTERNATE_METHOD,
    ACTION_RETRY_SILENTLY,
    ACTION_SEND_MANDATE_RENEWAL_LINK,
    ACTION_SEND_B2B_REMINDER,
    ACTION_ESCALATE_TO_HUMAN,
    ACTION_STOP_CONTACT,
)
from src.policy import PolicyEngine, PolicyDecision

class CandidateAction:
    """Represents a candidate recovery action evaluated by ERV."""
    def __init__(
        self,
        action: str,
        success_probability: float,
        amount: float,
        modeled_cost: float,
        friction_cost: float,
        escalation_risk: float,
        policy_decision: Optional[PolicyDecision] = None
    ):
        self.action = action
        self.success_probability = max(0.0, min(1.0, success_probability))
        self.amount = amount
        self.modeled_cost = modeled_cost
        self.friction_cost = friction_cost
        self.escalation_risk = escalation_risk
        self.erv = (self.success_probability * self.amount) - self.modeled_cost - self.friction_cost - self.escalation_risk
        self.policy_decision = policy_decision
        self.policy_allowed = policy_decision.allowed if policy_decision else True
        self.policy_reason = policy_decision.reason if policy_decision else "Not evaluated"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "success_probability": round(self.success_probability, 3),
            "modeled_cost": round(self.modeled_cost, 2),
            "friction_cost": round(self.friction_cost, 2),
            "escalation_risk": round(self.escalation_risk, 2),
            "erv": round(self.erv, 2),
            "policy_allowed": self.policy_allowed,
            "policy_reason": self.policy_reason,
            "policy_status": "AUTHORIZED" if self.policy_allowed else "BLOCKED",
            "probability": round(self.success_probability, 3),
            "direct_cost": round(self.modeled_cost, 2),
        }


class DecisionResult:
    """Complete result of an ERV decision cycle with counterfactual explanations."""
    def __init__(
        self,
        transaction_id: str,
        selected_action: str,
        selected_erv: float,
        selected_candidate: CandidateAction,
        counterfactuals: List[CandidateAction],
        explanation: str,
        diagnosis_root_cause: str = "",
        diagnosis_method: str = "rule"
    ):
        self.transaction_id = transaction_id
        self.selected_action = selected_action
        self.selected_erv = selected_erv
        self.selected_candidate = selected_candidate
        self.counterfactuals = counterfactuals
        self.explanation = explanation
        self.diagnosis_root_cause = diagnosis_root_cause
        self.diagnosis_method = diagnosis_method

    def to_dict(self) -> Dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "selected_action": self.selected_action,
            "selected_erv": round(self.selected_erv, 2),
            "selected_candidate": self.selected_candidate.to_dict(),
            "alternatives": [c.to_dict() for c in self.counterfactuals if c.action != self.selected_action],
            "all_evaluated_candidates": [c.to_dict() for c in self.counterfactuals],
            "explanation": self.explanation,
            "diagnosis": {
                "root_cause": self.diagnosis_root_cause,
                "method": self.diagnosis_method
            }
        }


class EconomicDecisionEngine:
    """Calculates ERV, ranks candidate interventions, and selects policy-authorized actions."""

    # Base recovery probabilities conditioned on failure code and intervention action
    PROBABILITY_MATRIX: Dict[str, Dict[str, float]] = {
        "insufficient_funds": {
            ACTION_SEND_REMINDER_SMS: 0.38,
            ACTION_SUGGEST_ALTERNATE_METHOD: 0.45,
            ACTION_RETRY_SILENTLY: 0.05,
            ACTION_SEND_UPDATE_CARD_LINK: 0.15,
            ACTION_ESCALATE_TO_HUMAN: 0.20,
        },
        "bank_declined": {
            ACTION_SUGGEST_ALTERNATE_METHOD: 0.52,
            ACTION_SEND_REMINDER_SMS: 0.28,
            ACTION_SEND_UPDATE_CARD_LINK: 0.35,
            ACTION_RETRY_SILENTLY: 0.08,
            ACTION_ESCALATE_TO_HUMAN: 0.25,
        },
        "gateway_timeout": {
            ACTION_RETRY_SILENTLY: 0.65,
            ACTION_SUGGEST_ALTERNATE_METHOD: 0.40,
            ACTION_SEND_REMINDER_SMS: 0.30,
            ACTION_ESCALATE_TO_HUMAN: 0.15,
        },
        "card_expired": {
            ACTION_SEND_UPDATE_CARD_LINK: 0.60,
            ACTION_SUGGEST_ALTERNATE_METHOD: 0.48,
            ACTION_SEND_REMINDER_SMS: 0.22,
            ACTION_RETRY_SILENTLY: 0.01,
            ACTION_ESCALATE_TO_HUMAN: 0.15,
        },
        "mandate_expired": {
            ACTION_SEND_MANDATE_RENEWAL_LINK: 0.58,
            ACTION_SUGGEST_ALTERNATE_METHOD: 0.42,
            ACTION_SEND_REMINDER_SMS: 0.25,
            ACTION_ESCALATE_TO_HUMAN: 0.20,
        },
        "b2b_invoice_overdue": {
            ACTION_SEND_B2B_REMINDER: 0.62,
            ACTION_ESCALATE_TO_HUMAN: 0.45,
            ACTION_SEND_REMINDER_SMS: 0.30,
        }
    }

    @classmethod
    def estimate_recovery_probability(
        cls,
        failure_code: str,
        action: str,
        attempt_number: int,
        channel: str = "web"
    ) -> float:
        """Estimates recovery probability decayed by attempt number and channel context."""
        if channel == "b2b_invoice" and action == ACTION_SEND_B2B_REMINDER:
            base_p = 0.65
        else:
            failure_probs = cls.PROBABILITY_MATRIX.get(failure_code, {})
            base_p = failure_probs.get(action, 0.20)

        # Attempt decay: each successive attempt experiences fatigue decay
        decay_factor = math.pow(0.85, max(0, attempt_number - 1))
        return base_p * decay_factor

    @classmethod
    def evaluate_candidates(
        cls,
        transaction: Dict[str, Any],
        diagnosis: Dict[str, Any],
        attempt_number: int,
        current_hour: Optional[int] = None,
        db_path: Optional[str] = None
    ) -> DecisionResult:
        """
        Generates candidate actions, evaluates ERV for each, checks policy clearance,
        and selects the highest policy-authorized action with a complete counterfactual explanation.
        """
        amount = float(transaction.get("amount", 1000.0))
        failure_code = transaction.get("failure_code", "insufficient_funds")
        channel = transaction.get("channel", "web")
        is_subscription = bool(transaction.get("is_subscription", False))
        confidence = float(diagnosis.get("confidence", 1.0))

        # Relevant candidate action set
        candidate_names = [
            ACTION_SUGGEST_ALTERNATE_METHOD,
            ACTION_SEND_REMINDER_SMS,
            ACTION_RETRY_SILENTLY,
            ACTION_SEND_UPDATE_CARD_LINK,
            ACTION_ESCALATE_TO_HUMAN,
        ]

        if channel == "b2b_invoice":
            candidate_names.append(ACTION_SEND_B2B_REMINDER)
        if is_subscription:
            candidate_names.append(ACTION_SEND_MANDATE_RENEWAL_LINK)

        # Remove duplicates while preserving order
        candidate_names = list(dict.fromkeys(candidate_names))

        evaluated: List[CandidateAction] = []

        for act in candidate_names:
            prob = cls.estimate_recovery_probability(failure_code, act, attempt_number, channel=channel)
            modeled_cost = ACTION_COSTS.get(act, 0.25)
            friction_cost = CUSTOMER_FRICTION_BASE.get(act, 1.00) * attempt_number
            # Escalation risk penalty if customer complaints occur
            escalation_risk = 5.0 if attempt_number >= 3 and act not in SILENT_ACTIONS else 0.0

            # Evaluate policy eligibility
            policy_dec = PolicyEngine.evaluate_action(
                transaction=transaction,
                proposed_action=act,
                attempt_number=attempt_number,
                current_hour=current_hour,
                confidence=confidence,
                db_path=db_path
            )

            cand = CandidateAction(
                action=act,
                success_probability=prob,
                amount=amount,
                modeled_cost=modeled_cost,
                friction_cost=friction_cost,
                escalation_risk=escalation_risk,
                policy_decision=policy_dec
            )
            evaluated.append(cand)

        # Sort candidate actions by ERV in descending order
        evaluated.sort(key=lambda x: x.erv, reverse=True)

        # Select highest ERV that is policy allowed
        selected: Optional[CandidateAction] = None
        for cand in evaluated:
            if cand.policy_allowed:
                selected = cand
                break

        # If no action is policy allowed (e.g. opt-out or cap reached), stop contact
        if not selected:
            stop_dec = PolicyEngine.evaluate_action(
                transaction=transaction,
                proposed_action=ACTION_STOP_CONTACT,
                attempt_number=attempt_number,
                current_hour=current_hour,
                db_path=db_path
            )
            selected = CandidateAction(
                action=ACTION_STOP_CONTACT,
                success_probability=0.0,
                amount=amount,
                modeled_cost=0.0,
                friction_cost=0.0,
                escalation_risk=0.0,
                policy_decision=stop_dec
            )
            explanation = "Outreach halted: All candidate actions disallowed by policy constraints (opt-out or attempt cap)."
        else:
            # Generate clear counterfactual explanation
            alternatives = [c for c in evaluated if c.action != selected.action]
            top_alt = alternatives[0] if alternatives else None
            if top_alt:
                explanation = (
                    f"'{selected.action}' was selected with the highest expected recovery value (ERV: ₹{selected.erv:,.2f}) "
                    f"among policy-eligible actions. Alternative '{top_alt.action}' yielded ERV: ₹{top_alt.erv:,.2f} "
                    f"({'Policy ALLOWED' if top_alt.policy_allowed else 'Policy REJECTED: ' + top_alt.policy_reason})."
                )
            else:
                explanation = f"'{selected.action}' selected with ERV ₹{selected.erv:,.2f}."

        return DecisionResult(
            transaction_id=transaction.get("transaction_id", ""),
            selected_action=selected.action,
            selected_erv=selected.erv,
            selected_candidate=selected,
            counterfactuals=evaluated,
            explanation=explanation,
            diagnosis_root_cause=diagnosis.get("root_cause", ""),
            diagnosis_method=diagnosis.get("method", "rule")
        )
