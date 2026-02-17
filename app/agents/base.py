from abc import ABC, abstractmethod
from typing import Dict, Any
from pydantic import BaseModel


class AgentResult(BaseModel):
    output: Dict[str, Any]
    meta: Dict[str, Any] = {}


class BaseAgent(ABC):
    name: str

    @abstractmethod
    def run(self, payload: Dict[str, Any]) -> AgentResult:
        ...
