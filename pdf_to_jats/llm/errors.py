"""Expected provider failures, distinct from application programming errors."""

from functools import wraps
import json
import urllib.error


class LLMError(RuntimeError):
    """A provider failed to produce a usable response."""


class LLMUnavailable(LLMError):
    """Provider configuration or transport is unavailable."""


class LLMRateLimited(LLMUnavailable):
    """The provider exhausted its rate-limit retries."""


class LLMResponseError(LLMError):
    """The provider returned malformed structured data."""


def provider_errors(function):
    """Normalize expected failures without exposing response/document contents."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            result = function(*args, **kwargs)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise LLMUnavailable("Provider connection failed.") from exc
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise LLMResponseError("Provider returned invalid JSON text.") from exc
        if not isinstance(result, dict):
            raise LLMResponseError("Provider response must be a JSON object.")
        return result
    return wrapped
