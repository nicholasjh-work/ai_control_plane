# FastAPI entry point for ai_control_plane — Nicholas Hidalgo
import os
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.agents.classifier_agent import ClassifierAgent
from app.agents.resolver_agent import ResolverAgent
from app.agents.summary_agent import SummaryAgent
from app.api.sql_router import router as sql_router
from app.governance.approvals import find_audit_record, record_approval
from app.governance.audit import Timer, build_audit_record, write_audit_record
from app.governance.policy import evaluate_policy
from app.orchestration.engine import WorkflowEngine
from app.schemas.decision import DecisionOutput, Escalation
from app.schemas.intake import IntakeRequest

app = FastAPI(title="AI Control Plane")
app.include_router(sql_router, prefix="/v1")

_STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.get("/demo", include_in_schema=False)
def demo() -> FileResponse:
    return FileResponse(str(_STATIC / "index.html"))


APPROVALS_LOG_PATH = os.getenv("APPROVALS_LOG_PATH", "logs/approvals.jsonl")
AUDIT_LOG_PATH = os.getenv("AUDIT_LOG_PATH", "logs/audit.jsonl")


class ApprovalRequest(BaseModel):
    decision: str
    approved_by: str
    reason: str = ""


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


def _extract_summary(result: Dict[str, Any]) -> str:
    for step in result.get("steps", []):
        if step["agent"] == "summary_agent":
            return step["output"].get("summary", "unavailable")
    return "unavailable"


@app.post("/run", response_model=DecisionOutput)
def run_workflow(req: IntakeRequest) -> DecisionOutput:
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
        write_audit_record(audit, payload)
        return DecisionOutput(
            status="needs_approval",
            category="unknown",
            priority="unknown",
            routing_team=policy.get("routing_team", "general"),
            suggested_actions=[],
            draft_response="",
            escalation=Escalation(required=False, reason="pending approval"),
            summary="unavailable",
            audit_id=audit["audit_id"],
            risk_score=policy["risk_score"],
            pii_detected=policy["pii_detected"],
            redacted=policy["pii_detected"],
        )

    if not policy.get("allowed", True):
        audit = build_audit_record(
            intake=payload,
            agents=["policy_block"],
            policy=policy,
            latency_ms=timer.ms(),
            status="blocked",
        )
        write_audit_record(audit, payload)
        return DecisionOutput(
            status="blocked",
            category="unknown",
            priority="unknown",
            routing_team=policy.get("routing_team", "general"),
            suggested_actions=[],
            draft_response="",
            escalation=Escalation(required=False, reason="blocked by policy"),
            summary="unavailable",
            audit_id=audit["audit_id"],
            risk_score=policy["risk_score"],
            pii_detected=policy["pii_detected"],
            redacted=policy["pii_detected"],
        )

    sanitized = dict(policy.get("sanitized_payload", payload))
    sanitized["routing_team"] = policy.get("routing_team", "general")
    engine = WorkflowEngine([ClassifierAgent(), ResolverAgent(), SummaryAgent()])
    result = engine.run(sanitized)
    final = result.get("final_output", {})
    agents = [step["agent"] for step in result.get("steps", [])]
    summary = _extract_summary(result)

    audit = build_audit_record(
        intake=payload,
        agents=agents,
        policy=policy,
        latency_ms=timer.ms(),
        status="succeeded",
        summary=summary,
    )
    write_audit_record(audit, payload)

    escalation_data = final.get("escalation", {})
    return DecisionOutput(
        status="succeeded",
        category=final.get("category", "unknown"),
        priority=final.get("priority", "unknown"),
        routing_team=final.get("routing_team", policy.get("routing_team", "general")),
        suggested_actions=final.get("suggested_actions", []),
        draft_response=final.get("draft_response", ""),
        escalation=Escalation(
            required=escalation_data.get("required", False),
            reason=escalation_data.get("reason", ""),
        ),
        summary=summary,
        audit_id=audit["audit_id"],
        risk_score=policy["risk_score"],
        pii_detected=policy["pii_detected"],
        redacted=policy["pii_detected"],
    )


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
        return {
            "status": "error",
            "message": "no sanitized_payload available for replay",
        }

    timer = Timer()
    sanitized = dict(sanitized)
    sanitized.setdefault("routing_team", policy.get("routing_team", "general"))
    engine = WorkflowEngine([ClassifierAgent(), ResolverAgent(), SummaryAgent()])
    result = engine.run(sanitized)
    agents = [step["agent"] for step in result.get("steps", [])]
    summary = _extract_summary(result)

    replay_policy = dict(policy)
    replay_policy["replayed_from_audit_id"] = audit_id

    audit = build_audit_record(
        intake=sanitized,
        agents=agents,
        policy=replay_policy,
        latency_ms=timer.ms(),
        status="replayed",
        summary=summary,
    )
    write_audit_record(audit, sanitized)
    return {
        "status": "replayed",
        "original_audit_id": audit_id,
        "audit": audit,
        "result": result,
    }
