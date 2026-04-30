# Audit record builder and Postgres writer — Nicholas Hidalgo
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.db.connection import SessionLocal
from app.db.models import AuditRecord


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_payload(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def hash_email(email: str) -> str:
    return hashlib.sha256(email.encode()).hexdigest()


class Timer:
    def __init__(self) -> None:
        self.start = time.time()

    def ms(self) -> int:
        return int((time.time() - self.start) * 1000)


def build_audit_record(
    intake: Dict[str, Any],
    agents: List[str],
    policy: Dict[str, Any],
    latency_ms: int,
    status: str,
    summary: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "audit_id": str(uuid.uuid4()),
        "timestamp_utc": utc_now(),
        "input_hash": hash_payload(intake),
        "agents_invoked": agents,
        "policy": policy,
        "latency_ms": latency_ms,
        "status": status,
        "summary": summary,
    }


def write_audit_record(audit: Dict[str, Any], intake: Dict[str, Any]) -> None:
    policy = audit.get("policy", {})
    db = SessionLocal()
    try:
        row = AuditRecord(
            id=uuid.UUID(audit["audit_id"]),
            request_id=audit["audit_id"],
            requester_email_hash=hash_email(intake.get("requester_email", "")),
            intake_text=json.dumps(
                {k: v for k, v in intake.items() if k != "requester_email"}
            ),
            policy_decision=policy.get("action", "unknown"),
            assigned_agent=", ".join(audit.get("agents_invoked", [])),
            resolution=audit.get("status"),
            confidence=policy.get("confidence_score"),
            redacted=policy.get("pii_detected", False),
            approved=False,
            summary=audit.get("summary"),
        )
        db.add(row)
        db.commit()
    finally:
        db.close()
