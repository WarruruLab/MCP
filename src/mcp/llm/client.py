from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional
from urllib import error, request


@dataclass
class LlmDecision:
    action: str
    score: float
    reason: str


class LlmClient:
    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> None:
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        timeout_value = timeout_seconds or os.getenv("OLLAMA_TIMEOUT_SECONDS", "10")
        self.timeout_seconds = float(timeout_value)

    def decide_append_or_new(self, context: str) -> LlmDecision:
        try:
            response_text = self._generate(self._build_prompt(context))
            return self._parse_decision(response_text)
        except (ValueError, error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            return self._fallback_decision(context)

    def _build_prompt(self, context: str) -> str:
        return (
            "You decide whether a new message should be appended to the current session block.\n"
            "Return JSON only with keys action, score, reason.\n"
            'action must be either "APPEND" or "NEW_BLOCK".\n'
            "score must be a float between 0 and 1.\n"
            "reason must be a short snake_case string.\n\n"
            f"{context}"
        )

    def _generate(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["APPEND", "NEW_BLOCK"]},
                    "score": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["action", "score", "reason"],
            },
            "options": {
                "temperature": 0,
            },
        }
        req = request.Request(
            url=f"{self.base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=self.timeout_seconds) as response:
            body = response.read().decode("utf-8")
        decoded = json.loads(body)
        return str(decoded.get("response", "")).strip()

    def _parse_decision(self, response_text: str) -> LlmDecision:
        data = json.loads(response_text)
        action = str(data.get("action", "")).strip().upper()
        if action not in {"APPEND", "NEW_BLOCK"}:
            raise ValueError("invalid action")

        score = float(data.get("score", 0.0))
        if score < 0.0 or score > 1.0:
            raise ValueError("invalid score")

        reason = str(data.get("reason", "")).strip() or "llm_decision"
        return LlmDecision(action=action, score=score, reason=reason)

    def _fallback_decision(self, context: str) -> LlmDecision:
        # Deterministic fallback used when Ollama is unavailable or returns invalid JSON.
        if len(context) % 2 == 0:
            return LlmDecision(action="APPEND", score=0.55, reason="fallback_even_length")
        return LlmDecision(action="NEW_BLOCK", score=0.55, reason="fallback_odd_length")
