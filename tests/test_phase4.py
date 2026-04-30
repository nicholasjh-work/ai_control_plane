from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def test_select_allowed():
    from app.sql.safety import validate_query

    result = validate_query("SELECT * FROM v_ticket_summary")
    assert result.allowed is True


def test_insert_blocked():
    from app.sql.safety import validate_query

    result = validate_query("INSERT INTO v_ticket_summary VALUES (1)")
    assert result.allowed is False


def test_unknown_table_blocked():
    from app.sql.safety import validate_query

    result = validate_query("SELECT * FROM raw_customers")
    assert result.allowed is False


def test_drop_blocked():
    from app.sql.safety import validate_query

    result = validate_query("DROP TABLE v_audit_summary")
    assert result.allowed is False


def test_unparseable_blocked():
    from app.sql.safety import validate_query

    result = validate_query("NOT VALID SQL ;;;")
    assert result.allowed is False


def test_policy_loads_from_config():
    import app.governance.policy as policy

    assert policy.max_intake_length == 2000
    assert "ClassifierAgent" in policy.ALLOWED_AGENTS


def test_sql_validate_endpoint_select():
    from app.main import app
    from app.llm.client import LLMUnavailableError

    client = TestClient(app)
    response = client.post("/v1/sql/validate", json={"query": "SELECT * FROM v_ticket_summary"})
    assert response.status_code == 200
    assert response.json()["allowed"] is True


def test_sql_validate_endpoint_insert():
    from app.main import app

    client = TestClient(app)
    response = client.post(
        "/v1/sql/validate",
        json={"query": "INSERT INTO v_ticket_summary VALUES (1)"},
    )
    assert response.status_code == 422
    assert response.json()["allowed"] is False
    assert "reason" in response.json()
