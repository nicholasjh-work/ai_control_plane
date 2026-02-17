import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def hash_payload(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

def write_jsonl(path: str, record: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

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
) -> Dict[str, Any]:
    return {
        "audit_id": str(uuid.uuid4()),
        "timestamp_utc": utc_now(),
        "input_hash": hash_payload(intake),
        "agents_invoked": agents,
        "policy": policy,
        "latency_ms": latency_ms,
        "status": status,
    }

