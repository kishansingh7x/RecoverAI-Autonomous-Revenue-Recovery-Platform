"""
RecoverAI Streamlit Dashboard.
Interactive visual interface for Razorpay AI Buildathon 2026 Track 03: AI Revenue Recovery.
Provides live end-to-end pipeline execution, financial KPIs, AI discipline metrics,
compliance audit trails, and promise-to-pay tracking.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import json
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime

from src.db import get_connection, DEFAULT_DB_PATH
from src.generate_data import generate_transactions
from src.detect import detect_revenue_at_risk
from src.diagnose import diagnose_transactions
from src.execute import execute_recovery_actions
from src.ptp_tracker import process_promises_to_pay
from src.metrics import calculate_metrics, REPORT_PATH
from src.llm_client import is_llm_available

# Page configuration
st.set_page_config(
    page_title="RecoverAI | Razorpay Buildathon 2026",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
<style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 700;
        color: #0c2340;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        font-size: 1.05rem;
        color: #506690;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 1.2rem 1rem;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }
    .metric-val {
        font-size: 1.8rem;
        font-weight: 700;
        color: #1e293b;
    }
    .metric-lbl {
        font-size: 0.85rem;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .badge-green {
        background-color: #dcfce7;
        color: #166534;
        padding: 3px 8px;
        border-radius: 4px;
        font-size: 0.8rem;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# Helper function to run the full pipeline
def execute_batch_run(count: int, seed: int):
    with st.spinner("Step 1/5: Generating synthetic transaction batch..."):
        generate_transactions(count=count, seed=seed)
    with st.spinner("Step 2/5: Detecting revenue-at-risk via deterministic rules..."):
        detect_revenue_at_risk()
    with st.spinner("Step 3/5: Diagnosing root causes (Rule-first >=80%, LLM fallback)..."):
        diagnose_transactions()
    with st.spinner("Step 4/5: Executing bounded recovery actions & stopping rules..."):
        execute_recovery_actions()
    with st.spinner("Step 5/5: Tracking promises-to-pay & scheduling follow-ups..."):
        process_promises_to_pay(seed=seed)
    with st.spinner("Computing final financial & compliance metrics..."):
        metrics = calculate_metrics()
    return metrics

# Sidebar Controls
st.sidebar.image("https://razorpay.com/assets/razorpay-glyph.svg", width=50)
st.sidebar.title("RecoverAI Engine")
st.sidebar.caption("Track 03: AI Revenue Recovery")
st.sidebar.markdown("---")

st.sidebar.subheader("Batch Controls")
batch_size = st.sidebar.slider("Batch Size (Transactions)", min_value=150, max_value=300, value=200, step=10)
random_seed = st.sidebar.number_input("Random Seed", value=42, min_value=1, max_value=9999, step=1)

llm_online = is_llm_available()
if llm_online:
    st.sidebar.success("🟢 Claude LLM: Connected (Live API)")
else:
    st.sidebar.info("🔵 LLM: Deterministic Fallback Mode (Defensive Engineering)")

st.sidebar.markdown("---")
run_clicked = st.sidebar.button("🚀 Run Live Batch Pipeline", type="primary", use_container_width=True)

# Main Header
st.markdown('<div class="main-title">⚡ RecoverAI: Autonomous Revenue Recovery Agent</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Payment Failure → Root Cause Diagnosis → Bounded Recovery Actions → Promises-to-Pay Tracking</div>', unsafe_allow_html=True)

# Check if report exists or if run was clicked
if run_clicked or not REPORT_PATH.exists():
    metrics = execute_batch_run(count=batch_size, seed=random_seed)
    st.sidebar.success("Pipeline executed successfully!")
else:
    try:
        with open(REPORT_PATH, "r", encoding="utf-8") as f:
            metrics = json.load(f)
    except Exception:
        metrics = execute_batch_run(count=batch_size, seed=random_seed)

summary = metrics.get("summary", {})
ai_stats = metrics.get("ai_judgment_discipline", {})
compliance = metrics.get("compliance_guardrails", {})
by_code = metrics.get("by_failure_code", [])

# Top KPI Metric Cards
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-lbl">Revenue At Risk</div>
        <div class="metric-val">₹{summary.get('revenue_at_risk_inr', 0):,.2f}</div>
        <div style="font-size: 0.85rem; color: #64748b; margin-top: 4px;">
            {summary.get('transactions_at_risk', 0)} of {summary.get('total_transactions', 0)} transactions flagged
        </div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-lbl">Revenue Recovered</div>
        <div class="metric-val" style="color: #15803d;">₹{summary.get('revenue_recovered_inr', 0):,.2f}</div>
        <div style="font-size: 0.85rem; color: #64748b; margin-top: 4px;">
            {summary.get('transactions_recovered', 0)} transactions recovered
        </div>
    </div>
    """, unsafe_allow_html=True)

with col3:
    rate = summary.get('overall_recovery_rate_pct', 0.0)
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-lbl">Recovery Rate</div>
        <div class="metric-val" style="color: #0369a1;">{rate:.2f}%</div>
        <div style="font-size: 0.85rem; color: #64748b; margin-top: 4px;">
            Avg Attempts: {summary.get('average_attempts_to_recovery', 1.0)}
        </div>
    </div>
    """, unsafe_allow_html=True)

with col4:
    rule_pct = ai_stats.get('resolved_by_rules_pct', 0.0)
    llm_pct = ai_stats.get('resolved_by_llm_fallback_pct', 0.0)
    badge = '<span class="badge-green">Target Met (≥80%)</span>' if rule_pct >= 80 else '<span style="color:#b91c1c;">Below 80%</span>'
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-lbl">AI Judgment Discipline {badge}</div>
        <div class="metric-val">{rule_pct:.1f}% <span style="font-size: 1rem; color: #64748b;">Rule</span></div>
        <div style="font-size: 0.85rem; color: #64748b; margin-top: 4px;">
            {llm_pct:.1f}% LLM Fallback ({ai_stats.get('resolved_by_llm_fallback', 0)} cases)
        </div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# Row 2: Charts and Compliance Guardrails
chart_col, guard_col = st.columns([3, 2])

with chart_col:
    st.subheader("📊 Recovery Rate by Failure Code")
    if by_code:
        df_code = pd.DataFrame(by_code)
        fig = px.bar(
            df_code,
            x="failure_code",
            y="recovery_rate_pct",
            text="recovery_rate_pct",
            hover_data=["at_risk_count", "recovered_count", "at_risk_amount", "recovered_amount"],
            labels={"failure_code": "Failure Reason", "recovery_rate_pct": "Recovery Rate (%)"},
            color="recovery_rate_pct",
            color_continuous_scale="Blues"
        )
        fig.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
        fig.update_layout(
            height=320,
            margin=dict(l=20, r=20, t=20, b=20),
            coloraxis_showscale=False,
            xaxis_tickangle=-25
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No failure code data available.")

with guard_col:
    st.subheader("🛡️ Compliance & Guardrails Panel")
    opt_stops = compliance.get("stopped_for_opt_out", 0)
    max_stops = compliance.get("stopped_for_max_attempts", 0)
    total_stops = compliance.get("total_stopped", 0)

    st.markdown(f"""
    <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 1.2rem;">
        <div style="font-weight: 600; color: #334155; margin-bottom: 0.8rem;">Enforced Stopping Rules (Zero Non-Compliance)</div>
        <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem; padding-bottom: 0.5rem; border-bottom: 1px solid #e2e8f0;">
            <span style="color: #475569;">🛑 Stopped for Opt-Out (Do Not Disturb):</span>
            <span style="font-weight: 700; color: #dc2626;">{opt_stops}</span>
        </div>
        <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem; padding-bottom: 0.5rem; border-bottom: 1px solid #e2e8f0;">
            <span style="color: #475569;">⚠️ Stopped for Max Attempts (Cap = 3):</span>
            <span style="font-weight: 700; color: #ea580c;">{max_stops}</span>
        </div>
        <div style="display: flex; justify-content: space-between; margin-top: 0.8rem; font-weight: 700;">
            <span>Total Contacts Prevented / Bounded:</span>
            <span>{total_stops}</span>
        </div>
    </div>
    <div style="margin-top: 0.8rem; font-size: 0.8rem; color: #64748b;">
        🔒 <b>Auditor Note:</b> System strictly guarantees 0 outbound customer notifications once opt-out is detected or 3 attempts are reached. Silent retries bypass customer contact caps.
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# Row 3: Promise-to-Pay Board & Recovery Log
st.subheader("🤝 Promise-to-Pay (PTP) Tracking Board")
conn = get_connection()
ptp_df = pd.read_sql_query("""
    SELECT p.promise_id, p.transaction_id, t.customer_name, t.amount,
           p.promised_date, 
           CASE WHEN p.fulfilled = 1 THEN '✅ Fulfilled (Recovered)' ELSE '⏳ Pending / Unfulfilled' END AS status,
           CASE WHEN p.follow_up_sent = 1 THEN '🔔 Sent' ELSE '—' END AS follow_up
    FROM promises_to_pay p
    JOIN transactions t ON p.transaction_id = t.transaction_id
    ORDER BY p.promised_date DESC
""", conn)

if not ptp_df.empty:
    st.dataframe(
        ptp_df,
        column_config={
            "amount": st.column_config.NumberColumn("Amount (₹)", format="₹%.2f"),
            "status": "Fulfillment Status",
            "follow_up": "Follow-Up Dispatched"
        },
        use_container_width=True,
        hide_index=True
    )
else:
    st.info("No promises logged yet for this batch.")

st.markdown("---")

# Row 4: Audit Trail Table (actions_log)
st.subheader("📜 Complete Recovery Audit Trail (actions_log)")
st.caption("Every autonomous decision, stopping condition, explainable reasoning, and simulated customer copy.")

filter_col1, filter_col2 = st.columns([2, 2])
with filter_col1:
    search_txn = st.text_input("Filter by Transaction ID (e.g. txn_0012)", "")
with filter_col2:
    action_filter = st.selectbox(
        "Filter by Action Type",
        ["All Actions", "stop_contact", "send_reminder_sms", "suggest_alternate_payment_method", "send_update_card_link", "send_mandate_renewal_link", "send_b2b_payment_reminder", "retry_silently", "escalate_to_human"]
    )

query = """
    SELECT a.timestamp, a.transaction_id, a.action_type, a.attempt_number,
           a.stopped_reason, a.reasoning, a.message_sent
    FROM actions_log a
    WHERE 1=1
"""
params = []
if search_txn.strip():
    query += " AND a.transaction_id LIKE ?"
    params.append(f"%{search_txn.strip()}%")
if action_filter != "All Actions":
    query += " AND a.action_type = ?"
    params.append(action_filter)

query += " ORDER BY a.timestamp DESC, a.transaction_id ASC"

audit_df = pd.read_sql_query(query, conn, params=params)
conn.close()

st.dataframe(
    audit_df,
    column_config={
        "timestamp": "Timestamp",
        "transaction_id": "Txn ID",
        "action_type": "Action Executed",
        "attempt_number": "Attempt #",
        "stopped_reason": "Stopped Reason",
        "reasoning": "Audit Reasoning (Explainability)",
        "message_sent": "Simulated Message Copy"
    },
    use_container_width=True,
    hide_index=True
)
