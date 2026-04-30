# Provider-agnostic LLM client supporting LM Studio and OpenAI — Nicholas Hidalgo
import os
from typing import Any, Dict

import httpx


class LLMUnavailableError(Exception):
    pass


class LLMClient:
    def __init__(self) -> None:
        self.provider = os.getenv("LLM_PROVIDER", "lmstudio")
        self.model = os.getenv("LLM_MODEL", "qwen2.5-coder-14b")
        if self.provider == "openai":
            self.base_url = "https://api.openai.com/v1"
            self.api_key = os.getenv("OPENAI_API_KEY", "")
        else:
            self.base_url = os.getenv("LLM_BASE_URL", "http://localhost:1234/v1")
            self.api_key = "lm-studio"

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    def _body(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 256,
        }

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        url = f"{self.base_url}/chat/completions"
        try:
            response = httpx.post(
                url,
                headers=self._headers(),
                json=self._body(system_prompt, user_prompt),
                timeout=5.0,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except httpx.TimeoutException as exc:
            raise LLMUnavailableError(f"LLM request timed out: {exc}") from exc
        except Exception as exc:
            raise LLMUnavailableError(f"LLM call failed: {exc}") from exc
