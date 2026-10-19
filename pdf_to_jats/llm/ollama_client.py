"""Ollama client using its OpenAI-compatible chat completions endpoint."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
import urllib.request


@dataclass(slots=True)
class OllamaClient:
    model: str = "qwen3:8b"
    base_url: str = "http://localhost:11434/v1"
    timeout_seconds: float = 120.0

    def classify(self, prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                "temperature": 0.0,
                "stream": False,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/chat/completions",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            raw = json.loads(response.read().decode("utf-8"))
        choices = raw.get("choices") or []
        text = ((choices[0].get("message") or {}).get("content") or "") if choices else ""
        if isinstance(text, list):
            text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
        if not text.strip():
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end > start:
                return json.loads(text[start : end + 1])
            raise
