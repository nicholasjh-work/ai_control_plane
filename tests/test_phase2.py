import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock, patch


def test_email_hash_is_not_raw():
    from app.governance.audit import hash_email

    email = "user@example.com"
    result = hash_email(email)
    assert result != email
    assert result == hashlib.sha256(email.encode()).hexdigest()
    assert len(result) == 64


def test_routing_loads_from_config():
    rules_path = Path("app/config/routing_rules.json")
    rules = json.loads(rules_path.read_text())
    assert "billing" in rules
    assert isinstance(rules["billing"], list)


def test_policy_routes_billing_keyword():
    from app.governance.policy import evaluate_policy

    payload = {
        "title": "Invoice not received",
        "description": "I have not received my invoice for last month.",
        "requester_email": "someone@example.com",
        "department": "finance",
        "system": "billing_system",
        "urgency": "low",
    }
    result = evaluate_policy(payload)
    assert result["routing_team"] == "billing"


def test_audit_write_does_not_store_raw_email():
    from app.governance.audit import write_audit_record

    intake = {
        "title": "Test",
        "description": "desc",
        "requester_email": "secret@example.com",
        "department": "eng",
        "system": "test",
        "urgency": "low",
    }
    audit = {
        "audit_id": "00000000-0000-0000-0000-000000000001",
        "policy": {"action": "allow", "confidence_score": 0.85, "pii_detected": False},
        "agents_invoked": ["classifier_agent"],
        "status": "succeeded",
    }

    mock_session = MagicMock()
    mock_session_cls = MagicMock(return_value=mock_session)

    with patch("app.governance.audit.SessionLocal", mock_session_cls):
        write_audit_record(audit, intake)

    added = mock_session.add.call_args[0][0]
    assert added.requester_email_hash != "secret@example.com"
    assert len(added.requester_email_hash) == 64
    assert "secret@example.com" not in (added.intake_text or "")
