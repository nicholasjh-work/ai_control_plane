"""
Tests for approval persistence, audit lookup, and approval-ID hardening.

All tests are deterministic and use mocks — no live database or LLM required.
"""

import json
import os
import uuid
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Approval ID format
# ---------------------------------------------------------------------------


class TestApprovalIdFormat:
    def test_approval_id_is_uuid_format(self, tmp_path):
        """record_approval() must produce a UUID-format approval_id."""
        from app.governance.approvals import record_approval

        approvals_file = str(tmp_path / "approvals.jsonl")

        with patch("app.governance.approvals._update_postgres_approval"):
            rec = record_approval(
                approvals_path=approvals_file,
                audit_id="test-audit-123",
                decision="approved",
                approved_by="reviewer@example.com",
                reason="looks good",
            )

        # Must be parseable as a UUID
        parsed = uuid.UUID(rec["approval_id"])
        assert parsed.version == 4

    def test_approval_id_is_unique_across_calls(self, tmp_path):
        """Each call to record_approval() produces a distinct approval_id."""
        from app.governance.approvals import record_approval

        approvals_file = str(tmp_path / "approvals.jsonl")

        with patch("app.governance.approvals._update_postgres_approval"):
            rec1 = record_approval(
                approvals_path=approvals_file,
                audit_id="audit-abc",
                decision="approved",
                approved_by="a@example.com",
            )
            rec2 = record_approval(
                approvals_path=approvals_file,
                audit_id="audit-abc",
                decision="rejected",
                approved_by="b@example.com",
            )

        assert rec1["approval_id"] != rec2["approval_id"]

    def test_approval_id_does_not_contain_timestamp_only(self, tmp_path):
        """approval_id must not be the old colon-delimited timestamp form."""
        from app.governance.approvals import record_approval

        approvals_file = str(tmp_path / "approvals.jsonl")

        with patch("app.governance.approvals._update_postgres_approval"):
            rec = record_approval(
                approvals_path=approvals_file,
                audit_id="audit-xyz",
                decision="approved",
                approved_by="ops@example.com",
            )

        # Old format was "audit_id:timestamp" — the new UUID must not contain ":"
        assert ":" not in rec["approval_id"]


# ---------------------------------------------------------------------------
# JSONL ledger still written
# ---------------------------------------------------------------------------


class TestJsonlLedger:
    def test_jsonl_ledger_receives_approval_record(self, tmp_path):
        """Approval record is always appended to the JSONL ledger."""
        from app.governance.approvals import record_approval

        approvals_file = str(tmp_path / "approvals.jsonl")

        with patch("app.governance.approvals._update_postgres_approval"):
            rec = record_approval(
                approvals_path=approvals_file,
                audit_id="audit-001",
                decision="approved",
                approved_by="manager@example.com",
                reason="reviewed and approved",
            )

        assert os.path.exists(approvals_file)
        with open(approvals_file) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 1
        stored = json.loads(lines[0])
        assert stored["audit_id"] == "audit-001"
        assert stored["decision"] == "approved"
        assert stored["approval_id"] == rec["approval_id"]

    def test_jsonl_ledger_accumulates_multiple_records(self, tmp_path):
        """Multiple approvals accumulate in the JSONL ledger."""
        from app.governance.approvals import record_approval

        approvals_file = str(tmp_path / "approvals.jsonl")

        with patch("app.governance.approvals._update_postgres_approval"):
            for i in range(3):
                record_approval(
                    approvals_path=approvals_file,
                    audit_id=f"audit-{i:03d}",
                    decision="approved",
                    approved_by="ops@example.com",
                )

        with open(approvals_file) as f:
            lines = [l.strip() for l in f if l.strip()]
        assert len(lines) == 3


# ---------------------------------------------------------------------------
# PostgreSQL approval persistence
# ---------------------------------------------------------------------------


class TestPostgresApprovalPersistence:
    def _make_mock_row(self, audit_id: str) -> MagicMock:
        row = MagicMock()
        row.request_id = audit_id
        row.approved = False
        return row

    def test_approved_decision_sets_approved_true(self):
        """_update_postgres_approval sets row.approved=True for 'approved'."""
        from app.governance.approvals import _update_postgres_approval

        mock_row = self._make_mock_row("audit-999")
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = (
            mock_row
        )

        with patch("app.governance.approvals.SessionLocal", return_value=mock_session):
            _update_postgres_approval("audit-999", "approved")

        assert mock_row.approved is True
        mock_session.commit.assert_called_once()

    def test_rejected_decision_sets_approved_false(self):
        """_update_postgres_approval sets row.approved=False for 'rejected'."""
        from app.governance.approvals import _update_postgres_approval

        mock_row = self._make_mock_row("audit-888")
        mock_row.approved = True  # Start as True to confirm it gets reset
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = (
            mock_row
        )

        with patch("app.governance.approvals.SessionLocal", return_value=mock_session):
            _update_postgres_approval("audit-888", "rejected")

        assert mock_row.approved is False
        mock_session.commit.assert_called_once()

    def test_missing_row_does_not_raise(self):
        """_update_postgres_approval is a no-op when the row is absent."""
        from app.governance.approvals import _update_postgres_approval

        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        with patch("app.governance.approvals.SessionLocal", return_value=mock_session):
            _update_postgres_approval("nonexistent-id", "approved")  # must not raise

        mock_session.commit.assert_not_called()

    def test_db_error_does_not_raise(self):
        """_update_postgres_approval swallows DB exceptions gracefully."""
        from app.governance.approvals import _update_postgres_approval

        with patch(
            "app.governance.approvals.SessionLocal",
            side_effect=Exception("connection refused"),
        ):
            _update_postgres_approval("audit-777", "approved")  # must not raise

    def test_record_approval_calls_postgres_update(self, tmp_path):
        """record_approval() calls _update_postgres_approval with correct args."""
        from app.governance.approvals import record_approval

        approvals_file = str(tmp_path / "approvals.jsonl")

        with patch("app.governance.approvals._update_postgres_approval") as mock_pg:
            record_approval(
                approvals_path=approvals_file,
                audit_id="audit-555",
                decision="approved",
                approved_by="lead@example.com",
            )

        mock_pg.assert_called_once_with("audit-555", "approved")


# ---------------------------------------------------------------------------
# Audit lookup — PostgreSQL primary, JSONL fallback
# ---------------------------------------------------------------------------


class TestAuditLookup:
    def _make_db_row(self, audit_id: str) -> MagicMock:
        row = MagicMock()
        row.request_id = audit_id
        row.policy_decision = "allow"
        row.confidence = 0.85
        row.redacted = False
        row.assigned_agent = "classifier_agent"
        row.resolution = "succeeded"
        row.summary = "Ticket processed."
        row.approved = False
        return row

    def test_find_audit_record_returns_postgres_row_when_found(self):
        """find_audit_record() returns a record from PostgreSQL when the row exists."""
        from app.governance.approvals import find_audit_record

        mock_row = self._make_db_row("audit-db-001")
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = (
            mock_row
        )

        with patch("app.governance.approvals.SessionLocal", return_value=mock_session):
            result = find_audit_record("logs/audit.jsonl", "audit-db-001")

        assert result is not None
        assert result["audit_id"] == "audit-db-001"
        assert result["status"] == "succeeded"

    def test_find_audit_record_falls_back_to_jsonl_when_db_unavailable(self, tmp_path):
        """find_audit_record() falls back to JSONL when DB raises an exception."""
        from app.governance.approvals import find_audit_record

        audit_file = str(tmp_path / "audit.jsonl")
        record = {"audit_id": "audit-jsonl-001", "status": "succeeded", "policy": {}}
        with open(audit_file, "w") as f:
            f.write(json.dumps(record) + "\n")

        with patch(
            "app.governance.approvals.SessionLocal",
            side_effect=Exception("DB unavailable"),
        ):
            result = find_audit_record(audit_file, "audit-jsonl-001")

        assert result is not None
        assert result["audit_id"] == "audit-jsonl-001"

    def test_find_audit_record_returns_none_when_not_found_anywhere(self, tmp_path):
        """find_audit_record() returns None when absent from both DB and JSONL."""
        from app.governance.approvals import find_audit_record

        audit_file = str(tmp_path / "audit.jsonl")
        # Write a record with a different ID
        with open(audit_file, "w") as f:
            f.write(json.dumps({"audit_id": "other-id", "status": "ok"}) + "\n")

        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        with patch("app.governance.approvals.SessionLocal", return_value=mock_session):
            result = find_audit_record(audit_file, "does-not-exist")

        assert result is None

    def test_find_audit_record_returns_none_for_missing_jsonl(self, tmp_path):
        """find_audit_record() returns None when JSONL file does not exist."""
        from app.governance.approvals import find_audit_record

        nonexistent = str(tmp_path / "no_such_file.jsonl")

        with patch(
            "app.governance.approvals.SessionLocal",
            side_effect=Exception("DB unavailable"),
        ):
            result = find_audit_record(nonexistent, "audit-xyz")

        assert result is None


# ---------------------------------------------------------------------------
# Approval endpoint integration (FastAPI TestClient, mocked DB)
# ---------------------------------------------------------------------------


class TestApprovalEndpoint:
    def _run_client(self):
        from fastapi.testclient import TestClient
        from app.main import app

        return TestClient(app)

    def _make_db_row(self, audit_id: str) -> MagicMock:
        row = MagicMock()
        row.request_id = audit_id
        row.policy_decision = "require_approval"
        row.confidence = 0.70
        row.redacted = True
        row.assigned_agent = "policy_approval_required"
        row.resolution = "needs_approval"
        row.summary = None
        row.approved = False
        return row

    def test_approve_endpoint_returns_uuid_approval_id(self):
        """POST /approve/{audit_id} returns a UUID-format approval_id."""
        mock_row = self._make_db_row("audit-ep-001")
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = (
            mock_row
        )

        with (
            patch("app.governance.approvals.SessionLocal", return_value=mock_session),
            patch("app.governance.approvals.append_jsonl"),
        ):
            client = self._run_client()
            resp = client.post(
                "/approve/audit-ep-001",
                json={
                    "decision": "approved",
                    "approved_by": "manager@example.com",
                    "reason": "reviewed",
                },
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        approval = body["approval"]
        # Must be a valid UUID — uuid.UUID() raises ValueError if not
        parsed = uuid.UUID(approval["approval_id"])
        assert parsed.version == 4

    def test_approve_endpoint_invalid_decision_rejected(self):
        """POST /approve/{audit_id} with invalid decision returns error."""
        client = self._run_client()
        resp = client.post(
            "/approve/any-id",
            json={"decision": "maybe", "approved_by": "x@y.com"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "error"

    def test_approve_endpoint_missing_audit_id_returns_error(self):
        """POST /approve/{audit_id} returns error when audit_id is not found."""
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = None

        with patch("app.governance.approvals.SessionLocal", return_value=mock_session):
            client = self._run_client()
            resp = client.post(
                "/approve/nonexistent-audit",
                json={"decision": "approved", "approved_by": "admin@example.com"},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "error"
        assert "not found" in resp.json()["message"]
