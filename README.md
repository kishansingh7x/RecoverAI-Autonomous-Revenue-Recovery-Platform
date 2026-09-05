# RecoverAI — Autonomous Revenue Recovery Platform

**Track 03: AI Revenue Recovery • Razorpay AI Buildathon 2026**  
**Author:** Kishaan, B.Tech CSIT 2029  
**Live System:** FastAPI Backend + RazorSense-Inspired Fintech Dashboard  
**Test Suite:** 45 Automated Unit & Integration Tests (100% Passing)

---

## 1. Executive Summary & Core Philosophy

RecoverAI is an autonomous financial operations platform built for Indian digital merchants, SaaS platforms, and B2B enterprises to recover failed payments without customer fatigue or unauthorized execution.

### Architectural Philosophy:
> **"AI assists reasoning; deterministic systems authorize financial execution."**

In RecoverAI, Large Language Models (LLMs) have **zero direct execution authority**, cannot alter ledger state directly, and cannot bypass deterministic policy bounds. AI is used strictly for root-cause classification of ambiguous failures and empathetic bilingual copy generation. All financial state transitions, contact attempt caps, opt-out halts, and settlement verifications are governed by mathematical optimization and deterministic state machines.

---

## 2. REAL vs. SIMULATED Architectural Boundaries

To maintain strict fintech engineering integrity, RecoverAI explicitly distinguishes between production-grade logic and simulated integration points:

| Component / Subsystem | Status | Implementation Details |
|---|---|---|
| **Deterministic Policy Engine** | **REAL** | Single central authorization gate (`src/policy.py`). Enforces opt-out halts, contact caps ($\le 3$), quiet hours (21:00–09:00 IST), channel eligibility, and idempotency. |
| **Recovery Domain State Machine** | **REAL** | Finite state machine with validated transition matrix (`src/state_machine.py`). Enforces terminal state locks (`RECOVERED`, `STOPPED`) and supervisor override for `ESCALATED`. |
| **Payment Verification Engine** | **REAL** | Strict lifecycle separation (`src/verify.py`): `ACTION_DISPATCHED` $\to$ `PAYMENT_PENDING` $\to$ `PAYMENT_SUCCESS_VERIFIED` $\to$ `RECOVERED`. Dispatched actions are never conflated with recovered money. |
| **Expected Recovery Value (ERV) Engine** | **REAL** | Mathematical optimization (`src/decision.py`) computing $\text{ERV}(a) = P(a) \times \text{Amount} - \text{Cost}(a) - \text{Friction}(a) - \text{Risk}(a)$. Ranks actions and generates counterfactual rejection rationales. |
| **Tamper-Evident SHA-256 Audit Chain** | **REAL** | Cryptographic hash chaining (`src/db.py`) over canonical event blocks: $\text{SHA256}(\text{timestamp}\|\text{txn\_id}\|\text{action}\|\text{reasoning}\|\text{attempt}\|\text{prev\_hash})$. Measures runtime and pinpoints exact tampered rows. |
| **Reproducible 3-Way Benchmark** | **REAL** | Deterministic comparative benchmark engine (`src/evaluation.py` & `run_evaluation.py`). Evaluates Naive Retry vs. Static Rules vs. RecoverAI on identical seeds. Zero hardcoded results. |
| **FastAPI REST API & OpenAPI Docs** | **REAL** | Full REST backend (`server.py`) serving Swagger interactive docs at `/docs` with CORS, cache control, and Pydantic validation. |
| **RazorSense Fintech Dashboard** | **REAL** | Modern, accessible UI (`web/index.html`, `web/blade-theme.css`, `web/app.js`) matching Razorpay's RazorSense visual design guidelines. |
| **AI Fallback & Hinglish Generator** | **REAL** | Dual-tier LLM integration (`src/llm_client.py`) connecting to Groq LPU (Llama 3.3 70B) or Claude 3.5 Sonnet with deterministic template fallbacks. |
| **Synthetic Transaction Generator** | **SIMULATED** | Seeded synthetic generator (`src/generate_data.py`) simulating realistic distributions across UPI, Card, Netbanking, and B2B Invoices. |
| **Settlement Webhook Events** | **SIMULATED** | Simulates asynchronous payment gateway capture webhooks (`payment.captured`, `order.paid`) with provider signature verification interface. |
| **Economic Communication Costs** | **SIMULATED** | Configurable industry cost model (`src/constants.py`): SMS ₹0.25, WhatsApp ₹0.50, Silent Retry ₹0.02, LLM ₹0.05, Escalation ₹15.00. |
| **Customer Support Call-Back Queue** | **SIMULATED** | Demonstrates human escalation workflow with simulated specialist dispatch queue and live countdown timer. |

---

## 3. Metric Formulations

RecoverAI strictly separates primary financial recovery metrics from secondary operational indicators:

### 1. Primary Financial KPI: Revenue Recovery Rate
$$\text{Revenue Recovery Rate (\%)} = \frac{\text{Verified Recovered Revenue (INR)}}{\text{Revenue at Risk (INR)}} \times 100$$
Measures actual money recovered from genuine payment failures. Actions dispatched or customer promises are **never** counted as revenue until verified.

### 2. Secondary Operational KPI: Transaction Recovery Rate
$$\text{Transaction Recovery Rate (\%)} = \frac{\text{Verified Recovered Transactions (\#)}}{\text{Transactions at Risk (\#)}} \times 100$$
Measures resolution volume across low-value vs. high-value payment attempts.

### 3. Net Recovered Value (NRV)
$$\text{Net Recovered Value (NRV)} = \text{Verified Recovered Revenue} - \sum \text{Modeled Recovery Costs}$$
Accounts for direct communication costs, technical retry overhead, customer fatigue penalties, and human escalation costs.

### 4. Deterministic Diagnosis Share
$$\text{Deterministic Share (\%)} = \frac{\text{Diagnoses Resolved by Deterministic Rules}}{\text{Total Diagnoses}} \times 100 \quad (\text{Target: } \ge 80\%)$$

---

## 4. Quickstart & Testing

### Prerequisites
- Python 3.11+ (Tested on Python 3.14)
- SQLite3 (built-in standard library)

### 1. Installation
```bash
# Clone or navigate to the repository
cd "Razorpay Project"

# Install dependencies
pip install -r requirements.txt
```

### 2. Run the Test Suite (45 Tests)
```bash
pytest -v
```
All 45 automated unit and integration tests validate state machines, verification gates, policy guardrails, ERV calculations, SHA-256 tamper detection, server endpoints, and edge cases.

### 3. Run the Reproducible Benchmark CLI
```bash
python run_evaluation.py --seed 42 --count 200
```
Outputs a live 3-way comparative evaluation table comparing Naive Retry, Static Rules, and RecoverAI across identical transactions.

### 4. Start the Web Dashboard & API Server
```bash
python server.py
```
Open your browser to:
- **Dashboard:** [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **Interactive OpenAPI Explorer:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## 5. 2–3 Minute Evaluator Demo Script

For evaluators and panel judges reviewing this submission, follow these 5 steps to verify all core capabilities:

### Step 1: Inspect Dual Metrics & Net Recovered Value (Top Strip)
- Open [http://127.0.0.1:8000](http://127.0.0.1:8000).
- Notice the **Executive Financial Metrics**:
  - Primary Metric: **Verified Revenue Recovered** and **Revenue Recovery Rate %**.
  - Secondary Strip: **Recovered Transactions**, **Net Recovered Value (NRV)**, and **Modeled Recovery Cost** (with *Simulation Assumptions* disclosure).
  - Deterministic Diagnosis Share: Proves $\ge 80\%$ resolution without LLM dependency.

### Step 2: Run the 3-Way Empirical Benchmark Panel
- Scroll to the **"3-Way Recovery Evaluation Benchmark"** section.
- Set Seed = `42`, Count = `200`, and click **"Run 3-way benchmark"**.
- Observe live comparative metrics across all 3 strategies:
  - **Naive Retry:** High customer fatigue and hundreds of unsafe retries on hard declines.
  - **Static Rules:** Better recovery but static action mapping without channel or economic optimization.
  - **RecoverAI:** Highest recovery rate, $+39.70\%$ revenue uplift vs static rules ($+279.7\%$ vs naive), maximum NRV, and strictly **0 policy violations**.

### Step 3: Inspect "Why This Action?" Decision & ERV Inspector
- Scroll to the **Operations Audit Ledger**.
- Click the **"Why this?"** button on any transaction row.
- The **Decision Inspector Drawer** slides out, displaying:
  - Root-cause diagnosis and confidence score.
  - **Candidate Actions & ERV Table**: Mathematical breakdown of $P(\text{rec})$, Direct Cost, Friction Penalty, and final Expected Recovery Value for every menu action.
  - **Deterministic Policy Guardrail Audit**: Validated checks for Opt-Out, Attempt Cap ($\le 3$), Quiet Hours, and Allowlist.
  - **Counterfactual Explanations**: Plain-English rationale for why competing actions were rejected.

### Step 4: Verify Cryptographic SHA-256 Audit Integrity
- In the Operations Audit Ledger header, locate the **"SHA-256 Hash Chain: Active"** status badge.
- Click **"Verify"**.
- A modal confirms that every record is chained cryptographically: $\text{SHA256}(\dots\|\text{prev\_hash})$.
- Displays total events verified, verification runtime in milliseconds, Genesis hash, and Head hash.

### Step 5: Test the Scenario Decision Studio
- Scroll to **"Test a Recovery Scenario"**.
- Select `insufficient_funds` with 0 attempts: Observe deterministic SMS recommendation.
- Check the **"Customer explicitly requested communication opt-out"** box and click **"Evaluate scenario"**:
  - The deterministic policy engine immediately halts outreach (`BLOCKED: Customer opted out`).
- Select `unlisted_ambiguous_payment_drop`:
  - Triggers AI fallback diagnosis and reveals the **Priority Support Assistant & Call-Back Workflow**.

---

## 6. Project Directory Structure

```
Razorpay Project/
├── server.py                        # FastAPI Backend & OpenAPI endpoint server
├── run_evaluation.py                # Standalone reproducible 3-way benchmark CLI runner
├── run_pipeline.py                  # End-to-end 5-stage pipeline runner CLI
├── requirements.txt                 # Project dependencies
├── report.json                      # Exported headline recovery & economic metrics
├── tests/                           # 45 Automated Pytest Test Suites
│   ├── test_state_machine.py        # Validated state transitions & terminal locks
│   ├── test_verify.py               # Payment verification & settlement simulation
│   ├── test_policy.py               # 12 Deterministic policy guardrails
│   ├── test_decision.py             # ERV mathematical calculation & counterfactuals
│   ├── test_evaluation.py           # Reproducible benchmark engine verification
│   ├── test_audit_chain.py          # SHA-256 cryptographic chain & tamper detection
│   ├── test_server_endpoints.py     # FastAPI endpoints & dashboard integration
│   ├── test_edge_cases.py           # Zero amounts, attempt caps, 404 boundaries
│   ├── test_detect.py               # Risk detection rules
│   ├── test_execute.py              # Recovery action dispatch & idempotency
│   └── test_support.py              # Support chat & priority callback queue
├── src/                             # Core Domain & Recovery Architecture
│   ├── state_machine.py             # Recovery state machine & transition table
│   ├── verify.py                    # Verification engine & settlement validator
│   ├── policy.py                    # Centralized deterministic policy engine
│   ├── decision.py                  # ERV economic decisioning & counterfactuals
│   ├── evaluation.py                # 3-way benchmark engine & outcome simulator
│   ├── db.py                        # SQLite schema, indices, & SHA-256 audit chaining
│   ├── metrics.py                   # Dual recovery rates, NRV, & modeled cost engine
│   ├── detect.py                    # Deterministic risk flag detection
│   ├── diagnose.py                  # Rule-first (≥80%) + LLM fallback diagnosis
│   ├── execute.py                   # Action dispatcher with SHA-256 chaining
│   ├── ptp_tracker.py               # Promise-to-Pay tracking & follow-up scheduler
│   ├── llm_client.py                # Groq LPU / Claude client with template fallback
│   └── constants.py                 # Action menus, policy limits, & economic model
└── web/                             # RazorSense Fintech UI
    ├── index.html                   # Flagship RecoverAI Dashboard markup
    ├── blade-theme.css              # Custom RazorSense fintech design system
    └── app.js                       # Frontend controller & interactive integrations
```

---

## 7. What Would Connect to Live Razorpay APIs in Production

In a live production deployment, RecoverAI's mock execution and verification interfaces map directly to Razorpay's developer platform:

1. **Razorpay Webhooks API:** Ingest asynchronous gateway webhooks (`payment.failed`, `order.paid`, `invoice.expired`) directly into `src/detect.py` and `src/verify.py`.
2. **Razorpay Payment Links & Smart Collect:** Generate dynamic, short-lived UPI/Card payment links (`rzp.io/pay`) dispatched via official WhatsApp Business API endpoints.
3. **Razorpay Subscriptions & Recurring Charges:** Trigger auto-debit retries via Razorpay Subscriptions recurring charge endpoint and generate mandate update links.
4. **Razorpay Optimizer:** Dynamically route retried transactions across alternate acquiring bank gateways to bypass downtime.
