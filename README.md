# RecoverAI — Autonomous Revenue Recovery Platform

<div align="center">

[![Razorpay AI Buildathon](https://img.shields.io/badge/Razorpay%20Buildathon%202026-Track%2003%3A%20AI%20Revenue%20Recovery-blue?style=for-the-badge)](https://razorpay.com)
[![Tests](https://img.shields.io/badge/Tests-45%2F45%20Passing%20(100%25)-brightgreen?style=for-the-badge&logo=pytest)](file:///tests/)
[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](file:///LICENSE)

**An autonomous, policy-bounded revenue recovery engine for Indian fintech, digital merchants, and SaaS platforms.**  
*Recovers failed payments intelligently using Expected Recovery Value (ERV) optimization, strict deterministic guardrails, and cryptographic SHA-256 audit chaining.*

[Architecture](#core-architectural-innovations) • [3-Way Benchmark](#empirical-3-way-benchmark) • [Quickstart](#quickstart--installation) • [Evaluator Demo](#evaluator-demo-script-2-3-minutes) • [Razorpay Integration](#razorpay-production-integration-path)

</div>

---

## Executive Summary

Failed payments cost Indian digital businesses billions annually. Standard recovery systems rely on either **blunt naive retries** (which spam users and trigger fraud blocks) or **unconstrained AI agents** (which risk financial hallucinations and compliance violations).

**RecoverAI** establishes a new standard for autonomous fintech operations:

> **"AI assists reasoning; deterministic systems authorize financial execution."**

In RecoverAI, Large Language Models (LLMs) have **zero direct execution authority**. AI is strictly quarantined to root-cause classification of ambiguous failures and empathetic bilingual copy generation. Every state transition, communication attempt cap ($\le 3$), quiet-hours freeze, and settlement verification is governed by a **deterministic state machine** and **mathematical optimization**.

---

## The 5-Stage Autonomous Recovery Pipeline

```text
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  1. DETECT   │ ──> │ 2. DIAGNOSE  │ ──> │  3. DECIDE   │ ──> │  4. EXECUTE  │ ──> │  5. VERIFY   │
│ Ingest fails │     │ Rule (≥80%)  │     │ ERV Ranking  │     │ Policy Gate  │     │ Settlement   │
│ & churn risk │     │ + AI Fallback│     │ Math Model   │     │ & Dispatch   │     │ Gateway Lock │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
```

1. **Detect (`src/detect.py`)**: Continuously monitors failed charges, abandoned checkouts, failed subscription renewals, and overdue B2B invoices.
2. **Diagnose (`src/diagnose.py`)**: Evaluates failure codes (`insufficient_funds`, `auth_failed`, `network_timeout`). Resolves $\ge 80\%$ deterministically via rule lookups; routes ambiguous anomalies to an LLM fallback classifier.
3. **Decide (`src/decision.py`)**: Computes **Expected Recovery Value (ERV)** for each candidate action, weighing historical recovery likelihood against direct communication costs, customer friction, and churn risk.
4. **Execute (`src/execute.py`)**: Validates the top-ranked action against the **Central Deterministic Policy Engine** (`src/policy.py`). If approved, logs a cryptographically chained event and dispatches the action (Silent Retry, WhatsApp Smart Link, SMS, or Human Escalation).
5. **Verify (`src/verify.py`)**: Enforces strict closed-loop settlement confirmation. A transaction is **never** marked recovered upon action dispatch—only after cryptographically verified gateway settlement (`payment.captured` / `order.paid`).

---

## Core Architectural Innovations

### 1. Deterministic Policy Guardrails (Zero Hallucinations)
A single, immutable policy authorization gate (`src/policy.py`) intercepts every proposed action before execution:
- **Opt-Out Halts**: If a customer opts out, outreach terminates instantly across all channels.
- **Strict Contact Cap**: Maximum of $3$ customer-facing contacts per recovery cycle. Technical silent retries bypass contact count.
- **Quiet Hours Enforcement**: No customer notifications dispatched between 21:00 and 09:00 IST.
- **Terminal State Locks**: Once a transaction is `RECOVERED` or `STOPPED`, it cannot be re-opened or re-charged.

### 2. Expected Recovery Value (ERV) Engine
Rather than applying static rules or raw LLM prompts, action selection is framed as an optimization problem:

```text
ERV(action) = [ P(recovery | failure, channel, attempt) × Transaction_Amount ]
              - Direct_Action_Cost
              - Customer_Friction_Penalty
              - Churn_Risk_Weight
```

The action with the highest positive ERV is selected. If policy blocks it, the engine gracefully falls back to the next-best permitted action and records explicit counterfactual explanations.

### 3. Tamper-Evident SHA-256 Cryptographic Audit Ledger
Financial auditability requires provable event sequencing. Every diagnostic evaluation, policy check, and action execution is cryptographically hashed:

```text
event_hash = SHA256( timestamp | transaction_id | action_type | reasoning | attempt_number | previous_hash )
```

Linking each event to `previous_hash` creates an immutable hash chain in SQLite (`src/db.py`). The dashboard includes an **Integrity Verification Tool** that traverses the ledger in milliseconds and pinpoints any altered records or broken links.

### 4. Dual-Metric Discipline
RecoverAI strictly distinguishes financial recovery from operational volume:
- **Revenue Recovery Rate**: `(Verified Recovered INR / Total INR at Risk) × 100` *(Primary Financial KPI)*
- **Transaction Recovery Rate**: `(Verified Recovered Transactions / Total Failed Transactions) × 100` *(Secondary Operational Indicator)*
- **Net Recovered Value (NRV)**: `Verified Recovered INR - Modeled Communication & Escalation Costs`

---

## Empirical 3-Way Benchmark

RecoverAI includes a fully reproducible evaluation benchmark (`run_evaluation.py`) running across **200 identical synthetic transactions** (Seed: `42`).

| Evaluation Metric | Naive Retry Strategy | Static Rule Strategy | RecoverAI Autonomous Platform | Performance Uplift |
|:---|:---:|:---:|:---:|:---:|
| **Verified Revenue Recovered** | ₹57,840 | ₹157,690 | **₹220,300** | **+39.7% vs Rules** (+280.9% vs Naive) |
| **Revenue Recovery Rate** | 12.8% | 34.9% | **48.8%** | **+13.9 percentage points** |
| **Transaction Recovery Rate** | 14.5% | 36.5% | **51.0%** | **+14.5 percentage points** |
| **Modeled Recovery Costs** | ₹9,630 | ₹8,760 | **₹12,180** | Optimized economic allocation |
| **Net Recovered Value (NRV)** | ₹48,210 | ₹148,930 | **₹208,120** | **+₹59,190 Net Profit Gain** |
| **Policy Violations** | 412 (Spam / Over-limit) | 46 (Channel Mismatch) | **0 (Zero)** | **100% Policy Compliant** |
| **Deterministic Diagnosis Share** | 0.0% | 100.0% | **88.5%** | **Target $\ge 80\%$ exceeded** |
| **Customer Contact Attempts** | 2.94 / recovery | 1.62 / recovery | **1.14 / recovery** | **61% lower customer fatigue** |

*All runs are strictly deterministic and reproducible across any environment.*

---

## Architectural Boundaries: REAL vs. SIMULATED

Fintech systems require absolute clarity regarding production readiness:

| Subsystem | Status | Implementation Details |
|:---|:---:|:---|
| **Deterministic Policy Engine** | **REAL** | Central authorization gate (`src/policy.py`) with opt-out halts, contact caps, quiet hours, and channel validation. |
| **Recovery State Machine** | **REAL** | Finite state machine (`src/state_machine.py`) with transition validation and terminal locks. |
| **ERV Decision Engine** | **REAL** | Mathematical optimization ranking candidate actions with counterfactual rejections (`src/decision.py`). |
| **Cryptographic Audit Trail** | **REAL** | SHA-256 hash chaining with automated tamper-detection validator (`src/db.py`). |
| **FastAPI Backend & OpenAPI** | **REAL** | Production-ready REST endpoints (`server.py`) with interactive docs at `/docs`. |
| **RazorSense Web Dashboard** | **REAL** | Fintech dashboard (`web/index.html`, `web/blade-theme.css`, `web/app.js`) matching Razorpay's design system. |
| **AI Fallback & Hinglish Copy** | **REAL** | Dual-tier LLM integration (`src/llm_client.py`) connecting to Groq / Claude with local rule templates. |
| **Synthetic Transaction Stream** | **SIMULATED** | Seeded generation (`src/generate_data.py`) modeling UPI, Card, Netbanking, and B2B Invoice failure distributions. |
| **Settlement Webhooks** | **SIMULATED** | Gateway capture webhook simulation (`payment.captured`, `order.paid`) validating signature interfaces. |
| **Communication Unit Costs** | **SIMULATED** | Industry cost model: SMS ₹0.25, WhatsApp ₹0.50, Silent Retry ₹0.02, Human Escalation ₹15.00. |

---

## Quickstart & Installation

### Prerequisites
- Python 3.11+
- Git & SQLite3 (standard library)

### 1. Clone & Install
```bash
git clone https://github.com/kishansingh7x/RecoverAI-Autonomous-Revenue-Recovery-Platform.git
cd RecoverAI-Autonomous-Revenue-Recovery-Platform

# Install production dependencies
pip install -r requirements.txt
```

### 2. Run the Test Suite (45 Tests)
```bash
pytest -v
```
*Validates 100% of policy rules, state transitions, ERV math, SHA-256 hash chaining, API endpoints, and edge cases.*

### 3. Run the Standalone 3-Way Benchmark CLI
```bash
python run_evaluation.py --seed 42 --count 200
```

### 4. Start the Web Dashboard
```bash
python server.py
```

---

## Evaluator Demo Script (2–3 Minutes)

Follow these 5 steps to verify all core capabilities in the web interface:

1. **Inspect Executive Financial Metrics (Top Bar)**:
   - Verify the separation of **Verified Recovered Revenue** (Primary KPI) vs. **Recovered Transactions** (Secondary KPI).
   - Observe the **Net Recovered Value (NRV)** displaying direct deductions for modeled SMS, WhatsApp, and retry costs.
2. **Execute the 3-Way Empirical Benchmark**:
   - Scroll to the **3-Way Recovery Evaluation Benchmark** panel.
   - Click **Run 3-way benchmark** (Seed: 42, Count: 200).
   - Verify the live performance comparison: RecoverAI achieves $+39.7\%$ revenue uplift with **zero policy violations**.
3. **Inspect the "Why This Action?" Decision Drawer**:
   - In the **Operations Audit Ledger**, click the **Why this?** button on any transaction.
   - Inspect the live ERV breakdown table ($P(\text{recovery})$, Direct Cost, Friction Penalty) and the **Deterministic Policy Guardrail Audit**.
4. **Verify Cryptographic SHA-256 Audit Integrity**:
   - Click the **Verify** badge next to the SHA-256 Hash Chain indicator.
   - Confirm that the modal verifies every hash link across the entire database in milliseconds.
5. **Test Edge Cases in the Scenario Studio**:
   - Scroll to **Test a Recovery Scenario**.
   - Select `insufficient_funds` and check **"Customer explicitly requested communication opt-out"**.
   - Click **Evaluate scenario** to observe immediate deterministic halt (`BLOCKED: Customer opted out`).

---

## Razorpay Production Integration Path

In a live production environment, RecoverAI binds directly to Razorpay's developer platform:

```text
Razorpay Gateway Webhooks (payment.failed, order.paid)
       │
       ▼
[ RecoverAI Detection & Policy Engine ]
       │
       ├─► Silent Retries ───────────────► Razorpay Subscriptions Recurring Charge API
       ├─► WhatsApp Smart Links ─────────► Razorpay Payment Links API (rzp.io/pay)
       ├─► Dynamic Gateway Failover ─────► Razorpay Optimizer Intelligent Routing
       └─► Settlement Confirmation ──────► Razorpay Webhook Signature Verification
```

1. **Razorpay Webhooks API**: Ingests real-time events (`payment.failed`, `order.paid`, `invoice.expired`) directly into the detection and verification gates.
2. **Razorpay Payment Links & Smart Collect**: Dispatches dynamic, short-lived UPI deep links via WhatsApp Business API.
3. **Razorpay Subscriptions**: Triggers auto-debit retries and generates recurring mandate update links.
4. **Razorpay Optimizer**: Dynamically routes retried transactions across alternate acquiring banking gateways to circumvent bank downtimes.

---

## Repository Structure

```
RecoverAI-Autonomous-Revenue-Recovery-Platform/
├── server.py                   # FastAPI REST API & RazorSense dashboard server
├── run_evaluation.py           # Standalone 3-way reproducible benchmark CLI
├── run_pipeline.py             # 5-stage end-to-end recovery pipeline CLI
├── requirements.txt            # Python dependencies
├── vercel.json                 # Vercel serverless deployment configuration
├── data/
│   └── seed_recovery.db        # Pre-packaged 200-transaction benchmark database
├── src/
│   ├── policy.py               # Central deterministic policy authorization engine
│   ├── state_machine.py        # Financial recovery state machine & terminal locks
│   ├── decision.py             # Expected Recovery Value (ERV) engine & counterfactuals
│   ├── verify.py               # Settlement verification & lifecycle validation
│   ├── evaluation.py           # 3-way comparative benchmark simulator
│   ├── db.py                   # SQLite schema & SHA-256 cryptographic audit chaining
│   ├── metrics.py              # Dual recovery rates, NRV, and modeled cost engine
│   ├── detect.py               # Revenue-at-risk detection rules
│   ├── diagnose.py             # Rule-first (≥80%) + LLM fallback diagnosis
│   ├── execute.py              # Action dispatcher with audit chain generation
│   ├── ptp_tracker.py          # Promise-to-Pay tracking & follow-up scheduler
│   ├── llm_client.py           # Groq LPU / Claude client with template fallbacks
│   └── constants.py            # Action menus, policy limits, & economic cost model
├── tests/                      # 45 Automated Pytest Test Suites (100% Passing)
└── web/                        # RazorSense Fintech Web UI
    ├── index.html              # Recovery dashboard single-page interface
    ├── blade-theme.css         # Razorpay RazorSense fintech styling & tokens
    └── app.js                  # UI event controller, modals, & live API bindings
```

---

## License

Distributed under the **MIT License**. See `LICENSE` for more information.

---

<div align="center">

**RecoverAI** • Developed for the **Razorpay AI Buildathon 2026**  
*Track 03: AI Revenue Recovery*

</div>
