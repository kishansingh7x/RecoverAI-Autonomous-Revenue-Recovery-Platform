# PRD: RecoverAI — Payment Failure → Root Cause → Recovery Agent

**Owner:** [Your Name], B.Tech CSIT 2029
**Purpose:** Submission for Razorpay AI Buildathon 2026 — Track 03: AI Revenue Recovery
**Audience of this document:** An autonomous coding agent (Antigravity). Build this exactly as specified. Where a decision is ambiguous, prefer the simplest working implementation over a complex one, and note the tradeoff in the README instead of asking for clarification.

---

## 1. One-line pitch

An agent that watches a batch of e-commerce/subscription transactions, detects revenue that is at risk (failed payments, abandoned checkouts, failed subscription renewals, overdue invoices), diagnoses *why* each one failed, decides a bounded and compliant recovery action, executes a simulated recovery workflow, tracks promises-to-pay, and reports exactly how much money it recovered — with a full audit trail and at least one documented failure it recovered from during development.

## 2. Why this project (context for the agent, do not skip)

Razorpay's evaluation rubric for this track has four criteria. Every module below is designed to hit one or more of them directly:

1. **Problem Taste** — this is a real, ground-level problem: businesses lose meaningful revenue not because customers refuse to pay, but because a payment failed and nobody followed up correctly.
2. **Build Quality** — clean repo structure, deterministic core, reliable end-to-end execution on a batch, not a single cherry-picked demo case.
3. **AI Judgment** — detection and routing logic must be **deterministic (plain code/rules)**. The LLM must be used **only** where natural language judgment genuinely helps: writing the personalized recovery message, and classifying the small number of *ambiguous* failure cases the rule engine can't confidently classify. Do not use an LLM for anything a rule or SQL query can do.
4. **Failure Recovery** — the project must include one deliberately surfaced, real bug encountered during build (e.g. duplicate messaging, a bad confidence threshold, a race condition in retry scheduling), documented with: what broke, how it was detected, and the fix. Do not fabricate this — actually build it, notice something break, and document the real fix.

The official "bar" for this track: *"Don't just identify the problem. Show measured money recovered across a batch, with compliant escalation, stopping rules, and an audit trail."* Every number the system produces must come from actually running the batch, not from hardcoded/fabricated output.

## 3. Scope

### In scope (build this)
- Synthetic transaction batch generator (150–300 records)
- Deterministic revenue-at-risk detector
- Deterministic root-cause + recommended-action rule engine, with an LLM fallback only for low-confidence/ambiguous cases
- LLM-generated personalized recovery messages (English + optional Hinglish tone)
- Bounded action executor with a fixed action menu, max-attempt cap, and stop rules (opt-out, compliance)
- Promise-to-pay tracker with automatic follow-up on missed promises
- Full audit trail logger (every decision + reasoning + timestamp, exportable as JSON/CSV)
- Metrics engine: revenue at risk, amount recovered, recovery rate by failure type, stopped-for-compliance count
- Simple dashboard (Streamlit) to demo the batch run and metrics visually
- A documented failure-and-fix case study
- README with architecture diagram (ASCII or Mermaid is fine), setup instructions, and headline metrics

### Out of scope (do not build, do not waste time on)
- Real payment gateway integration (Razorpay live/test API calls) — mock this layer, but structure the code so a real API client could be swapped in later (note this in README as "next step")
- Real SMS/WhatsApp/email sending — mock/log the message instead of calling Twilio/WhatsApp Business API
- User authentication, multi-tenant support, or a production database
- Any offense-capable logic (nothing that could be used to defraud, spam, or harass — this is a defensive/recovery tool only)

## 4. Users / personas

- **Merchant ops analyst** — wants to see how much revenue is at risk right now and how much the agent is recovering, without reading logs.
- **Compliance reviewer** — wants proof that the agent never contacts a customer more than the allowed number of times, respects opt-outs, and that every action is explainable after the fact.
- **Razorpay panel (the actual audience for this build)** — wants to see a working system, real numbers from a real batch run, and evidence you understand where AI helps and where it doesn't.

## 5. Data model

Use SQLite for simplicity (single file `recovery.db`), accessed via SQLAlchemy or plain `sqlite3`. Also keep everything readable via a `transactions.csv` export.

### Table: `transactions`
| Field | Type | Notes |
|---|---|---|
| transaction_id | TEXT PK | e.g. `txn_0001` |
| customer_id | TEXT | e.g. `cust_042` |
| customer_name | TEXT | synthetic Indian names |
| amount | REAL | in INR |
| payment_method | TEXT | upi / card / netbanking / wallet |
| status | TEXT | success / failed / abandoned |
| failure_code | TEXT (nullable) | insufficient_funds / bank_declined / gateway_timeout / card_expired / otp_timeout / mandate_expired / null if success |
| is_subscription | BOOLEAN | true/false |
| channel | TEXT | web / app / b2b_invoice |
| created_at | DATETIME | |
| retry_count | INTEGER | default 0 |
| customer_opted_out | BOOLEAN | default false, ~5% of customers randomly set true |

### Table: `risk_flags`
| Field | Type | Notes |
|---|---|---|
| flag_id | TEXT PK | |
| transaction_id | TEXT FK | |
| risk_type | TEXT | failed_payment_not_retried / abandoned_checkout / failed_subscription_renewal / overdue_invoice |
| detected_at | DATETIME | |

### Table: `diagnoses`
| Field | Type | Notes |
|---|---|---|
| diagnosis_id | TEXT PK | |
| transaction_id | TEXT FK | |
| root_cause | TEXT | human-readable root cause |
| recommended_action | TEXT | one of the fixed action menu values (see §6.4) |
| method | TEXT | "rule" or "llm_fallback" |
| confidence | REAL | 0–1, only meaningful for llm_fallback |

### Table: `actions_log` (this IS the audit trail)
| Field | Type | Notes |
|---|---|---|
| action_id | TEXT PK | |
| transaction_id | TEXT FK | |
| action_type | TEXT | see fixed action menu |
| reasoning | TEXT | plain-language explanation of why this action was chosen |
| message_sent | TEXT (nullable) | the actual generated recovery message, if any |
| attempt_number | INTEGER | |
| stopped_reason | TEXT (nullable) | "max_attempts_reached" / "customer_opted_out" / null |
| timestamp | DATETIME | |

### Table: `promises_to_pay`
| Field | Type | Notes |
|---|---|---|
| promise_id | TEXT PK | |
| transaction_id | TEXT FK | |
| promised_date | DATE | |
| fulfilled | BOOLEAN | default false |
| follow_up_sent | BOOLEAN | default false |

## 6. Functional requirements

### 6.1 Synthetic data generator (`generate_data.py`)
- Generate 150–300 transactions with realistic distributions:
  - ~60% success, ~30% failed, ~10% abandoned
  - Failure codes distributed roughly: insufficient_funds 30%, bank_declined 25%, gateway_timeout 15%, card_expired 15%, otp_timeout 10%, mandate_expired 5%
  - ~20% of transactions are subscriptions
  - ~10% are B2B invoices (channel = b2b_invoice) with larger amounts and longer overdue windows
  - Use `Faker` (locale `en_IN` if available) for names; timestamps spread over the last 30 days
- Output: populate `recovery.db` and also dump `transactions.csv`
- Must be re-runnable (idempotent — wipe and regenerate, don't append duplicates)

### 6.2 Detection layer (`detect.py`) — fully deterministic, no AI
Rules (implement as plain Python/SQL, log each detection to `risk_flags`):
- `failed_payment_not_retried`: status = failed AND retry_count = 0 AND age > 24 hours
- `abandoned_checkout`: status = abandoned
- `failed_subscription_renewal`: is_subscription = true AND status = failed
- `overdue_invoice`: channel = b2b_invoice AND status = failed AND age > 7 days

### 6.3 Diagnosis layer (`diagnose.py`) — rule-first, LLM fallback
1. First pass: a lookup table maps `failure_code` → `root_cause` + `recommended_action` deterministically. This should cover the large majority of cases (target: ≥80% resolved by rules alone — this ratio is itself a metric you report, proving deliberate, sparing AI use).
2. Second pass (LLM fallback): only invoked when `failure_code` is null/unrecognized, or when a transaction matches more than one risk flag and the rule table doesn't specify precedence. Call the LLM with a structured prompt (see §7) asking for `root_cause`, `recommended_action` (must be restricted to the fixed action menu — validate the LLM's output against the allowed list and fall back to `escalate_to_human` if it returns anything else), and `confidence` (0–1). If confidence < 0.5, force `recommended_action = escalate_to_human`.
3. Log every diagnosis with `method = "rule"` or `"llm_fallback"` so the audit trail shows exactly which cases needed AI.

### 6.4 Fixed action menu (never allow anything outside this list)
- `send_reminder_sms` (for insufficient_funds — schedule retry in 2 days)
- `send_update_card_link` (for card_expired)
- `suggest_alternate_payment_method` (for bank_declined)
- `retry_silently` (for gateway_timeout / otp_timeout — technical, no customer contact needed, retry once after 1 hour)
- `send_mandate_renewal_link` (for mandate_expired subscriptions)
- `send_b2b_payment_reminder` (for overdue_invoice — formal tone, cc's a finance contact if amount > ₹50,000)
- `escalate_to_human` (low-confidence or repeated-failure cases)
- `stop_contact` (terminal state — see stopping rules)

### 6.5 Bounded execution & stopping rules (`execute.py`)
- Before taking any action, check: `customer_opted_out` → force `stop_contact`, log `stopped_reason = "customer_opted_out"`, do not proceed.
- Max 3 contact attempts per transaction. On attempt 4, force `stop_contact`, log `stopped_reason = "max_attempts_reached"`.
- `retry_silently` does not count against the customer-contact attempt cap (it's not customer-facing).
- For any customer-facing action, generate the actual message text via the LLM (see §7.2), log it in `actions_log.message_sent`, but **do not actually send** anything externally — this is simulated. Print/log clearly that it's simulated.
- Every single action, whether it results in a message or a stop, must be written to `actions_log` with full reasoning in plain English (e.g. "insufficient_funds detected via rule engine; scheduling reminder 2 days out per rule table; this is attempt 1 of 3").

### 6.6 Promise-to-pay tracker (`ptp_tracker.py`)
- For a random ~40% of transactions that received a `send_reminder_sms`, `suggest_alternate_payment_method`, or `send_b2b_payment_reminder` action, simulate the customer "responding" with a promised payment date (2–10 days out). Insert into `promises_to_pay`.
- Of those promises, simulate ~65% being fulfilled by the promised date (mark `fulfilled = true`, and correspondingly mark the original transaction as recovered/success in a `recovered` boolean you add to `transactions` or compute at report time).
- For unfulfilled promises past their date, mark `follow_up_sent = true` and log a new `actions_log` entry (a follow-up reminder), respecting the same attempt cap and stop rules.

### 6.7 Metrics engine (`metrics.py`)
Compute and print/export (as `report.json` and shown in the dashboard):
- Total transactions in batch, total revenue at risk (sum of amounts on all flagged transactions)
- Total amount recovered (sum of amounts on transactions that ended up "recovered" via promise fulfillment)
- Overall recovery rate (%) = recovered amount / at-risk amount
- Recovery rate broken down by failure_code
- % of diagnoses resolved by rule engine vs LLM fallback (this proves your AI-judgment discipline)
- Count and % of cases that hit `stop_contact` and why (opted_out vs max_attempts)
- Average attempts-to-recovery

### 6.8 Dashboard (`app.py`, Streamlit)
Single-page Streamlit app with:
- A "Run batch" button that regenerates data and runs the full pipeline (detect → diagnose → execute → track promises → metrics) live, so the panel sees it work end-to-end, not just cached output
- Headline metric cards: revenue at risk, amount recovered, recovery rate, rule-vs-LLM split
- A bar chart: recovery rate by failure_code
- A table of the audit trail (`actions_log`), filterable by transaction_id, with reasoning visible
- A small "compliance panel": count of stopped-for-opt-out and stopped-for-max-attempts cases, to visually prove the guardrails work
- A "promise-to-pay" table showing promised dates, fulfilled/unfulfilled status, follow-ups sent

### 6.9 Deliberate failure case study (do this for real, then document it)
Introduce and then fix a real bug — pick one of these (or a real one you actually hit) and document it exactly as it happened in `FAILURE_LOG.md`:
- **Duplicate messaging**: initially the executor doesn't check whether an action was already logged for a transaction+attempt combination, so re-running the pipeline sends two reminders for the same attempt. Fix: add a uniqueness constraint / idempotency check on `(transaction_id, attempt_number)` before logging a new action.
- **LLM over-confidence**: the LLM fallback initially returns high confidence on bad classifications for edge cases (e.g. classifying an already-refunded transaction as "insufficient_funds"). Fix: add a confidence threshold and a sanity-check rule that overrides the LLM if the transaction status contradicts its output.
- **Race condition on stopping rules**: a customer who is both `customer_opted_out` and about to get a `send_mandate_renewal_link` slips through because the opt-out check was applied after the action was already chosen, not before. Fix: move the opt-out check to the very start of `execute.py`, before any diagnosis-to-action mapping is used.

`FAILURE_LOG.md` should contain: what broke, how you noticed it (a log line, a wrong metric, a duplicate row), the root cause, and the fix, with a before/after code snippet.

## 7. AI / LLM integration details

### 7.1 Model & API
- Use the Anthropic API (`claude-sonnet-4-6` or whichever current small/fast model is available) via a simple wrapper function `call_llm(prompt: str) -> str`.
- Read the API key from an environment variable (`ANTHROPIC_API_KEY`); never hardcode it. If no key is present, the system must still run end-to-end by falling back to rule-only diagnosis and a template-based (non-LLM) message generator — **do not let the whole demo break if there's no API key**. Log clearly "LLM unavailable, using deterministic fallback" so the graceful-degradation behavior is itself visible in the audit trail — this is good defensive engineering to point out in the pitch.

### 7.2 Prompts (use structured, low-temperature calls; always ask for JSON output and validate/parse it defensively)

**Diagnosis fallback prompt (only for ambiguous cases):**
```
You are a payment-recovery diagnosis assistant for an Indian fintech merchant.
Given this failed/abandoned transaction, return ONLY valid JSON with keys:
root_cause (string, one sentence), recommended_action (must be exactly one of:
send_reminder_sms, send_update_card_link, suggest_alternate_payment_method,
retry_silently, send_mandate_renewal_link, send_b2b_payment_reminder,
escalate_to_human), confidence (float 0-1).

Transaction: {transaction_json}
```

**Recovery message generation prompt:**
```
Write a short, polite payment recovery message (SMS-length, under 300 characters)
for an Indian customer. Tone: {tone} (professional | friendly Hinglish).
Context: payment of ₹{amount} failed due to {root_cause}. Recommended action for
the customer: {recommended_action_description}. Do not mention internal system
details, confidence scores, or that this was AI-generated. Return only the message text.
```

### 7.3 Guardrails
- Validate every LLM JSON response against a schema before using it. On parse failure or invalid `recommended_action`, force `escalate_to_human` and log the raw LLM output for debugging in the audit trail.
- Never let the LLM choose a dollar amount, a discount, or anything financial — those stay hardcoded/rule-driven. The LLM only classifies and writes copy.

## 8. Tech stack

- **Language:** Python 3.11+
- **Data/DB:** SQLite (stdlib `sqlite3`), `pandas` for CSV export/analysis
- **Synthetic data:** `Faker`
- **LLM:** `anthropic` Python SDK
- **Dashboard:** `streamlit`, `plotly` or `streamlit`'s built-in charts for the bar chart
- **Testing:** `pytest` for at least: detection rules, action-menu validation, stopping-rule enforcement, idempotency fix (regression test for the bug in §6.9)
- **Env management:** `requirements.txt` + `.env.example` (never commit a real `.env`)

## 9. Repository structure

```
recoverai/
├── README.md
├── PRD.md                      (this file, kept in repo for context)
├── FAILURE_LOG.md
├── requirements.txt
├── .env.example
├── data/
│   └── transactions.csv        (generated, gitignored except a sample)
├── recovery.db                 (generated, gitignored)
├── src/
│   ├── generate_data.py
│   ├── detect.py
│   ├── diagnose.py
│   ├── execute.py
│   ├── ptp_tracker.py
│   ├── metrics.py
│   ├── llm_client.py
│   ├── db.py                   (schema + connection helpers)
│   └── constants.py             (fixed action menu, rule tables)
├── app.py                       (Streamlit dashboard, entry point)
├── run_pipeline.py              (CLI: runs the full pipeline end-to-end, prints report.json)
├── tests/
│   ├── test_detect.py
│   ├── test_execute.py
│   └── test_idempotency.py
└── report.json                  (generated after each run)
```

## 10. README requirements

The README must include, in this order:
1. One-paragraph problem statement (why revenue recovery matters for a merchant)
2. Architecture diagram (Mermaid flowchart: data → detect → diagnose (rule/LLM split shown) → bounded execute → audit log + promise tracker → metrics)
3. Setup instructions (`pip install -r requirements.txt`, set `ANTHROPIC_API_KEY`, `python src/generate_data.py`, `python run_pipeline.py` or `streamlit run app.py`)
4. **Headline results from an actual run** (fill this in after running it — do not leave placeholder numbers): revenue at risk, amount recovered, recovery rate, % rule vs LLM
5. A short "How this satisfies the buildathon bar" section explicitly mapping features to Problem Taste / Build Quality / AI Judgment / Failure Recovery
6. A "What I'd build next with real Razorpay APIs" section (2-3 sentences: swap the mock executor for Razorpay's test-mode payment retry + notification APIs)
7. Link to the 5-minute pitch video (leave a placeholder to fill in)

## 11. Acceptance criteria (the agent should self-check against these before declaring done)

- [ ] `python src/generate_data.py` produces a fresh batch of 150–300 transactions with the specified distributions
- [ ] `python run_pipeline.py` runs detect → diagnose → execute → ptp_tracker → metrics end-to-end without errors, using only a batch (not a single hardcoded transaction), and prints/exports `report.json` with non-zero, non-fabricated numbers
- [ ] At least 80% of diagnoses are resolved by the rule engine, not the LLM (log this ratio)
- [ ] Every customer-facing action respects the 3-attempt cap and opt-out flag — provable via a passing test in `tests/test_execute.py`
- [ ] Re-running the pipeline on the same data does not create duplicate actions for the same transaction+attempt (idempotency test passes)
- [ ] `streamlit run app.py` launches a working dashboard showing live metrics and the audit trail table
- [ ] `FAILURE_LOG.md` documents one real bug (not fabricated) with before/after fix
- [ ] The system runs end-to-end even with no `ANTHROPIC_API_KEY` set (graceful fallback), and this fallback is visibly logged
- [ ] README contains real, run-derived numbers, not placeholders
- [ ] No code path allows an unbounded or unlogged financial action

## 12. Suggested build order (for the agent to execute in sequence)

1. `db.py` + `constants.py` (schema and fixed lookup tables)
2. `generate_data.py` → verify with a quick `pandas` sanity check on distributions
3. `detect.py` → unit test the four rules
4. `llm_client.py` (with the no-API-key fallback path built in from the start, not bolted on later)
5. `diagnose.py` → verify the ≥80% rule-resolved ratio on a real generated batch
6. `constants.py` action menu + `execute.py` with stopping rules → write `test_execute.py` and `test_idempotency.py` alongside this, not after
7. `ptp_tracker.py`
8. `metrics.py` → produce `report.json` from a real run
9. `app.py` Streamlit dashboard wired to the same pipeline functions (no duplicated logic between CLI and dashboard)
10. Run the full thing, deliberately trigger and fix the chosen bug from §6.9, write `FAILURE_LOG.md`
11. Write the final README with real numbers and the Mermaid diagram
12. Record the 5-minute pitch video (outside the scope of the agent, but leave a clear placeholder/script outline in README)

---

**Build this as if it will actually be judged live by a panel who will ask "walk me through what happens when a payment fails" and expect you to trace it through real code and real logged output — not slides.**
