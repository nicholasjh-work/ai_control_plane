# Classifies support tickets by category, priority, and routing team — Nicholas Hidalgo
import json
from pathlib import Path
from typing import Any, Dict

from app.agents.base import AgentResult, BaseAgent
from app.llm.client import LLMClient, LLMUnavailableError

_RULES_PATH = Path(__file__).parent.parent / "config" / "routing_rules.json"
_ROUTING_TEAMS = list(json.loads(_RULES_PATH.read_text()).keys())

_SYSTEM_PROMPT = (
    "You are a ticket classifier. Given the following support ticket, "
    "return only the most relevant routing team from this list: "
    f"{', '.join(_ROUTING_TEAMS)}. Return the team name only, no explanation."
)


class ClassifierAgent(BaseAgent):
    name = "classifier_agent"

    def run(self, payload: Dict[str, Any]) -> AgentResult:
        title = payload.get("title", "").lower()
        urgency = payload.get("urgency", "low")

        category = (
            "incident" if ("dashboard" in title or "outage" in title) else "request"
        )

        if urgency == "critical":
            priority = "P0"
        elif urgency == "high":
            priority = "P1"
        else:
            priority = "P2"

        intake_text = f"Title: {payload.get('title', '')}\nDescription: {payload.get('description', '')}"
        fallback_team = payload.get("routing_team", "general")

        try:
            raw = LLMClient().complete(_SYSTEM_PROMPT, intake_text)
            routing_team = raw.strip().lower()
            if routing_team not in _ROUTING_TEAMS:
                routing_team = fallback_team
        except LLMUnavailableError:
            routing_team = fallback_team

        return AgentResult(
            output={
                "category": category,
                "priority": priority,
                "routing_team": routing_team,
            },
            meta={"rule_based": False, "llm_routing": True},
        )
