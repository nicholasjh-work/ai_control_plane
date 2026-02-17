from typing import List, Dict, Any
from app.agents.base import BaseAgent


class WorkflowEngine:
    def __init__(self, agents: List[BaseAgent]):
        self.agents = agents

    def run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        ctx = {
            "initial_input": payload,
            "steps": []
        }

        current_payload = payload.copy()

        for agent in self.agents:
            result = agent.run(current_payload)

            ctx["steps"].append({
                "agent": agent.name,
                "output": result.output,
                "meta": result.meta
            })

            current_payload.update(result.output)

        ctx["final_output"] = current_payload
        return ctx
