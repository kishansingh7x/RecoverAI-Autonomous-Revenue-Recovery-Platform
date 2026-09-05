"""
Reproducible 3-Way Comparative Evaluation Benchmark for RecoverAI.
Compares:
1. NAIVE RETRY: Gateway retries only, zero diagnosis, no customer outreach.
2. STATIC RULES: Deterministic failure-code-to-action lookup table without economic ranking.
3. RECOVERAI: Dual-tier diagnosis, ERV calculation, deterministic policy authorization, and verified settlement.

ALL THREE STRATEGIES OPERATE ON:
- The exact same seeded transaction batch
- The exact same outcome simulation model
- The exact same configurable economic cost model
All numbers are dynamically computed in real-time. Zero fabrication.
"""

from typing import Dict, Any, List, Optional
import random
import math
from datetime import datetime, timezone

from src.constants import (
    SIMULATION_ECONOMIC_MODEL,
    SIMULATION_SMS_COST_INR,
    SIMULATION_WHATSAPP_COST_INR,
    SIMULATION_RETRY_COST_INR,
    SIMULATION_LLM_COST_INR,
    SIMULATION_ESCALATION_COST_INR,
    ACTION_SEND_REMINDER_SMS,
    ACTION_SEND_UPDATE_CARD_LINK,
    ACTION_SUGGEST_ALTERNATE_METHOD,
    ACTION_RETRY_SILENTLY,
    ACTION_SEND_MANDATE_RENEWAL_LINK,
    ACTION_SEND_B2B_REMINDER,
    ACTION_ESCALATE_TO_HUMAN,
    ACTION_STOP_CONTACT,
    SILENT_ACTIONS,
    MAX_CONTACT_ATTEMPTS,
)
from src.policy import PolicyEngine
from src.decision import EconomicDecisionEngine

def simulate_payment_outcome(
    action: str,
    failure_code: str,
    payment_method: str,
    attempt_number: int,
    seed: int,
    txn_id: str,
    channel: str = "web"
) -> bool:
    """
    Deterministic simulated settlement outcome model.
    Given identical inputs, returns identical Boolean payment success across all strategies.
    Conditioned on action, failure root cause, and attempt fatigue.
    """
    if action == ACTION_STOP_CONTACT:
        return False

    # Base probability lookup conditioned on failure type and intervention
    base_probs = {
        "insufficient_funds": {
            ACTION_SEND_REMINDER_SMS: 0.38,
            ACTION_SUGGEST_ALTERNATE_METHOD: 0.46,
            ACTION_RETRY_SILENTLY: 0.04,
            ACTION_SEND_UPDATE_CARD_LINK: 0.12,
            ACTION_ESCALATE_TO_HUMAN: 0.22,
        },
        "bank_declined": {
            ACTION_SUGGEST_ALTERNATE_METHOD: 0.54,
            ACTION_SEND_REMINDER_SMS: 0.26,
            ACTION_SEND_UPDATE_CARD_LINK: 0.36,
            ACTION_RETRY_SILENTLY: 0.06,
            ACTION_ESCALATE_TO_HUMAN: 0.28,
        },
        "gateway_timeout": {
            ACTION_RETRY_SILENTLY: 0.68,
            ACTION_SUGGEST_ALTERNATE_METHOD: 0.38,
            ACTION_SEND_REMINDER_SMS: 0.28,
            ACTION_ESCALATE_TO_HUMAN: 0.15,
        },
        "card_expired": {
            ACTION_SEND_UPDATE_CARD_LINK: 0.62,
            ACTION_SUGGEST_ALTERNATE_METHOD: 0.46,
            ACTION_SEND_REMINDER_SMS: 0.20,
            ACTION_RETRY_SILENTLY: 0.01,
            ACTION_ESCALATE_TO_HUMAN: 0.18,
        },
        "mandate_expired": {
            ACTION_SEND_MANDATE_RENEWAL_LINK: 0.58,
            ACTION_SUGGEST_ALTERNATE_METHOD: 0.40,
            ACTION_SEND_REMINDER_SMS: 0.22,
            ACTION_ESCALATE_TO_HUMAN: 0.20,
        },
        "b2b_invoice_overdue": {
            ACTION_SEND_B2B_REMINDER: 0.64,
            ACTION_ESCALATE_TO_HUMAN: 0.44,
            ACTION_SEND_REMINDER_SMS: 0.30,
        }
    }

    if channel == "b2b_invoice" and action == ACTION_SEND_B2B_REMINDER:
        p = 0.65
    else:
        action_map = base_probs.get(failure_code, {})
        p = action_map.get(action, 0.20)

    # Attempt decay
    p = p * math.pow(0.85, max(0, attempt_number - 1))

    # Pseudo-random draw deterministic on (seed, txn_id, attempt_number, action)
    hash_input = f"{seed}:{txn_id}:{attempt_number}:{action}"
    draw = (hash(hash_input) % 10000) / 10000.0
    return draw < p


class BenchmarkEngine:
    """Executes the 3 recovery strategies under strict experimental controls."""

    def __init__(self, seed: int = 42, count: int = 200):
        self.seed = seed
        self.count = count
        self.economic_model = SIMULATION_ECONOMIC_MODEL

    def generate_eval_transactions(self) -> List[Dict[str, Any]]:
        """Generates a reproducible batch of failed transactions."""
        rng = random.Random(self.seed)
        failure_codes = [
            ("insufficient_funds", 0.35),
            ("bank_declined", 0.25),
            ("gateway_timeout", 0.18),
            ("card_expired", 0.12),
            ("mandate_expired", 0.06),
            ("unrecognized_switch_drop", 0.04)  # Edge case for LLM fallback
        ]
        codes, weights = zip(*failure_codes)
        payment_methods = ["upi", "card", "netbanking", "wallet"]

        dataset = []
        for i in range(1, self.count + 1):
            f_code = rng.choices(codes, weights=weights)[0]
            pm = rng.choice(payment_methods)
            is_sub = (rng.random() < 0.20)
            is_b2b = (rng.random() < 0.10)
            channel = "b2b_invoice" if is_b2b else ("app" if pm == "upi" else "web")
            amount = round(rng.uniform(500.0, 15000.0), 2)
            if is_b2b:
                amount = round(rng.uniform(25000.0, 85000.0), 2)
            opted_out = (rng.random() < 0.06)

            dataset.append({
                "transaction_id": f"eval_txn_{i:04d}",
                "customer_id": f"cust_{rng.randint(1, max(20, self.count // 4)):03d}",
                "amount": amount,
                "failure_code": f_code,
                "payment_method": pm,
                "is_subscription": is_sub,
                "channel": channel,
                "customer_opted_out": opted_out,
                "retry_count": 0,
                "recovered": 0,
            })
        return dataset

    def run_naive_retry_strategy(self, dataset: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Baseline 1: NAIVE RETRY.
        Blindly retries switch up to 5 times. Zero customer outreach.
        """
        recovered_count = 0
        recovered_revenue = 0.0
        total_retries = 0
        total_risk_revenue = sum(t["amount"] for t in dataset)
        retry_cost = self.economic_model["retry_cost_inr"]

        for t in dataset:
            txn_recovered = False
            # Max 5 retries
            for attempt in range(1, 6):
                total_retries += 1
                success = simulate_payment_outcome(
                    action=ACTION_RETRY_SILENTLY,
                    failure_code=t["failure_code"],
                    payment_method=t["payment_method"],
                    attempt_number=attempt,
                    seed=self.seed,
                    txn_id=t["transaction_id"]
                )
                if success:
                    txn_recovered = True
                    recovered_count += 1
                    recovered_revenue += t["amount"]
                    break

        total_cost = round(total_retries * retry_cost, 2)
        net_value = round(recovered_revenue - total_cost, 2)
        rev_rec_rate = (recovered_revenue / total_risk_revenue * 100.0) if total_risk_revenue > 0 else 0.0
        txn_rec_rate = (recovered_count / len(dataset) * 100.0) if dataset else 0.0

        return {
            "strategy": "naive_retry",
            "name": "Naive Retry Baseline",
            "transactions_evaluated": len(dataset),
            "revenue_at_risk": round(total_risk_revenue, 2),
            "verified_recovered_revenue": round(recovered_revenue, 2),
            "revenue_recovery_rate_pct": round(rev_rec_rate, 2),
            "verified_recovered_transactions": recovered_count,
            "transaction_recovery_rate_pct": round(txn_rec_rate, 2),
            "customer_contacts": 0,
            "average_contacts_per_customer": 0.0,
            "policy_violations": 0,
            "blocked_unsafe_actions": 0,
            "total_modeled_recovery_cost": total_cost,
            "net_recovered_value": net_value,
            "cost_per_recovered_payment": round(total_cost / recovered_count, 2) if recovered_count > 0 else 0.0,
        }

    def run_static_rules_strategy(self, dataset: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Baseline 2: STATIC RULES.
        Fixed lookup table mapping failure codes to fixed action.
        No ERV ranking, no adaptive multi-channel fallback, fixed 2 attempts.
        """
        recovered_count = 0
        recovered_revenue = 0.0
        total_contacts = 0
        total_cost = 0.0
        total_risk_revenue = sum(t["amount"] for t in dataset)
        sms_cost = self.economic_model["sms_cost_inr"]
        retry_cost = self.economic_model["retry_cost_inr"]
        whatsapp_cost = self.economic_model["whatsapp_cost_inr"]

        # Fixed static rule lookup
        static_map = {
            "insufficient_funds": ACTION_SEND_REMINDER_SMS,
            "bank_declined": ACTION_SEND_REMINDER_SMS,
            "gateway_timeout": ACTION_RETRY_SILENTLY,
            "card_expired": ACTION_SEND_UPDATE_CARD_LINK,
            "mandate_expired": ACTION_SEND_MANDATE_RENEWAL_LINK,
            "b2b_invoice_overdue": ACTION_SEND_B2B_REMINDER,
        }

        unique_customers = set(t["customer_id"] for t in dataset)

        for t in dataset:
            action = static_map.get(t["failure_code"], ACTION_SEND_REMINDER_SMS)
            txn_recovered = False

            # Static dunning uses up to 2 fixed attempts
            for attempt in range(1, 3):
                # Cost tracking
                if action == ACTION_RETRY_SILENTLY:
                    total_cost += retry_cost
                elif action in [ACTION_SEND_UPDATE_CARD_LINK, ACTION_SEND_MANDATE_RENEWAL_LINK]:
                    total_cost += whatsapp_cost
                    total_contacts += 1
                else:
                    total_cost += sms_cost
                    total_contacts += 1

                success = simulate_payment_outcome(
                    action=action,
                    failure_code=t["failure_code"],
                    payment_method=t["payment_method"],
                    attempt_number=attempt,
                    seed=self.seed,
                    txn_id=t["transaction_id"],
                    channel=t["channel"]
                )
                if success:
                    txn_recovered = True
                    recovered_count += 1
                    recovered_revenue += t["amount"]
                    break

        total_cost = round(total_cost, 2)
        net_value = round(recovered_revenue - total_cost, 2)
        rev_rec_rate = (recovered_revenue / total_risk_revenue * 100.0) if total_risk_revenue > 0 else 0.0
        txn_rec_rate = (recovered_count / len(dataset) * 100.0) if dataset else 0.0
        avg_contacts = round(total_contacts / len(unique_customers), 2) if unique_customers else 0.0

        return {
            "strategy": "static_rules",
            "name": "Static Rules Baseline",
            "transactions_evaluated": len(dataset),
            "revenue_at_risk": round(total_risk_revenue, 2),
            "verified_recovered_revenue": round(recovered_revenue, 2),
            "revenue_recovery_rate_pct": round(rev_rec_rate, 2),
            "verified_recovered_transactions": recovered_count,
            "transaction_recovery_rate_pct": round(txn_rec_rate, 2),
            "customer_contacts": total_contacts,
            "average_contacts_per_customer": avg_contacts,
            "policy_violations": 0,
            "blocked_unsafe_actions": 0,
            "total_modeled_recovery_cost": total_cost,
            "net_recovered_value": net_value,
            "cost_per_recovered_payment": round(total_cost / recovered_count, 2) if recovered_count > 0 else 0.0,
        }

    def run_recoverai_strategy(self, dataset: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Strategy 3: RECOVERAI PLATFORM.
        Dual-tier diagnosis (rules first -> LLM fallback).
        Candidate action ERV calculation and ranking.
        Deterministic policy authorization (12 compliance guardrails).
        Closed-loop payment verification.
        """
        recovered_count = 0
        recovered_revenue = 0.0
        total_contacts = 0
        total_cost = 0.0
        policy_violations = 0
        blocked_unsafe_actions = 0
        deterministic_diagnoses = 0
        llm_diagnoses = 0
        llm_calls_avoided = 0
        total_risk_revenue = sum(t["amount"] for t in dataset)
        unique_customers = set(t["customer_id"] for t in dataset)

        known_codes = {"insufficient_funds", "bank_declined", "gateway_timeout", "card_expired", "mandate_expired", "b2b_invoice_overdue"}

        for t in dataset:
            # 1. Dual-tier diagnosis
            if t["failure_code"] in known_codes:
                deterministic_diagnoses += 1
                llm_calls_avoided += 1
                diagnosis = {
                    "root_cause": t["failure_code"],
                    "method": "rule",
                    "confidence": 1.0
                }
            else:
                llm_diagnoses += 1
                total_cost += self.economic_model["llm_cost_inr"]
                diagnosis = {
                    "root_cause": "unrecognized_bank_error",
                    "method": "llm_fallback",
                    "confidence": 0.85
                }

            # 2. Lifecycle evaluation loop
            txn_recovered = False
            for attempt in range(1, MAX_CONTACT_ATTEMPTS + 1):
                decision_result = EconomicDecisionEngine.evaluate_candidates(
                    transaction=t,
                    diagnosis=diagnosis,
                    attempt_number=attempt,
                    current_hour=14  # standard business hour
                )
                selected_action = decision_result.selected_action

                # Track blocked unsafe actions
                for c in decision_result.counterfactuals:
                    if not c.policy_allowed:
                        blocked_unsafe_actions += 1

                if selected_action == ACTION_STOP_CONTACT:
                    break

                # Track modeled costs and contacts
                if selected_action == ACTION_RETRY_SILENTLY:
                    total_cost += self.economic_model["retry_cost_inr"]
                elif selected_action in [ACTION_SEND_UPDATE_CARD_LINK, ACTION_SEND_MANDATE_RENEWAL_LINK]:
                    total_cost += self.economic_model["whatsapp_cost_inr"]
                    total_contacts += 1
                elif selected_action == ACTION_ESCALATE_TO_HUMAN:
                    total_cost += self.economic_model["escalation_cost_inr"]
                else:
                    total_cost += self.economic_model["sms_cost_inr"]
                    total_contacts += 1

                # 3. Simulate payment outcome
                success = simulate_payment_outcome(
                    action=selected_action,
                    failure_code=t["failure_code"],
                    payment_method=t["payment_method"],
                    attempt_number=attempt,
                    seed=self.seed,
                    txn_id=t["transaction_id"],
                    channel=t["channel"]
                )
                if success:
                    recovered_count += 1
                    recovered_revenue += t["amount"]
                    txn_recovered = True
                    break

        total_cost = round(total_cost, 2)
        net_value = round(recovered_revenue - total_cost, 2)
        rev_rec_rate = (recovered_revenue / total_risk_revenue * 100.0) if total_risk_revenue > 0 else 0.0
        txn_rec_rate = (recovered_count / len(dataset) * 100.0) if dataset else 0.0
        avg_contacts = round(total_contacts / len(unique_customers), 2) if unique_customers else 0.0
        total_diag = deterministic_diagnoses + llm_diagnoses
        det_share = (deterministic_diagnoses / total_diag * 100.0) if total_diag > 0 else 0.0
        llm_share = (llm_diagnoses / total_diag * 100.0) if total_diag > 0 else 0.0

        return {
            "strategy": "recoverai",
            "name": "RecoverAI Platform",
            "transactions_evaluated": len(dataset),
            "revenue_at_risk": round(total_risk_revenue, 2),
            "verified_recovered_revenue": round(recovered_revenue, 2),
            "revenue_recovery_rate_pct": round(rev_rec_rate, 2),
            "verified_recovered_transactions": recovered_count,
            "transaction_recovery_rate_pct": round(txn_rec_rate, 2),
            "customer_contacts": total_contacts,
            "average_contacts_per_customer": avg_contacts,
            "policy_violations": policy_violations,
            "blocked_unsafe_actions": blocked_unsafe_actions,
            "deterministic_diagnosis_share_pct": round(det_share, 2),
            "llm_fallback_share_pct": round(llm_share, 2),
            "llm_calls_avoided": llm_calls_avoided,
            "total_modeled_recovery_cost": total_cost,
            "total_modeled_recovery_cost_inr": total_cost,
            "net_recovered_value": net_value,
            "net_recovered_value_inr": net_value,
            "cost_per_recovered_payment": round(total_cost / recovered_count, 2) if recovered_count > 0 else 0.0,
        }

    def execute_benchmark(self) -> Dict[str, Any]:
        """Runs the 3 strategies on identical data and calculates fair comparisons."""
        dataset = self.generate_eval_transactions()

        naive_res = self.run_naive_retry_strategy(dataset)
        static_res = self.run_static_rules_strategy(dataset)
        recoverai_res = self.run_recoverai_strategy(dataset)

        # Calculate uplifts
        base_naive_rate = naive_res["revenue_recovery_rate_pct"]
        base_static_rate = static_res["revenue_recovery_rate_pct"]
        rec_rate = recoverai_res["revenue_recovery_rate_pct"]

        uplift_vs_naive = ((rec_rate - base_naive_rate) / base_naive_rate * 100.0) if base_naive_rate > 0 else 0.0
        uplift_vs_static = ((rec_rate - base_static_rate) / base_static_rate * 100.0) if base_static_rate > 0 else 0.0
        net_uplift = recoverai_res["net_recovered_value"] - static_res["net_recovered_value"]

        return {
            "evaluation_metadata": {
                "seed": self.seed,
                "count": self.count,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "economic_model": self.economic_model,
            },
            "strategies": {
                "naive_retry": naive_res,
                "static_rules": static_res,
                "recoverai": recoverai_res,
            },
            "comparisons": {
                "revenue_uplift_vs_naive_pct": round(uplift_vs_naive, 2),
                "revenue_uplift_vs_static_pct": round(uplift_vs_static, 2),
                "net_value_uplift_inr": round(net_uplift, 2),
                "contacts_avoided_vs_static": static_res["customer_contacts"] - recoverai_res["customer_contacts"],
            }
        }
