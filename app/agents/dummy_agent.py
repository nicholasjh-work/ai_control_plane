from typing import Dict, Any
from app.agents.base import BaseAgent, AgentResult


class DummyAgent(BaseAgent):
    name = "dummy_agent"

    def run(self, payload: Dict[str, Any]) -> AgentResult:
        return AgentResult(
            output={"processed": True},
            meta={"note": "dummy execution"}
        )
