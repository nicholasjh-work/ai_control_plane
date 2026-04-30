import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


def test_llm_client_falls_back_on_timeout():
    import httpx
    from app.llm.client import LLMClient, LLMUnavailableError

    with patch("app.llm.client.httpx.post", side_effect=httpx.TimeoutException("timed out")):
        with pytest.raises(LLMUnavailableError, match="timed out"):
            LLMClient().complete("sys", "user")


def test_classifier_falls_back_on_llm_error():
    from app.llm.client import LLMUnavailableError
    from app.agents.classifier_agent import ClassifierAgent

    payload = {
        "title": "Invoice problem",
        "description": "I was charged twice.",
        "urgency": "low",
        "routing_team": "billing",
    }

    with patch("app.agents.classifier_agent.LLMClient") as mock_cls:
        mock_cls.return_value.complete.side_effect = LLMUnavailableError("down")
        result = ClassifierAgent().run(payload)

    assert result.output["routing_team"] == "billing"
    assert "category" in result.output
    assert "priority" in result.output


def test_summary_agent_returns_unavailable_on_error():
    from app.llm.client import LLMUnavailableError
    from app.agents.summary_agent import SummaryAgent

    payload = {"title": "Crash on login", "description": "App crashes immediately."}

    with patch("app.agents.summary_agent.LLMClient") as mock_cls:
        mock_cls.return_value.complete.side_effect = LLMUnavailableError("down")
        result = SummaryAgent().run(payload)

    assert result.output["summary"] == "unavailable"


def test_decision_output_enforced():
    from unittest.mock import patch
    from app.main import app
    from app.llm.client import LLMUnavailableError

    client = TestClient(app)

    with patch("app.agents.classifier_agent.LLMClient") as mock_cls_c, \
         patch("app.agents.summary_agent.LLMClient") as mock_cls_s, \
         patch("app.governance.audit.SessionLocal") as mock_db:

        mock_cls_c.return_value.complete.side_effect = LLMUnavailableError("down")
        mock_cls_s.return_value.complete.side_effect = LLMUnavailableError("down")
        mock_session = MagicMock()
        mock_db.return_value = mock_session

        response = client.post("/run", json={
            "title": "Login crash",
            "description": "App crashes on login.",
            "requester_email": "test@example.com",
            "department": "eng",
            "system": "auth",
            "urgency": "high",
        })

    assert response.status_code == 200
    body = response.json()
    required_fields = {
        "status", "category", "priority", "routing_team",
        "suggested_actions", "draft_response", "escalation",
        "summary", "audit_id", "risk_score", "pii_detected", "redacted",
    }
    assert required_fields.issubset(body.keys())
    assert isinstance(body["suggested_actions"], list)
    assert isinstance(body["escalation"], dict)
    assert "required" in body["escalation"]
