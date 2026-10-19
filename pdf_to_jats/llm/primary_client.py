"""Use local Ollama first and fall back to OpenRouter when it is unavailable."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Callable

from pdf_to_jats.llm.ollama_client import OllamaClient
from pdf_to_jats.llm.openrouter_client import OpenRouterClient

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PrimaryLLMClient:
    ollama: OllamaClient
    openrouter: OpenRouterClient

    def classify(
        self,
        prompt: str,
        payload: dict[str, Any],
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        report = progress or (lambda _message: None)
        report(f"Sending author/affiliation data to Qwen ({self.ollama.model})...")
        try:
            response = self.ollama.classify(prompt, payload)
            report("Qwen returned a response.")
            return response
        except Exception as exc:
            report(f"Qwen failed ({exc}); trying OpenRouter...")
            logger.warning("Qwen via Ollama (%s) failed; trying OpenRouter: %s", self.ollama.model, exc)
            try:
                response = self.openrouter.classify(prompt, payload)
                report("OpenRouter returned a response.")
                return response
            except Exception as fallback_exc:
                report(f"OpenRouter failed ({fallback_exc}); using heuristic links.")
                raise RuntimeError(
                    f"Qwen via Ollama ({self.ollama.model}) failed: {exc}; "
                    f"OpenRouter fallback failed: {fallback_exc}"
                ) from fallback_exc
