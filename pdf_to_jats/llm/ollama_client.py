"""Ollama client using its native chat API."""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any
import urllib.request

from pdf_to_jats.llm.errors import LLMResponseError, provider_errors


@dataclass(slots=True)
class OllamaClient:
    model: str = "qwen3:8b"
    base_url: str = "http://localhost:11434"
    timeout_seconds: float = 120.0

    @provider_errors
    def classify(self, prompt: str, payload: dict[str, Any], progress=None) -> dict[str, Any]:
        report = progress or (lambda message: None)
        started = time.perf_counter()
        report("Preparing Qwen request...")
        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                # Qwen3's default reasoning mode can spend a long time thinking
                # before returning this short extraction result. Disable it for
                # structured metadata parsing and ask Ollama for JSON directly.
                "think": False,
                "format": "json",
                "options": {"temperature": 0.0, "num_predict": 4096},
                "stream": False,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url.rstrip('/')}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        report(f"Preparing Qwen request: {time.perf_counter() - started:.2f} seconds.")
        sent = time.perf_counter()
        report("Waiting for Qwen to process the prompt and generate its response...")
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            raw = json.loads(response.read().decode("utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("message", {}), dict):
            raise LLMResponseError("Ollama response has an invalid message structure.")
        elapsed = time.perf_counter() - sent
        report(f"Qwen request round trip: {elapsed:.2f} seconds.")
        for field, label in (
            ("load_duration", "Model loading"),
            ("prompt_eval_duration", "Prompt processing"),
            ("eval_duration", "Response generation"),
            ("total_duration", "Total server processing"),
        ):
            duration = raw.get(field)
            if isinstance(duration, (int, float)) and duration >= 0:
                report(f"Qwen {label}: {duration / 1_000_000_000:.2f} seconds.")
        if isinstance(raw.get("total_duration"), (int, float)):
            overhead = max(0, elapsed - raw["total_duration"] / 1_000_000_000)
            report(f"Qwen transport/client overhead (approximate): {overhead:.2f} seconds.")
        report("Parsing Qwen's structured response...")
        text = ((raw.get("message") or {}).get("content") or "")
        if isinstance(text, list):
            if any(not isinstance(part, dict) or not isinstance(part.get("text", ""), str)
                   for part in text):
                raise LLMResponseError("Ollama message content has invalid text parts.")
            text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
        if not isinstance(text, str):
            raise LLMResponseError("Ollama message content must be text.")
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
