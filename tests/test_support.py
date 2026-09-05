"""
Unit and Integration Tests for 24x7 Customer Priority Support & Escalation
"""
import pytest
from fastapi.testclient import TestClient
from server import app
from src.llm_client import answer_support_chat
from src.db import create_support_callback, get_support_callbacks

client = TestClient(app)

def test_answer_support_chat_fallback():
    """Test that support chat returns helpful Hindi/Hinglish instructions."""
    res = answer_support_chat("Mera paisa account se kat gaya par order cancel ho gaya")
    assert res is not None
    assert "reply" in res
    assert res["can_escalate"] is True
    assert "1800-123-7729" in res["helpline"]
    assert len(res["suggestions"]) > 0

def test_api_support_chat_endpoint():
    """Test POST /api/support/chat endpoint."""
    payload = {
        "message": "Bank ne payment decline kar diya hai, alternative link do",
        "history": []
    }
    response = client.post("/api/support/chat", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "reply" in data
    assert "suggestions" in data

def test_api_support_callback_creation():
    """Test POST /api/support/callback and audit trail persistence."""
    payload = {
        "customer_name": "Priya Sharma",
        "phone": "9876543210",
        "preferred_slot": "Immediate (within 3-5 mins)",
        "issue_summary": "Auto-debit failed twice without OTP prompt"
    }
    response = client.post("/api/support/callback", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "ticket_id" in data
    assert data["ticket_id"].startswith("RZP-TKT-")
    assert data["status"] == "queued"

    # Verify listing
    get_res = client.get("/api/support/callbacks")
    assert get_res.status_code == 200
    res_data = get_res.json()
    callbacks = res_data.get("callbacks", [])
    assert any(cb["phone"] == "9876543210" for cb in callbacks)
