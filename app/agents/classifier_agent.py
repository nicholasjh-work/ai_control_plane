from typing import Dict, Any
from app.agents.base import BaseAgent, AgentResult


class ClassifierAgent(BaseAgent):
    name = "classifier_agent"

    def run(self, payload: Dict[str, Any]) -> AgentResult:
        title = payload.get("title", "").lower()
        urgency = payload.get("urgency", "low")

        if "dashboard" in title or "outage" in title:
            category = "incident"
        else:
            category = "request"

        if urgency == "critical":
            priority = "P0"
        elif urgency == "high":
            priority = "P1"
        else:
            priority = "P2"

        return AgentResult(
            output={
                "category": category,
                "priority": priority,
                "routing_team": "Data Platform"
            },
            meta={"rule_based": True}
        )
