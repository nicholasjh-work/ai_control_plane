from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, Any
import os

from app.orchestration.engine import WorkflowEngine
from app.agents.classifier_agent import ClassifierAgent
from app.agents.resolver_agent import ResolverAgent
from app.schemas.intake import IntakeRequest

from app.governance.policy import evaluate_policy
from app.governance.audit import Timer, build_audit_record, write_jsonl
from app.governance.approvals import find_audit_record, record_approval

app = FastAPI(title="AI Control Plane")

AUDIT_LOG_PATH = os.getenv("AUDIT_LOG_PATH", "logs/audit.jsonl")
APPROVALS_LOG_PATH = os.getenv("APPROVALS_LOG_PATH", "logs/approvals.jsonl")


class ApprovalRequest(BaseModel):
    decision: str  # "approved" or "rejected"
    approved_by: str
    reason: str = ""


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/run")
def run_workflow(req: IntakeRequest) -> Dict[str, Any]:
    payload = req.model_dump()

    timer = Timer()
    policy = evaluate_policy(payload)

    if policy.get("requires_approval"):
        audit = build_audit_record(
            intake=payload,
            agents=["policy_approval_required"],
            policy=policy,
            latency_ms=timer.ms(),
            status="needs_approval",
        )
        write_jsonl(AUDIT_LOG_PATH, audit)
        return {"status": "needs_approval", "policy": policy, "audit": 
audit}

    if not policy.get("allowed", True):
        audit = build_audit_record(
            intake=payload,
            agents=["policy_block"],
            policy=policy,
            latency_ms=timer.ms(),
            status="blocked",
        )
        write_jsonl(AUDIT_LOG_PATH, audit)
        return {"status": "blocked", "policy": policy, "audit": audit}

    sanitized = policy.get("sanitized_payload", payload)

    engine = WorkflowEngine([ClassifierAgent(), ResolverAgent()])
    result = engine.run(sanitized)
    agents = [step["agent"] for step in result.get("steps", [])]

    audit = build_audit_record(
        intake=payload,
        agents=agents,
        policy=policy,
        latency_ms=timer.ms(),
        status="succeeded",
    )
    write_jsonl(AUDIT_LOG_PATH, audit)

    return {"status": "succeeded", "policy": policy, "audit": audit, 
"result": result}


@app.post("/approve/{audit_id}")
def approve(audit_id: str, req: ApprovalRequest) -> Dict[str, Any]:
    decision = req.decision.strip().lower()
    if decision not in ["approved", "rejected"]:
        return {
            "status": "error",
            "message": "decision must be 'approved' or 'rejected'",
        }

    audit_rec = find_audit_record(AUDIT_LOG_PATH, audit_id)
    if not audit_rec:
        return {"status": "error", "message": "audit_id not found"}

    approval = record_approval(
        approvals_path=APPROVALS_LOG_PATH,
        audit_id=audit_id,
        decision=decision,
        approved_by=req.approved_by,
        reason=req.reason,
    )
    return {"status": "ok", "approval": approval}


@app.post("/replay/{audit_id}")
def replay(audit_id: str) -> Dict[str, Any]:
    audit_rec = find_audit_record(AUDIT_LOG_PATH, audit_id)
    if not audit_rec:
        return {"status": "error", "message": "audit_id not found"}

    policy = audit_rec.get("policy", {})
    sanitized = policy.get("sanitized_payload")
    if not sanitized:
        return {"status": "error", "message": "no sanitized_payload available for replay"}
    timer = Timer()

    engine = WorkflowEngine([ClassifierAgent(), ResolverAgent()])
    result = engine.run(sanitized)
    agents = [step["agent"] for step in result.get("steps", [])]

    replay_policy = dict(policy)
    replay_policy["replayed_from_audit_id"] = audit_id

    audit = build_audit_record(
        intake=sanitized,
        agents=agents,
        policy=replay_policy,
        latency_ms=timer.ms(),
        status="replayed",
    )
    write_jsonl(AUDIT_LOG_PATH, audit)

    return {"status": "replayed", "original_audit_id": audit_id, "audit": 
audit, "result": result}
