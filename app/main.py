from fastapi import FastAPI
from typing import Dict, Any

from app.orchestration.engine import WorkflowEngine
from app.agents.classifier_agent import ClassifierAgent
from app.agents.resolver_agent import ResolverAgent
from app.schemas.intake import IntakeRequest

from app.governance.policy import evaluate_policy
from app.governance.audit import Timer, build_audit_record, write_jsonl

import os

app = FastAPI(title="AI Control Plane")

AUDIT_LOG_PATH = os.getenv("AUDIT_LOG_PATH", "logs/audit.jsonl")

@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}

@app.post("/run")
def run_workflow(req: IntakeRequest) -> Dict[str, Any]:
    payload = req.model_dump()

    timer = Timer()
    policy = evaluate_policy(payload)

    # Approval gate
    if policy.get("requires_approval"):
        audit = build_audit_record(
            intake=payload,
            agents=["policy_approval_required"],
            policy=policy,
            latency_ms=timer.ms(),
            status="needs_approval",
        )
        write_jsonl(AUDIT_LOG_PATH, audit)
        return {
            "status": "needs_approval",
            "policy": policy,
            "audit": audit
        }

    # Block gate
    if not policy.get("allowed", True):
        audit = build_audit_record(
            intake=payload,
            agents=["policy_block"],
            policy=policy,
            latency_ms=timer.ms(),
            status="blocked",
        )
        write_jsonl(AUDIT_LOG_PATH, audit)
        return {
            "status": "blocked",
            "policy": policy,
            "audit": audit
        }

    sanitized = policy.get("sanitized_payload", payload)

    engine = WorkflowEngine([
        ClassifierAgent(),
        ResolverAgent()
    ])

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

    return {
        "status": "succeeded",
        "policy": policy,
        "audit": audit,
        "result": result
    }
