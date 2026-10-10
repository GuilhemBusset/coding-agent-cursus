"""Minimal stdlib client for the Anthropic Messages and OpenAI Chat Completions APIs.

No SDK on purpose: the demos stay inside the session's declared dependencies, and the
request each one sends is visible here in full. Keys come from the environment only.
"""

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

KEY_VARS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
BASE_VARS = {"anthropic": "ANTHROPIC_BASE_URL", "openai": "OPENAI_BASE_URL"}
DEFAULT_BASES = {"anthropic": "https://api.anthropic.com", "openai": "https://api.openai.com"}
PATHS = {"anthropic": "/v1/messages", "openai": "/v1/chat/completions"}
VENDORS = {"anthropic": "Anthropic", "openai": "OpenAI"}
# Defaults for --model. Each must have a "Yes" row in sampling.md's dated, sourced
# "Temperature support" table; change one only together with that table.
DEFAULT_MODELS = {"anthropic": "claude-opus-4-6", "openai": "gpt-4.1-mini"}
ANTHROPIC_VERSION = "2023-06-01"
TIMEOUT_S = 60


class ApiError(Exception):
    """The vendor refused the request or could not be reached."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.message = message
        self.status = status


def require_key(provider):
    """Return the provider's API key, or exit with one clear line before any network call."""
    name = KEY_VARS[provider]
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"error: {name} is not set. Export your {VENDORS[provider]} API key, "
              "or replay the offline recording with --replay.", file=sys.stderr)
        sys.exit(2)
    return value


def endpoint(provider):
    """The full URL, honouring the vendor's standard base-URL variable."""
    base = os.environ.get(BASE_VARS[provider], "").strip() or DEFAULT_BASES[provider]
    base = base.rstrip("/")
    if base.endswith("/v1"):  # OPENAI_BASE_URL is often given with /v1 already.
        base = base[:-3]
    return base + PATHS[provider]


def complete(provider, model, prompt, max_tokens, temperature=None):
    """Send one user message; return (text, model echoed by the API).

    ``temperature=None`` leaves the field out, so the vendor default applies. Nothing
    else that shapes sampling (top_p, thinking, reasoning effort) is ever sent.
    """
    key = require_key(provider)
    body = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    headers = {"Content-Type": "application/json"}
    if provider == "anthropic":
        body["max_tokens"] = max_tokens
        headers.update({"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION})
    else:
        body["max_completion_tokens"] = max_tokens
        headers["Authorization"] = "Bearer " + key
    if temperature is not None:
        body["temperature"] = temperature
    request = Request(endpoint(provider), data=json.dumps(body).encode("utf-8"),
                      headers=headers, method="POST")
    try:
        with urlopen(request, timeout=TIMEOUT_S) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise ApiError(_error_message(error), error.code) from None
    except (URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", error)
        raise ApiError(f"could not reach {endpoint(provider)}: {reason}") from None
    except ValueError:
        raise ApiError("the API returned a response that is not JSON") from None
    if provider == "anthropic":
        text = "".join(part.get("text", "") for part in data.get("content", [])
                       if part.get("type") == "text")
    else:
        choices = data.get("choices") or [{}]
        text = (choices[0].get("message") or {}).get("content") or ""
    return text.strip(), data.get("model", model)


def _error_message(error):
    raw = error.read().decode("utf-8", "replace")
    try:
        detail = json.loads(raw).get("error", {})
        message = detail.get("message") if isinstance(detail, dict) else str(detail)
    except (ValueError, AttributeError):
        message = None
    return f"HTTP {error.code}: {message or raw.strip() or error.reason}"
