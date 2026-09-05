"""
Payment Verification Engine for RecoverAI.
Enforces strict settlement verification semantics.
Under no circumstances is an outreach dispatch or a Promise-to-Pay equivalent to recovered revenue.
A transaction only reaches RECOVERED state through an authenticated or validated settlement event
accepted by this verification layer.
"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone
import hashlib
import json

from src.constants import (
    STATE_ACTION_DISPATCHED,
    STATE_PAYMENT_PENDING,
    STATE_RECOVERED,
    STATE_FOLLOW_UP_ELIGIBLE,
    STATE_STOPPED,
)
from src.state_machine import RecoveryStateMachine, InvalidStateTransitionError
from src.db import get_connection

class VerificationError(Exception):
    """Raised when settlement verification fails or payload is invalid."""
    pass


class VerificationResult:
    """Structured result of a payment settlement verification check."""
    def __init__(
        self,
        verified: bool,
        transaction_id: str,
        verified_amount: float = 0.0,
        verification_id: str = "",
        verification_source: str = "simulation_settlement_event",
        message: str = "",
        raw_payload: Optional[Dict[str, Any]] = None,
    ):
        self.verified = verified
        self.transaction_id = transaction_id
        self.verified_amount = verified_amount
        self.verification_id = verification_id
        self.verification_source = verification_source
        self.message = message
        self.raw_payload = raw_payload or {}
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verified": self.verified,
            "transaction_id": self.transaction_id,
            "verified_amount": self.verified_amount,
            "verification_id": self.verification_id,
            "verification_source": self.verification_source,
            "message": self.message,
            "timestamp": self.timestamp,
        }


class VerificationEngine:
    """
    Verification layer governing settlement confirmation.
    Includes provider signature validation interface/stub and
    deterministic simulated settlement verification for hackathon evaluation.
    """

    @staticmethod
    def validate_provider_signature_stub(payload: Dict[str, Any], signature: str, secret: str = "rzp_sim_secret") -> bool:
        """
        Provider signature validation interface/stub.
        In live production, validates HMAC-SHA256 signature from payment gateway webhook.
        In hackathon simulation mode, validates signature structure or simulated hash.
        """
        if not signature:
            return False
        # Stub check: compute expected HMAC or accept structured simulation test tokens
        canonical = json.dumps(payload, sort_keys=True)
        expected = hashlib.sha256(f"{canonical}:{secret}".encode("utf-8")).hexdigest()
        return signature == expected or signature.startswith("sim_sig_valid_")

    @classmethod
    def verify_settlement_event(
        cls,
        transaction_id: str,
        event_type: str,
        amount: float,
        auth_code: str = "",
        signature: Optional[str] = None,
        db_path: Optional[str] = None
    ) -> VerificationResult:
        """
        Verifies a settlement event against the transaction's current recovery state.
        Only transitions state to RECOVERED if current state is ACTION_DISPATCHED or PAYMENT_PENDING.
        """
        conn = get_connection(db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT transaction_id, amount, status, recovery_state, recovered
            FROM transactions
            WHERE transaction_id = ?
        """, (transaction_id,))
        row = cursor.fetchone()

        if not row:
            conn.close()
            return VerificationResult(
                verified=False,
                transaction_id=transaction_id,
                message=f"Transaction '{transaction_id}' not found in database."
            )

        current_state = row["recovery_state"]
        expected_amount = row["amount"]

        if row["recovered"] == 1 or current_state == STATE_RECOVERED:
            conn.close()
            return VerificationResult(
                verified=True,
                transaction_id=transaction_id,
                verified_amount=expected_amount,
                message="Transaction was already verified as RECOVERED."
            )

        # Validate event type
        valid_settlement_events = {
            "payment.captured",
            "settlement.verified",
            "mandate.auto_debited",
            "invoice.paid",
            "ptp_payment_confirmed"
        }

        if event_type not in valid_settlement_events:
            conn.close()
            return VerificationResult(
                verified=False,
                transaction_id=transaction_id,
                message=f"Invalid event_type '{event_type}'. Must be one of {valid_settlement_events}."
            )

        # Check signature if provided
        if signature is not None:
            sig_valid = cls.validate_provider_signature_stub(
                {"txn_id": transaction_id, "event": event_type, "amount": amount},
                signature
            )
            if not sig_valid:
                conn.close()
                return VerificationResult(
                    verified=False,
                    transaction_id=transaction_id,
                    message="Provider signature verification failed."
                )

        # Validate state machine transition to RECOVERED
        try:
            RecoveryStateMachine.validate_and_transition(
                current_state=current_state,
                target_state=STATE_RECOVERED,
                transaction_id=transaction_id,
                reason=f"Settlement confirmed via {event_type} (Auth: {auth_code or 'SIM_AUTH'})"
            )
        except InvalidStateTransitionError as err:
            conn.close()
            return VerificationResult(
                verified=False,
                transaction_id=transaction_id,
                message=f"State machine rejected transition to RECOVERED: {str(err)}"
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        verification_id = f"vfy_{hashlib.sha256(f'{transaction_id}:{now_iso}'.encode()).hexdigest()[:12]}"

        # Atomically update transaction to RECOVERED
        cursor.execute("""
            UPDATE transactions
            SET recovered = 1,
                recovery_state = ?,
                verified_at = ?,
                verification_source = 'simulation_settlement_event'
            WHERE transaction_id = ?
        """, (STATE_RECOVERED, now_iso, transaction_id))

        conn.commit()
        conn.close()

        return VerificationResult(
            verified=True,
            transaction_id=transaction_id,
            verified_amount=expected_amount,
            verification_id=verification_id,
            verification_source="simulation_settlement_event",
            message="Payment success validated. State successfully transitioned to RECOVERED."
        )
