"""
Tests for Recovery State Machine (src/state_machine.py).
Verifies:
- Valid transition flows
- Invalid transition rejection with InvalidStateTransitionError
- RECOVERED is terminal and blocks any further action
- STOPPED is terminal and blocks further outreach
- ESCALATED requires supervisor override
"""

import pytest
from src.state_machine import RecoveryStateMachine, InvalidStateTransitionError
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
)

def test_valid_recovery_lifecycle():
    """Verifies the complete standard happy-path recovery lifecycle."""
    state = STATE_FAILED
    
    # 1. Detection
    res = RecoveryStateMachine.validate_and_transition(state, STATE_RISK_FLAGGED, "TXN_101")
    assert res["new_state"] == STATE_RISK_FLAGGED
    state = res["new_state"]

    # 2. Diagnosis
    res = RecoveryStateMachine.validate_and_transition(state, STATE_DIAGNOSED, "TXN_101")
    assert res["new_state"] == STATE_DIAGNOSED
    state = res["new_state"]

    # 3. Action Selection (ERV)
    res = RecoveryStateMachine.validate_and_transition(state, STATE_ACTION_SELECTED, "TXN_101")
    assert res["new_state"] == STATE_ACTION_SELECTED
    state = res["new_state"]

    # 4. Dispatch
    res = RecoveryStateMachine.validate_and_transition(state, STATE_ACTION_DISPATCHED, "TXN_101")
    assert res["new_state"] == STATE_ACTION_DISPATCHED
    state = res["new_state"]

    # 5. Awaiting Payment
    res = RecoveryStateMachine.validate_and_transition(state, STATE_PAYMENT_PENDING, "TXN_101")
    assert res["new_state"] == STATE_PAYMENT_PENDING
    state = res["new_state"]

    # 6. Verified Settlement
    res = RecoveryStateMachine.validate_and_transition(state, STATE_RECOVERED, "TXN_101")
    assert res["new_state"] == STATE_RECOVERED
    assert RecoveryStateMachine.is_terminal(res["new_state"]) is True

def test_invalid_transition_rejected():
    """Verifies that skipping states (e.g. FAILED -> RECOVERED) is strictly rejected."""
    with pytest.raises(InvalidStateTransitionError):
        RecoveryStateMachine.validate_and_transition(STATE_FAILED, STATE_RECOVERED, "TXN_ERR_01")

    with pytest.raises(InvalidStateTransitionError):
        RecoveryStateMachine.validate_and_transition(STATE_FAILED, STATE_ACTION_DISPATCHED, "TXN_ERR_02")

def test_recovered_is_strictly_terminal():
    """Verifies that once RECOVERED, no subsequent recovery actions can be taken."""
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        RecoveryStateMachine.validate_and_transition(STATE_RECOVERED, STATE_ACTION_DISPATCHED, "TXN_REC_01")
    assert "already verified RECOVERED" in str(exc_info.value)

def test_stopped_is_terminal():
    """Verifies that STOPPED transactions cannot transition to action states."""
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        RecoveryStateMachine.validate_and_transition(STATE_STOPPED, STATE_ACTION_SELECTED, "TXN_STP_01")
    assert "terminal STOPPED state" in str(exc_info.value)

def test_escalated_requires_supervisor_override():
    """Verifies that ESCALATED state blocks autonomous recovery unless overridden."""
    # Autonomous transition attempt should fail
    with pytest.raises(InvalidStateTransitionError) as exc_info:
        RecoveryStateMachine.validate_and_transition(STATE_ESCALATED, STATE_ACTION_SELECTED, "TXN_ESC_01")
    assert "supervisor authorization" in str(exc_info.value)

    # Supervisor override should succeed
    res = RecoveryStateMachine.validate_and_transition(
        STATE_ESCALATED,
        STATE_ACTION_SELECTED,
        "TXN_ESC_01",
        supervisor_override=True
    )
    assert res["new_state"] == STATE_ACTION_SELECTED
    assert res["supervisor_override"] is True
