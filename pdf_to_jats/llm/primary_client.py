"""Use local Ollama first and fall back to OpenRouter when it is unavailable."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Callable

from pdf_to_jats.llm.errors import LLMError, LLMUnavailable
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
            response = self.ollama.classify(prompt, payload, progress=report)
            report("Qwen returned a response.")
            return response
        except LLMError as exc:
            report("Qwen unavailable; trying OpenRouter...")
            logger.warning("Qwen unavailable (%s); trying OpenRouter", type(exc).__name__)
            try:
                response = self.openrouter.classify(prompt, payload)
                report("OpenRouter returned a response.")
                return response
            except LLMError as fallback_exc:
                report("OpenRouter unavailable; using heuristic links.")
                raise LLMUnavailable(
                    "Qwen and OpenRouter failed; heuristic links require review."
                ) from fallback_exc
