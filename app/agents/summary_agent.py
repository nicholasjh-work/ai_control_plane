# Summarizes a support ticket in one sentence using an LLM — Nicholas Hidalgo
from typing import Any, Dict

from app.agents.base import AgentResult, BaseAgent
from app.llm.client import LLMClient, LLMUnavailableError

_SYSTEM_PROMPT = (
    "You are a support ticket summarizer. "
    "Summarize the following ticket in one sentence, 20 words or fewer."
)


class SummaryAgent(BaseAgent):
    name = "summary_agent"

    def run(self, payload: Dict[str, Any]) -> AgentResult:
        intake_text = (
            f"Title: {payload.get('title', '')}\n"
            f"Description: {payload.get('description', '')}"
        )
        try:
            summary = LLMClient().complete(_SYSTEM_PROMPT, intake_text).strip()
        except LLMUnavailableError:
            summary = "unavailable"

        return AgentResult(
            output={"summary": summary},
            meta={"agent": "SummaryAgent"},
        )
