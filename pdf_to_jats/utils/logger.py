"""Logging setup with conservative API-key redaction."""

from __future__ import annotations

import logging
import re

_SK_KEY = re.compile(r"\bsk-[A-Za-z0-9._\-]{8,}")
_KEY_VALUE = re.compile(
    r"(?i)\b(api[_-]?key|authorization|bearer)(\s*[:=]\s*|\s+)"
    r"([A-Za-z0-9._\-]{8,})"
)


def redact_secrets(text: str) -> str:
    """Mask API keys and bearer tokens before a message reaches a handler."""

    redacted = _SK_KEY.sub("sk-***", text)
    return _KEY_VALUE.sub(lambda match: f"{match.group(1)}{match.group(2)}***", redacted)


class _RedactionFilter(logging.Filter):
    """Redact the final formatted message while preserving record metadata."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # A broken %-format must not suppress the record.
            return True
        record.msg = redact_secrets(message)
        record.args = ()
        return True


def configure_logging(level: int = logging.INFO) -> None:
    """Configure standard logging for the application."""

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    redaction = _RedactionFilter()
    for handler in logging.getLogger().handlers:
        if not any(isinstance(item, _RedactionFilter) for item in handler.filters):
            handler.addFilter(redaction)
