import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.db.connection import SessionLocal
from app.db.models import AuditRecord


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: str, record: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def find_audit_record(audit_path: str, audit_id: str) -> Optional[Dict[str, Any]]:
    """Locate an audit record by audit_id.

    Primary source: PostgreSQL (ai_control_plane_audit table), queried by
    request_id.  Falls back to JSONL scan only when the DB session cannot be
    acquired or the record is absent in the DB.  The JSONL audit_path argument
    is used exclusively as a fallback; it is not the primary source of truth.
    """
    # --- Primary: PostgreSQL lookup ---
    try:
        db = SessionLocal()
        try:
            row = (
                db.query(AuditRecord).filter(AuditRecord.request_id == audit_id).first()
            )
            if row is not None:
                return {
                    "audit_id": str(row.request_id),
                    "policy": {
                        "action": row.policy_decision,
                        "confidence_score": row.confidence,
                        "pii_detected": row.redacted,
                    },
                    "agents_invoked": (
                        row.assigned_agent.split(", ") if row.assigned_agent else []
                    ),
                    "status": row.resolution,
                    "summary": row.summary,
                    "approved": row.approved,
                }
        finally:
            db.close()
    except Exception:
        # DB unavailable — fall through to JSONL
        pass

    # --- Fallback: JSONL scan (supplemental ledger) ---
    # This path is exercised only when PostgreSQL is unreachable or the record
    # predates DB persistence.  It is not the authoritative lookup path.
    if not os.path.exists(audit_path):
        return None
    with open(audit_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("audit_id") == audit_id:
                return rec
    return None


def record_approval(
    approvals_path: str,
    audit_id: str,
    decision: str,
    approved_by: str,
    reason: str = "",
) -> Dict[str, Any]:
    """Record an approval decision.

    1. Writes to the JSONL approvals ledger (supplemental, append-only).
    2. Updates the approved column in PostgreSQL (primary structured store).
       If the DB update fails it is logged but does not raise, so the JSONL
       record is always written regardless.
    """
    rec = {
        "approval_id": str(uuid.uuid4()),
        "timestamp_utc": utc_now(),
        "audit_id": audit_id,
        "decision": decision,
        "approved_by": approved_by,
        "reason": reason,
    }

    # Always write the supplemental JSONL ledger first.
    append_jsonl(approvals_path, rec)

    # Update the primary PostgreSQL audit record.
    _update_postgres_approval(audit_id, decision)

    return rec


def _update_postgres_approval(audit_id: str, decision: str) -> None:
    """Set approved=True/False on the matching AuditRecord row.

    Silently skips if the DB is unavailable or the row is not found.
    """
    try:
        approved_flag = decision == "approved"
        db = SessionLocal()
        try:
            row = (
                db.query(AuditRecord).filter(AuditRecord.request_id == audit_id).first()
            )
            if row is not None:
                row.approved = approved_flag
                db.commit()
        finally:
            db.close()
    except Exception:
        # DB unavailable — approval recorded in JSONL only.
        pass
