import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def append_jsonl(path: str, record: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

def find_audit_record(audit_path: str, audit_id: str) -> Optional[Dict[str, 
Any]]:
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

def record_approval(approvals_path: str, audit_id: str, decision: str, 
approved_by: str, reason: str = "") -> Dict[str, Any]:
    rec = {
        "approval_id": audit_id + ":" + utc_now(),
        "timestamp_utc": utc_now(),
        "audit_id": audit_id,
        "decision": decision,
        "approved_by": approved_by,
        "reason": reason,
    }
    append_jsonl(approvals_path, rec)
    return rec

