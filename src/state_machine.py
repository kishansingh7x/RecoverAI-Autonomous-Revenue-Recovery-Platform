"""
Recovery State Machine for RecoverAI.
Explicit domain abstraction governing all recovery state transitions.
Enforces that:
- Every transition is validated against an explicit transition table.
- Invalid transitions are rejected with InvalidStateTransitionError.
- Recovered transactions never receive further recovery actions.
- Stopped transactions do not continue outreach.
- Escalated transactions cannot continue automated recovery without explicit supervisor authorization.
- State changes are auditable.
"""

from typing import Dict, Set, Optional, Tuple, Any
from datetime import datetime, timezone

from src.constants import (
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
    ALL_RECOVERY_STATES,
)

class InvalidStateTransitionError(ValueError):
    """Raised when an illegal state transition is attempted."""
    def __init__(self, from_state: str, to_state: str, reason: str = ""):
        self.from_state = from_state
        self.to_state = to_state
        self.reason = reason
        msg = f"Invalid recovery state transition: '{from_state}' -> '{to_state}'."
        if reason:
            msg += f" Reason: {reason}"
        super().__init__(msg)


# Explicit Allowed Transitions Table: source_state -> set of valid target_states
TRANSITION_TABLE: Dict[str, Set[str]] = {
    STATE_FAILED: {
        STATE_RISK_FLAGGED,
        STATE_STOPPED,
        STATE_ESCALATED,
    },
    STATE_RISK_FLAGGED: {
        STATE_DIAGNOSED,
        STATE_STOPPED,
        STATE_ESCALATED,
    },
    STATE_DIAGNOSED: {
        STATE_ACTION_SELECTED,
        STATE_STOPPED,
        STATE_ESCALATED,
    },
    STATE_ACTION_SELECTED: {
        STATE_ACTION_DISPATCHED,
        STATE_STOPPED,
        STATE_ESCALATED,
    },
    STATE_ACTION_DISPATCHED: {
        STATE_PAYMENT_PENDING,
        STATE_RECOVERED,      # Immediate settlement (e.g. silent retry success)
        STATE_STOPPED,
        STATE_ESCALATED,
    },
    STATE_PAYMENT_PENDING: {
        STATE_RECOVERED,          # Validated settlement event received
        STATE_FOLLOW_UP_ELIGIBLE, # Payment window expired, attempts left
        STATE_STOPPED,            # Opt-out or terminal timeout
        STATE_ESCALATED,          # Disputed / unresolved charge
    },
    STATE_FOLLOW_UP_ELIGIBLE: {
        STATE_ACTION_SELECTED,    # Re-evaluating next candidate action
        STATE_DIAGNOSED,          # Re-diagnosing post failure
        STATE_STOPPED,            # Cap reached
        STATE_ESCALATED,
    },
    # Terminal states
    STATE_RECOVERED: set(),       # Absolute terminal: NO further transitions permitted
    STATE_STOPPED: set(),         # Outreach halted permanently
    STATE_ESCALATED: set(),       # Blocked from automated transitions
}

# Supervisor authorized transitions from ESCALATED
SUPERVISOR_AUTHORIZED_TRANSITIONS: Dict[str, Set[str]] = {
    STATE_ESCALATED: {
        STATE_ACTION_SELECTED,
        STATE_DIAGNOSED,
        STATE_STOPPED,
    }
}


class RecoveryStateMachine:
    """Domain service managing validated recovery transitions."""

    @staticmethod
    def is_valid_transition(
        from_state: str,
        to_state: str,
        supervisor_override: bool = False
    ) -> bool:
        """Checks whether a transition between two states is permissible."""
        if from_state not in ALL_RECOVERY_STATES or to_state not in ALL_RECOVERY_STATES:
            return False

        if supervisor_override and from_state == STATE_ESCALATED:
            return to_state in SUPERVISOR_AUTHORIZED_TRANSITIONS.get(STATE_ESCALATED, set())

        allowed = TRANSITION_TABLE.get(from_state, set())
        return to_state in allowed

    @classmethod
    def validate_and_transition(
        cls,
        current_state: str,
        target_state: str,
        transaction_id: str = "",
        reason: str = "",
        supervisor_override: bool = False
    ) -> Dict[str, Any]:
        """
        Validates transition and produces an auditable transition record.
        Raises InvalidStateTransitionError if the transition is disallowed.
        """
        if current_state == STATE_RECOVERED:
            raise InvalidStateTransitionError(
                current_state,
                target_state,
                "Transaction is already verified RECOVERED. Further recovery actions are strictly forbidden."
            )

        if current_state == STATE_STOPPED:
            raise InvalidStateTransitionError(
                current_state,
                target_state,
                "Transaction is in terminal STOPPED state. Further recovery outreach is halted."
            )

        if current_state == STATE_ESCALATED and not supervisor_override:
            raise InvalidStateTransitionError(
                current_state,
                target_state,
                "Transaction is ESCALATED. Autonomous recovery blocked without explicit supervisor authorization."
            )

        if not cls.is_valid_transition(current_state, target_state, supervisor_override=supervisor_override):
            raise InvalidStateTransitionError(
                current_state,
                target_state,
                f"Transition not permitted by domain policy. Allowed from '{current_state}': {TRANSITION_TABLE.get(current_state, set())}"
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        return {
            "transaction_id": transaction_id,
            "previous_state": current_state,
            "new_state": target_state,
            "reason": reason or f"Transitioned to {target_state}",
            "supervisor_override": supervisor_override,
            "timestamp": now_iso,
        }

    @staticmethod
    def is_terminal(state: str) -> bool:
        """Returns True if the state is terminal (RECOVERED or STOPPED)."""
        return state in {STATE_RECOVERED, STATE_STOPPED}

    @staticmethod
    def can_receive_outreach(state: str) -> bool:
        """Determines if a transaction in this state can receive customer-facing outreach."""
        return state in {STATE_DIAGNOSED, STATE_ACTION_SELECTED, STATE_FOLLOW_UP_ELIGIBLE}
