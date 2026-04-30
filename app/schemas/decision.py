# Pydantic response schema for the /run endpoint — Nicholas Hidalgo
from typing import List

from pydantic import BaseModel


class Escalation(BaseModel):
    required: bool
    reason: str


class DecisionOutput(BaseModel):
    status: str
    category: str
    priority: str
    routing_team: str
    suggested_actions: List[str]
    draft_response: str
    escalation: Escalation
    summary: str = ""
    audit_id: str
    risk_score: float
    pii_detected: bool
    redacted: bool
