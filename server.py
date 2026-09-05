"""
RecoverAI High-Performance FastAPI Backend Server.
Powers the world-class RecoverAI Dashboard and provides full REST API for judges.
Serves interactive OpenAPI / Swagger docs at /docs and the web frontend at /.
"""

import sys
import os
import json
import time
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db import get_connection, DEFAULT_DB_PATH, ensure_db_schema
from src.constants import (
    RULE_LOOKUP_TABLE,
    MAX_CONTACT_ATTEMPTS,
    FIXED_ACTION_MENU,
    ACTION_RETRY_SILENTLY,
    ACTION_ESCALATE_TO_HUMAN,
    STOPPED_REASON_MAX_ATTEMPTS,
    STOPPED_REASON_OPTED_OUT,
    METHOD_RULE,
    METHOD_LLM_FALLBACK
)
from src.generate_data import generate_transactions
from src.detect import detect_revenue_at_risk
from src.diagnose import diagnose_transactions
from src.execute import execute_recovery_actions
from src.ptp_tracker import process_promises_to_pay
from src.metrics import calculate_metrics, REPORT_PATH
from src.llm_client import (
    is_llm_available,
    get_llm_provider,
    generate_recovery_message,
    diagnose_with_llm,
    answer_support_chat
)

# Ensure database schema is up-to-date
ensure_db_schema()

app = FastAPI(
    title="RecoverAI — Autonomous Revenue Recovery Agent API",
    description="REST API powering the RecoverAI Autonomous Revenue Recovery Platform (Razorpay AI Buildathon 2026, Track 03).",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_cache_control_header(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# Request Models
class PipelineRunRequest(BaseModel):
    count: int = Field(default=200, ge=50, le=500, description="Number of synthetic transactions to generate")
    seed: int = Field(default=42, ge=1, le=99999, description="Random seed for reproducibility")

class SandboxDiagnoseRequest(BaseModel):
    failure_code: str = Field(default="insufficient_funds", description="Payment failure code to diagnose")
    amount: float = Field(default=2499.00, ge=1.0, description="Transaction amount in INR")
    customer_name: str = Field(default="Rohan Verma", description="Customer full name")
    channel: str = Field(default="app", description="Transaction origin channel (app, web, b2b_invoice)")
    payment_method: str = Field(default="upi", description="Payment instrument (upi, card, netbanking)")
    customer_opted_out: bool = Field(default=False, description="Whether customer has opted out of communication")
    retry_count: int = Field(default=0, ge=0, le=10, description="Number of previous outreach attempts")

class SupportChatRequest(BaseModel):
    message: str = Field(..., description="Customer query or message")
    transaction_id: Optional[str] = Field(default=None, description="Related transaction ID if any")
    history: Optional[List[Dict[str, str]]] = Field(default=[], description="Chat conversation history")

class SupportCallbackRequest(BaseModel):
    customer_name: str = Field(default="Valued Customer", description="Customer full name")
    phone: str = Field(..., description="Customer phone number for callback")
    transaction_id: Optional[str] = Field(default="TXN_SUPPORT_DIRECT", description="Transaction ID")
    preferred_slot: str = Field(default="Immediate (within 5 mins)", description="Preferred callback slot")
    issue_summary: Optional[str] = Field(default="Payment assistance requested", description="Brief summary of issue")

class EvaluationRunRequest(BaseModel):
    seed: int = Field(default=42, ge=1, le=99999, description="Seed for reproducible benchmark generation")
    count: int = Field(default=200, ge=20, le=1000, description="Number of failed transactions to evaluate")

class VerificationSimulateRequest(BaseModel):
    event_type: str = Field(default="payment.captured", description="Settlement event type")
    auth_code: Optional[str] = Field(default="AUTH_SIM_001", description="Provider authorization code")



@app.get("/api/health")
def get_health() -> Dict[str, Any]:
    """Returns agent health, database status, and LLM connectivity."""
    db_exists = DEFAULT_DB_PATH.exists()
    return {
        "status": "healthy",
        "agent": "RecoverAI",
        "track": "Track 03: AI Revenue Recovery",
        "version": "1.0.0",
        "database_connected": db_exists,
        "llm_online": is_llm_available(),
        "llm_provider": get_llm_provider(),
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/metrics")
def get_metrics() -> Dict[str, Any]:
    """Returns headline recovery metrics, AI discipline split, and compliance stats."""
    ensure_db_schema(DEFAULT_DB_PATH)
    
    # Read pre-packaged or active report.json first for instant sub-millisecond response
    rep_path = REPORT_PATH if REPORT_PATH.exists() else (PROJECT_ROOT / "report.json")
    if rep_path.exists():
        try:
            with open(rep_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "recovery_economics" in data and "net_recovered_value_inr" in data.get("summary", {}):
                    return data
        except Exception:
            pass

    return calculate_metrics()


def execute_full_pipeline(count: int, seed: int) -> Dict[str, Any]:
    """Helper that runs all 5 pipeline stages and captures timings."""
    start_total = time.time()
    
    t0 = time.time()
    gen_result = generate_transactions(count=count, seed=seed)
    gen_time = round(time.time() - t0, 3)

    t0 = time.time()
    det_flags = detect_revenue_at_risk()
    det_time = round(time.time() - t0, 3)

    t0 = time.time()
    diag_res = diagnose_transactions()
    diag_time = round(time.time() - t0, 3)

    t0 = time.time()
    exec_res = execute_recovery_actions()
    exec_time = round(time.time() - t0, 3)

    t0 = time.time()
    ptp_res = process_promises_to_pay(seed=seed)
    ptp_time = round(time.time() - t0, 3)

    metrics = calculate_metrics()
    total_time = round(time.time() - start_total, 3)

    return {
        "total_time_sec": total_time,
        "timings": {
            "step1_generate": gen_time,
            "step2_detect": det_time,
            "step3_diagnose": diag_time,
            "step4_execute": exec_time,
            "step5_ptp": ptp_time
        },
        "step_details": {
            "transactions_generated": gen_result.get("total_generated", count),
            "risk_flags_detected": len(det_flags),
            "diagnoses_count": len(diag_res),
            "actions_executed": len(exec_res),
            "promises_fulfilled": ptp_res.get("fulfilled", 0)
        },
        "metrics": metrics
    }


@app.post("/api/pipeline/run")
def run_pipeline(payload: PipelineRunRequest) -> Dict[str, Any]:
    """
    Executes the full end-to-end 5-stage RecoverAI revenue recovery pipeline.
    Returns stage-by-stage timings, execution counters, and final metrics.
    """
    try:
        result = execute_full_pipeline(count=payload.count, seed=payload.seed)
        return {
            "success": True,
            "message": f"Pipeline executed successfully with {payload.count} transactions (seed={payload.seed})",
            **result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/transactions")
def get_transactions(
    limit: int = Query(default=100, ge=1, le=500),
    status: Optional[str] = None,
    channel: Optional[str] = None,
    at_risk_only: bool = False
) -> Dict[str, Any]:
    """Returns a list of transactions with their risk status, recovery state, and details."""
    conn = get_connection()
    cursor = conn.cursor()

    query = """
        SELECT 
            t.transaction_id,
            t.customer_id,
            t.customer_name,
            t.amount,
            t.payment_method,
            t.status,
            t.failure_code,
            t.channel,
            t.created_at,
            t.retry_count,
            t.customer_opted_out,
            t.recovered,
            rf.risk_type,
            d.root_cause,
            d.recommended_action,
            d.method AS diagnosis_source,
            d.confidence AS confidence_score
        FROM transactions t
        LEFT JOIN risk_flags rf ON t.transaction_id = rf.transaction_id
        LEFT JOIN diagnoses d ON t.transaction_id = d.transaction_id
        WHERE 1=1
    """
    params = []

    if at_risk_only:
        query += " AND rf.risk_type IS NOT NULL"
    if status:
        query += " AND t.status = ?"
        params.append(status)
    if channel:
        query += " AND t.channel = ?"
        params.append(channel)

    query += " ORDER BY t.created_at DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    items = [dict(row) for row in rows]
    return {"total": len(items), "transactions": items}


@app.get("/api/audit-trail")
def get_audit_trail(
    limit: int = Query(default=100, ge=1, le=500),
    action_type: Optional[str] = None,
    compliance_only: bool = False
) -> Dict[str, Any]:
    """Returns the immutable audit log of all automated actions and compliance halts."""
    conn = get_connection()
    cursor = conn.cursor()

    query = """
        SELECT 
            a.action_id,
            a.transaction_id,
            a.action_type,
            a.reasoning,
            a.message_sent,
            a.attempt_number,
            a.stopped_reason,
            a.timestamp AS executed_at,
            a.previous_hash,
            a.event_hash,
            t.customer_name,
            t.amount,
            t.failure_code,
            t.payment_method,
            t.channel
        FROM actions_log a
        LEFT JOIN transactions t ON a.transaction_id = t.transaction_id
        WHERE 1=1
    """
    params = []

    if compliance_only:
        query += " AND a.stopped_reason IS NOT NULL"
    if action_type:
        query += " AND a.action_type = ?"
        params.append(action_type)

    query += " ORDER BY a.timestamp DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    results = [dict(r) for r in rows]
    return {"total": len(results), "audit_trail": results}


@app.get("/api/audit/integrity")
def get_audit_integrity() -> Dict[str, Any]:
    """
    Cryptographically verifies the append-only SHA-256 audit ledger.
    Measures runtime performance and detects any out-of-band tampering.
    """
    from src.db import verify_audit_chain, GENESIS_HASH
    res = verify_audit_chain()
    res["valid"] = res.get("chain_valid", False)
    res["events_verified"] = res.get("events_checked", 0)
    res["verification_time_ms"] = res.get("measured_runtime_ms", 0.0)
    res["genesis_hash"] = GENESIS_HASH
    res["head_hash"] = res.get("latest_hash", GENESIS_HASH)
    return res


@app.post("/api/evaluation/run")
def run_evaluation_benchmark(payload: EvaluationRunRequest) -> Dict[str, Any]:
    """
    Triggers the reproducible 3-way comparative evaluation benchmark (Naive Retry vs. Static Rules vs. RecoverAI)
    using the specified seed and transaction count.
    """
    from src.evaluation import BenchmarkEngine
    engine = BenchmarkEngine(seed=payload.seed, count=payload.count)
    res = engine.execute_benchmark()
    # Add top-level aliases for direct access
    res["naive_retry"] = res["strategies"]["naive_retry"]
    res["static_rules"] = res["strategies"]["static_rules"]
    res["recover_ai"] = res["strategies"]["recoverai"]
    res["comparison"] = res["comparisons"]
    res["comparison"]["revenue_uplift_pct"] = res["comparisons"]["revenue_uplift_vs_static_pct"]
    return res


@app.get("/api/decision/{txn_id}")
def get_decision_inspection(txn_id: str) -> Dict[str, Any]:
    """
    Returns 'Why This Action?' inspection details:
    Transaction details, root cause, candidate actions with individual ERVs and policy checks.
    """
    from src.decision import EconomicDecisionEngine
    from src.db import get_connection

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.*, d.root_cause, d.recommended_action, d.method, d.confidence
        FROM transactions t
        LEFT JOIN diagnoses d ON t.transaction_id = d.transaction_id
        WHERE t.transaction_id = ?
    """, (txn_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Transaction '{txn_id}' not found.")

    txn_data = dict(row)
    diagnosis_data = {
        "root_cause": txn_data.get("root_cause") or txn_data.get("failure_code") or "unknown_drop",
        "method": txn_data.get("method") or "rule",
        "confidence": txn_data.get("confidence") or 1.0
    }

    result = EconomicDecisionEngine.evaluate_candidates(
        transaction=txn_data,
        diagnosis=diagnosis_data,
        attempt_number=max(1, txn_data.get("retry_count", 1)),
        current_hour=14
    )

    resp = result.to_dict()
    resp["transaction"] = {
        "transaction_id": txn_data.get("transaction_id"),
        "customer_name": txn_data.get("customer_name"),
        "amount": txn_data.get("amount"),
        "payment_method": txn_data.get("payment_method"),
        "channel": txn_data.get("channel"),
        "customer_opted_out": bool(txn_data.get("customer_opted_out", False)),
        "retry_count": txn_data.get("retry_count", 0),
        "recovery_state": txn_data.get("recovery_state", "FAILED"),
        "recovered": bool(txn_data.get("recovered", False))
    }
    return resp


@app.post("/api/verify/{txn_id}")
def verify_transaction_settlement(txn_id: str, payload: VerificationSimulateRequest) -> Dict[str, Any]:
    """
    Simulates a payment settlement event and transitions state to RECOVERED if validated.
    """
    from src.verify import VerificationEngine
    from src.db import get_connection

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT amount FROM transactions WHERE transaction_id = ?", (txn_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Transaction '{txn_id}' not found.")

    result = VerificationEngine.verify_settlement_event(
        transaction_id=txn_id,
        event_type=payload.event_type,
        amount=row["amount"],
        auth_code=payload.auth_code
    )
    return result.to_dict()


@app.get("/api/promises")
def get_promises(limit: int = Query(default=50, ge=1, le=200)) -> Dict[str, Any]:
    """Returns recorded promises-to-pay and their current fulfillment status."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            p.promise_id,
            p.transaction_id,
            p.promised_date,
            p.fulfilled,
            p.follow_up_sent,
            t.customer_name,
            t.amount,
            t.payment_method,
            t.channel
        FROM promises_to_pay p
        JOIN transactions t ON p.transaction_id = t.transaction_id
        ORDER BY p.promised_date DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()

    return {"total": len(rows), "promises": [dict(r) for r in rows]}


@app.post("/api/sandbox/diagnose")
def sandbox_diagnose(payload: SandboxDiagnoseRequest) -> Dict[str, Any]:
    """
    Interactive Judge Sandbox endpoint:
    Evaluates any transaction scenario live through the Rule Engine & LLM,
    verifies compliance guardrails, and renders personalized Hinglish & English copy.
    """
    code = payload.failure_code
    
    # 1. Check Deterministic Rule Table
    if code in RULE_LOOKUP_TABLE:
        diagnosis_source = "rule_engine"
        rule_data = RULE_LOOKUP_TABLE[code]
        root_cause = rule_data["root_cause"]
        recommended_action = rule_data["recommended_action"]
        confidence_score = 1.0
        reasoning = f"Matched deterministic rule lookup for '{code}'. High confidence, zero latency."
    else:
        # Fallback to LLM
        diagnosis_source = "llm_fallback"
        tx_mock = {
            "transaction_id": "test_sandbox_txn",
            "amount": payload.amount,
            "failure_code": code,
            "channel": payload.channel,
            "payment_method": payload.payment_method,
            "is_subscription": 0
        }
        llm_res = diagnose_with_llm(tx_mock)
        root_cause = llm_res.get("root_cause", "Unrecognized failure pattern")
        recommended_action = llm_res.get("recommended_action", ACTION_ESCALATE_TO_HUMAN)
        confidence_score = llm_res.get("confidence_score", 0.75)
        reasoning = llm_res.get("reasoning", "Diagnosed by Claude LLM fallback due to ambiguous failure pattern.")

    # 2. Check Compliance Guardrails
    compliance_passed = True
    compliance_reason = "Compliant. Within 3-attempt cap and customer is active."
    action_status = "executed"

    if payload.customer_opted_out:
        compliance_passed = False
        compliance_reason = "BLOCKED: Customer has opted out of notifications. Communication halted immediately."
        action_status = "stopped_opt_out"
    elif payload.retry_count >= MAX_CONTACT_ATTEMPTS:
        compliance_passed = False
        compliance_reason = f"BLOCKED: Reached maximum contact cap of {MAX_CONTACT_ATTEMPTS} attempts. Prevented customer fatigue."
        action_status = "stopped_max_attempts"
    elif recommended_action == ACTION_RETRY_SILENTLY:
        compliance_reason = "ALLOWED: Technical retry executed silently in the background without contacting the customer."
        action_status = "scheduled_silent_retry"

    # 3. Generate Personalized Recovery Copy
    action_desc = RULE_LOOKUP_TABLE.get(code, {}).get("action_description", root_cause)
    english_copy = generate_recovery_message(
        amount=payload.amount,
        root_cause=root_cause,
        recommended_action=recommended_action,
        action_description=action_desc,
        customer_name=payload.customer_name,
        tone="professional"
    )
    hinglish_copy = generate_recovery_message(
        amount=payload.amount,
        root_cause=root_cause,
        recommended_action=recommended_action,
        action_description=action_desc,
        customer_name=payload.customer_name,
        tone="friendly Hinglish"
    )

    return {
        "input": payload.model_dump(),
        "diagnosis": {
            "diagnosis_source": diagnosis_source,
            "root_cause": root_cause,
            "recommended_action": recommended_action,
            "confidence_score": confidence_score,
            "reasoning": reasoning
        },
        "compliance": {
            "passed": compliance_passed,
            "status": action_status,
            "decision": compliance_reason,
            "max_contact_cap": MAX_CONTACT_ATTEMPTS,
            "current_attempts": payload.retry_count
        },
        "copy": {
            "english": english_copy,
            "hinglish": hinglish_copy
        }
    }


@app.post("/api/support/chat")
def support_chat(payload: SupportChatRequest) -> Dict[str, Any]:
    """
    24x7 Customer Priority Support AI Chat endpoint.
    Answers payment queries, handles pending debit and refund questions,
    and flags cases requiring human intervention with a 1-click 'Request Call Back'.
    """
    try:
        response = answer_support_chat(
            message=payload.message,
            history=payload.history,
            transaction_id=payload.transaction_id
        )
        return {
            "success": True,
            "reply": response["reply"],
            "can_escalate": response["can_escalate"],
            "helpline": response["helpline"],
            "provider": response["provider"],
            "suggestions": response.get("suggestions", []),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "success": False,
            "reply": "Hum samajh sakte hain ki aapko dikkat aa rahi hai. Aap chahein toh turant niche se 'Request a Call Back' kar sakte hain ya helpline 1800-123-7729 dial kar sakte hain.",
            "can_escalate": True,
            "helpline": "1800-123-7729 (Toll-Free, 24x7)",
            "provider": "error_fallback",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


@app.post("/api/support/callback")
def schedule_support_callback(payload: SupportCallbackRequest) -> Dict[str, Any]:
    """
    'Request a Call Back' priority escalation endpoint.
    Queues a high-priority customer callback, generates an immutable audit entry,
    and provides real-time estimated wait time and ticket reference.
    """
    ticket_id = f"RZP-TKT-{uuid.uuid4().hex[:6].upper()}"
    now_iso = datetime.now().isoformat()

    conn = get_connection()
    cursor = conn.cursor()

    try:
        # 1. Insert into dedicated support_callbacks table
        cursor.execute("""
            INSERT INTO support_callbacks (
                ticket_id, customer_name, phone, transaction_id, preferred_slot, issue_summary, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)
        """, (
            ticket_id,
            payload.customer_name,
            payload.phone,
            payload.transaction_id,
            payload.preferred_slot,
            payload.issue_summary,
            now_iso
        ))

        # 2. Check if transaction_id exists in transactions table
        txn_id = payload.transaction_id or f"TXN_SP_{ticket_id}"
        cursor.execute("SELECT transaction_id FROM transactions WHERE transaction_id = ?", (txn_id,))
        txn_exists = cursor.fetchone() is not None

        if not txn_exists:
            # Create a placeholder transaction so audit trail foreign key constraint is satisfied
            cursor.execute("""
                INSERT OR IGNORE INTO transactions (
                    transaction_id, customer_id, customer_name, amount, payment_method,
                    status, failure_code, is_subscription, channel, created_at,
                    retry_count, customer_opted_out, recovered
                ) VALUES (?, 'cust_support_direct', ?, 0.0, 'upi', 'failed', 'unlisted_reason_human_escalation', 0, 'support_portal', ?, 0, 0, 0)
            """, (txn_id, payload.customer_name, now_iso))

        # 3. Log to tamper-evident actions_log audit trail with SHA-256 hash chaining
        from src.db import compute_event_hash, GENESIS_HASH
        cursor.execute("SELECT COALESCE(MAX(attempt_number), 0) + 1 FROM actions_log WHERE transaction_id = ?", (txn_id,))
        attempt_num = cursor.fetchone()[0]

        cursor.execute("SELECT event_hash FROM actions_log ORDER BY rowid DESC LIMIT 1")
        last_row = cursor.fetchone()
        prev_hash = last_row[0] if last_row and last_row[0] else GENESIS_HASH

        action_id = f"act_{uuid.uuid4().hex[:8]}"
        action_type = "escalate_to_human_callback"
        reasoning = f"Demo Callback Workflow requested by {payload.customer_name} ({payload.phone}) for Ticket {ticket_id}. Preferred Slot: {payload.preferred_slot}."
        event_hash = compute_event_hash(
            timestamp=now_iso,
            transaction_id=txn_id,
            action_type=action_type,
            reasoning=reasoning,
            attempt_number=attempt_num,
            previous_hash=prev_hash
        )

        cursor.execute("""
            INSERT INTO actions_log (
                action_id, transaction_id, action_type, reasoning, message_sent, attempt_number, stopped_reason, timestamp, previous_hash, event_hash
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
        """, (
            action_id,
            txn_id,
            action_type,
            reasoning,
            f"Support specialist assigned in demo simulation mode.",
            attempt_num,
            now_iso,
            prev_hash,
            event_hash
        ))

        conn.commit()
    except Exception as err:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to queue callback: {str(err)}")
    finally:
        conn.close()

    return {
        "success": True,
        "ticket_id": ticket_id,
        "customer_name": payload.customer_name,
        "phone": payload.phone,
        "preferred_slot": payload.preferred_slot,
        "estimated_wait": "3 to 5 minutes",
        "helpline": "1800-123-7729 (Toll-Free, 24x7)",
        "message": f"Callback scheduled successfully! Ticket reference: {ticket_id}. Our payment specialist will call you shortly.",
        "status": "queued",
        "timestamp": now_iso
    }


@app.get("/api/support/callbacks")
def get_support_callbacks(limit: int = Query(default=20, ge=1, le=100)) -> Dict[str, Any]:
    """Returns recently requested customer callbacks for operations monitoring."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ticket_id, customer_name, phone, transaction_id, preferred_slot, issue_summary, status, created_at
        FROM support_callbacks
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,))
    rows = cursor.fetchall()
    conn.close()
    return {"total": len(rows), "callbacks": [dict(r) for r in rows]}


# Static Frontend Mounting
WEB_DIR = PROJECT_ROOT / "web"
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

@app.get("/")
def serve_dashboard():
    """Serves the flagship RecoverAI web dashboard."""
    index_file = WEB_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return JSONResponse(
        status_code=200,
        content={"message": "RecoverAI API is online. Frontend files are being initialized at /static."}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
