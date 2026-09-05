"""
Integration tests for FastAPI Server Endpoints (server.py) and Frontend Integration.
Verifies:
- GET / serves the dashboard with Phase 8 components
- GET /api/metrics returns full dual rates, NRV, and modeled cost schema
- POST /api/evaluation/run returns empirical 3-way benchmark output
- GET /api/audit/integrity validates SHA-256 ledger integrity
- GET /api/decision/{txn_id} returns ERV rankings, policy status, and counterfactuals
"""

import pytest
from fastapi.testclient import TestClient
from server import app
from src.db import get_connection, init_db, DEFAULT_DB_PATH
from src.generate_data import generate_transactions
from src.detect import detect_revenue_at_risk
from src.diagnose import diagnose_transactions
from src.execute import execute_recovery_actions

@pytest.fixture(scope="module")
def client():
    # Ensure a seeded batch exists in the default database
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM transactions")
    count = cursor.fetchone()[0]
    conn.close()

    if count < 50:
        generate_transactions(count=100, seed=42)
        detect_revenue_at_risk()
        diagnose_transactions()
        execute_recovery_actions()

    with TestClient(app) as test_client:
        yield test_client

def test_serve_dashboard_contains_phase8_elements(client):
    """Verifies that GET / serves the HTML with all required Phase 8 UX components."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    # Verify Secondary Metrics Strip
    assert "secondary-metrics-strip" in html
    assert "kpiTxnRecoveredCount" in html
    assert "kpiNetRecoveredValue" in html
    assert "kpiModeledCost" in html

    # Verify 3-Way Benchmark Section
    assert "sectionBenchmark" in html
    assert "btnRunBenchmark" in html
    assert "benchNaiveRevRate" in html
    assert "benchStaticRevRate" in html
    assert "benchRecoverAiRevRate" in html

    # Verify Audit Integrity Bar
    assert "btnVerifyIntegrity" in html
    assert "auditIntegrityLabel" in html

    # Verify Decision Inspector Drawer
    assert "decisionDrawer" in html
    assert "inspErvTableBody" in html
    assert "inspPolicyChecklist" in html
    assert "inspExplanationBox" in html

def test_api_metrics_schema(client):
    """Verifies GET /api/metrics returns dual rates, NRV, and economic model."""
    response = client.get("/api/metrics")
    assert response.status_code == 200
    data = response.json()

    assert "summary" in data
    summary = data["summary"]
    assert "revenue_recovery_rate_pct" in summary
    assert "transaction_recovery_rate_pct" in summary
    assert "net_recovered_value_inr" in summary
    assert "total_modeled_recovery_cost_inr" in summary

    assert "recovery_economics" in data
    assert "economic_model" in data["recovery_economics"]

    assert "ai_judgment_discipline" in data
    assert "deterministic_diagnosis_share_pct" in data["ai_judgment_discipline"]

def test_api_evaluation_run(client):
    """Verifies POST /api/evaluation/run returns comparative 3-way evaluation results."""
    payload = {"seed": 42, "count": 60}
    response = client.post("/api/evaluation/run", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert "naive_retry" in data
    assert "static_rules" in data
    assert "recover_ai" in data
    assert "comparison" in data

    rec_ai = data["recover_ai"]
    assert "revenue_recovery_rate_pct" in rec_ai
    assert "net_recovered_value_inr" in rec_ai
    assert rec_ai["policy_violations"] == 0

    assert "revenue_uplift_pct" in data["comparison"]

def test_api_audit_integrity(client):
    """Verifies GET /api/audit/integrity checks the canonical SHA-256 hash chain."""
    response = client.get("/api/audit/integrity")
    assert response.status_code == 200
    data = response.json()

    assert "valid" in data
    assert "events_verified" in data
    assert "verification_time_ms" in data
    assert "genesis_hash" in data
    assert "head_hash" in data

def test_api_decision_inspection(client):
    """Verifies GET /api/decision/{txn_id} returns ERV rankings and policy checks."""
    tx_res = client.get("/api/transactions?limit=1")
    assert tx_res.status_code == 200
    txns = tx_res.json().get("transactions", [])
    if not txns:
        pytest.skip("No transactions available for decision inspection test")

    txn_id = txns[0]["transaction_id"]
    response = client.get(f"/api/decision/{txn_id}")
    assert response.status_code == 200
    data = response.json()

    assert "selected_action" in data
    assert "selected_erv" in data
    assert "all_evaluated_candidates" in data
    assert len(data["all_evaluated_candidates"]) > 0

    # Ensure ERV candidates have all mathematical components
    candidate = data["all_evaluated_candidates"][0]
    assert "action" in candidate
    assert "probability" in candidate
    assert "direct_cost" in candidate
    assert "friction_cost" in candidate
    assert "erv" in candidate
    assert "policy_status" in candidate

    assert "explanation" in data
    assert "transaction" in data
