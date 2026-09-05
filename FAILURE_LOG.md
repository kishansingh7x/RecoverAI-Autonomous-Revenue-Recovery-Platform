# Failure Log: Real Case Study Encountered During Development

**Project:** RecoverAI — Autonomous AI Revenue Recovery Agent  
**Buildathon Track:** Razorpay AI Buildathon 2026 — Track 03: AI Revenue Recovery  
**Documented Per PRD:** Section 2 (Failure Recovery Criterion) & Section 6.9  

---

## 1. Executive Summary

During the initial implementation of the bounded action execution layer (`src/execute.py`), re-running the pipeline on an existing transaction batch caused the agent to advance every customer to the subsequent contact attempt prematurely (firing Attempt 2 and Attempt 3 back-to-back), rather than remaining idempotent.

This failure was detected during manual execution verification and automated regression testing. It was resolved by introducing a batch-level idempotency guard, an explicit uniqueness check on `(transaction_id, attempt_number, action_type)`, and a dedicated regression test (`tests/test_idempotency.py`).

---

## 2. What Broke

When running the full recovery pipeline once, 60 transactions were diagnosed and 60 initial recovery actions were dispatched (with `attempt_number = 1`).

However, when re-executing `execute_recovery_actions()` on the same unchanged database state, the executor generated **48 additional outbound actions** instead of **0**:
```
Re-run result: 48 new actions generated!
```

### Consequences:
1. **Customer Spamming:** Customers received duplicate recovery reminders within seconds of the first.
2. **Artificial Cap Exhaustion:** By the third re-run, customers had their 3-attempt limit completely exhausted and were prematurely halted under `max_attempts_reached`, stopping genuine recovery opportunities.
3. **Audit Trail Corruption:** Audit logs contained duplicate attempt logs with near-identical timestamps.

---

## 3. How It Was Detected

The issue was uncovered during CLI testing of pipeline repeatability:

```powershell
python -c "from src.execute import execute_recovery_actions; print('Re-run result:', len(execute_recovery_actions()))"
# Expected: Re-run result: 0
# Actual:   Re-run result: 48
```

Inspecting the database directly confirmed that customer `txn_0002` had both an Attempt 1 and an Attempt 2 row logged within 10 seconds:
```sql
SELECT action_id, transaction_id, attempt_number, timestamp 
FROM actions_log 
WHERE transaction_id = 'txn_0002';

-- Output:
-- act_txn_0002_1 | txn_0002 | 1 | 2026-09-05 04:03:04
-- act_txn_0002_2 | txn_0002 | 2 | 2026-09-05 04:03:14
```

---

## 4. Root Cause Analysis

In `src/execute.py`, the previous customer attempt count was computed as:
```python
customer_facing_attempts = sum(
    1 for h in history if h["action_type"] not in SILENT_ACTIONS and h["action_type"] != ACTION_STOP_CONTACT
)
next_attempt = customer_facing_attempts + 1
```

1. On the **first run**, `history` was empty (`customer_facing_attempts = 0`), so `next_attempt = 1`. The action was logged with `attempt_number = 1`.
2. On the **second run**, `history` contained 1 item (`customer_facing_attempts = 1`). The code calculated `next_attempt = 1 + 1 = 2`.
3. The guard check only checked `actions_log` for `attempt_number = 2`, which did not yet exist.
4. Because the executor did not check whether an active customer-facing action was **already pending** for this transaction in the current batch cycle, it assumed a second attempt was due immediately and fired Attempt 2.

Follow-up attempts should only be event-driven (e.g. an unfulfilled promise in `ptp_tracker.py` or an elapsed timeout), never triggered spontaneously by re-invoking the batch processor.

---

## 5. The Fix

The fix was applied in two parts:
1. **Batch State Guard:** In `src/execute.py`, if `customer_facing_attempts > 0` and the transaction is not stopped, skip taking a new action during the standard batch cycle.
2. **Idempotency Guard:** An explicit existence check verifies that `(transaction_id, next_attempt, action_type)` does not exist before any database insertion.

### Before & After Code Comparison

#### Before (`src/execute.py`):
```python
# Count previous customer-facing contact attempts
customer_facing_attempts = sum(
    1 for h in history if h["action_type"] not in SILENT_ACTIONS and h["action_type"] != ACTION_STOP_CONTACT
)

# Rule 4: Customer-Facing Recovery Action
next_attempt = customer_facing_attempts + 1
action_entry = {
    "action_id": f"act_{txn_id}_{next_attempt}",
    "transaction_id": txn_id,
    "action_type": rec_action,
    "reasoning": reasoning,
    "message_sent": message_copy,
    "attempt_number": next_attempt,
    "stopped_reason": None,
    "timestamp": now_str
}
executed_actions.append(action_entry)
```

#### After (`src/execute.py`):
```python
# 1. Enforce stopping rules first (Opt-out, Max attempts cap)
if is_opted_out:
    ...
if customer_facing_attempts >= MAX_CONTACT_ATTEMPTS:
    ...

# 2. Check if an initial action was already dispatched for this transaction in the current cycle
if history:
    if rec_action in SILENT_ACTIONS and any(h["action_type"] == rec_action for h in history):
        continue
    # If an initial customer-facing action was already taken, do not spontaneously fire attempt 2
    if customer_facing_attempts > 0:
        continue

# 3. Guard against duplicate insertion
if check_idempotency:
    cursor.execute("""
        SELECT 1 FROM actions_log 
        WHERE transaction_id = ? AND attempt_number = ? AND action_type = ?
    """, (txn_id, next_attempt, rec_action))
    if cursor.fetchone():
        continue
```

---

## 6. Verification and Regression Test

A dedicated regression test was added to `tests/test_idempotency.py`:

```python
def test_re_running_pipeline_does_not_duplicate_actions(test_db):
    # Pass 1: Initial execution
    first_run_actions = execute_recovery_actions(db_path=test_db, check_idempotency=True)
    assert len(first_run_actions) == 3

    # Pass 2: Re-run on unchanged database state
    second_run_actions = execute_recovery_actions(db_path=test_db, check_idempotency=True)
    assert len(second_run_actions) == 0, "Idempotency violated: duplicate actions created on re-run!"
```

### Test Result:
```powershell
pytest tests/test_idempotency.py
# ============================== 1 passed in 0.08s ==============================
```

Subsequent CLI verification confirmed:
```powershell
python -c "from src.execute import execute_recovery_actions; print('Re-run result:', len(execute_recovery_actions()))"
# Output: Re-run result: 0
```
