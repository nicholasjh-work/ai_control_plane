from pydantic import BaseModel
from typing import List


class Escalation(BaseModel):
    required: bool
    reason: str


class DecisionOutput(BaseModel):
    category: str
    priority: str
    routing_team: str
    suggested_actions: List[str]
    draft_response: str
    escalation: Escalation
