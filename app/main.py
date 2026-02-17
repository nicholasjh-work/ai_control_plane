from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, Any

from app.orchestration.engine import WorkflowEngine
from app.agents.classifier_agent import ClassifierAgent
from app.agents.resolver_agent import ResolverAgent

app = FastAPI(title="ai_control_plane")


# ======================
# Request schema
# ======================
class IntakeRequest(BaseModel):
    title: str
    description: str
    requester_email: str
    department: str
    system: str
    urgency: str


# ======================
# Health check
# ======================
@app.get("/health")
def health():
    return {"status": "ok"}


# ======================
# Main orchestration endpoint
# ======================
@app.post("/run")
def run_workflow(req: IntakeRequest) -> Dict[str, Any]:
    payload = req.model_dump()

    engine = WorkflowEngine([
        ClassifierAgent(),
        ResolverAgent()
    ])

    result = engine.run(payload)
    return result

