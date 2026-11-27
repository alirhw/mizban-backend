"""Observability primitives for Miz Ban (Task T-031 / Architecture Spec section 25).

Provides:
- Request ID propagation via contextvars + RequestIdMiddleware (X-Request-ID).
- PII scrubbing for Python logs and Sentry events (phone numbers, OTPs, secrets, card PANs).
- Production JSON log formatter (timestamp, level, logger, message, request_id).
- Fail-open Sentry SDK initialisation (disabled when SENTRY_DSN is unset; data_collection with PII disabled).
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Any

_request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?98|0098|0)9\d{9}(?!\d)")
_OTP_TEXT_PATTERN = re.compile(
    r"(?i)\b(otp|code|otp_code|token|secret|password|sessionid|csrftoken)\b\s*[:=]\s*(['\"]?)([^\s,'\";\}]+)\2"
)
_REQUEST_ID_SAFE_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

_SENSITIVE_KEYS = frozenset(
    {
        "otp",
        "code",
        "otp_code",
        "phone",
        "mobile",
        "phone_number",
        "password",
        "secret",
        "token",
        "csrf_token",
        "csrftoken",
        "sessionid",
        "session_id",
        "authorization",
        "cookie",
        "cookies",
        "card_pan",
        "pan",
        "raw_payload",
        "callback_params",
        "api_key",
    }
)


def get_request_id() -> str:
    """Return the active request_id from contextvars, or '-' outside a request."""
    return _request_id_var.get()


def set_request_id(value: str) -> Token[str]:
    """Bind a request_id into the current execution context."""
    return _request_id_var.set(value)


def reset_request_id(token: Token[str]) -> None:
    """Restore the previous request_id context."""
    _request_id_var.reset(token)


def scrub_pii_text(text: str) -> str:
    """Redact Iranian mobile numbers and inline secret/OTP key-value pairs from text."""
    if not text:
        return text
    cleaned = _PHONE_PATTERN.sub("[REDACTED_PHONE]", text)
    cleaned = _OTP_TEXT_PATTERN.sub(r"\1=[REDACTED]", cleaned)
    return cleaned


def scrub_pii_value(value: Any, *, _depth: int = 0) -> Any:
    """Recursively scrub PII and secrets from nested dicts/lists/strings."""
    if _depth > 8:
        return value
    if isinstance(value, str):
        return scrub_pii_text(value)
    if isinstance(value, dict):
        result: dict[Any, Any] = {}
        for key, item in value.items():
            key_lower = str(key).lower()
            if key_lower in _SENSITIVE_KEYS:
                result[key] = "[REDACTED]"
            else:
                result[key] = scrub_pii_value(item, _depth=_depth + 1)
        return result
    if isinstance(value, list):
        return [scrub_pii_value(item, _depth=_depth + 1) for item in value]
    if isinstance(value, tuple):
        return tuple(scrub_pii_value(item, _depth=_depth + 1) for item in value)
    return value


def scrub_sentry_event(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """Sentry before_send hook: strip user PII, sensitive headers/data, and phone/OTP patterns."""
    del hint
    if not isinstance(event, dict):
        return event
    event.pop("user", None)
    request_data = event.get("request")
    if isinstance(request_data, dict):
        request_data.pop("cookies", None)
        headers = request_data.get("headers")
        if isinstance(headers, dict):
            for sensitive_header in ("Cookie", "cookie", "Authorization", "authorization", "X-CSRFToken"):
                headers.pop(sensitive_header, None)
    return scrub_pii_value(event)


class PiiScrubbingFilter(logging.Filter):
    """Attach request_id to every LogRecord and scrub PII from formatted log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        try:
            rendered = record.getMessage()
        except Exception:
            rendered = str(record.msg)
        scrubbed = scrub_pii_text(rendered)
        if scrubbed != rendered:
            record.msg = scrubbed
            record.args = ()
        return True


class JsonLogFormatter(logging.Formatter):
    """Structured single-line JSON log formatter for production logs."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=UTC).isoformat()
        payload: dict[str, Any] = {
            "timestamp": timestamp,
            "level": record.levelname,
            "logger": record.name,
            "message": scrub_pii_text(record.getMessage()),
            "request_id": getattr(record, "request_id", get_request_id()),
        }
        if record.exc_info:
            payload["exc_info"] = scrub_pii_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


class RequestIdMiddleware:
    """Attach a unique request_id to every HTTP request/response and log context."""

    def __init__(self, get_response: Any) -> None:
        self.get_response = get_response

    def __call__(self, request: Any) -> Any:
        incoming = request.META.get("HTTP_X_REQUEST_ID", "").strip()
        req_id = incoming if _REQUEST_ID_SAFE_PATTERN.fullmatch(incoming) else uuid.uuid4().hex[:16]
        request.request_id = req_id
        token = set_request_id(req_id)
        try:
            response = self.get_response(request)
        finally:
            reset_request_id(token)
        response["X-Request-ID"] = req_id
        return response


def init_sentry(
    *,
    dsn: str,
    environment: str,
    release: str,
    traces_sample_rate: float = 0.1,
    transport: Any = None,
) -> bool:
    """Initialise sentry-sdk when DSN is provided; return False (disabled) when unset."""
    cleaned_dsn = (dsn or "").strip()
    if not cleaned_dsn:
        return False

    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    clamped_rate = max(0.0, min(1.0, float(traces_sample_rate)))
    kwargs: dict[str, Any] = {
        "dsn": cleaned_dsn,
        "integrations": [DjangoIntegration()],
        "environment": environment,
        "release": release,
        "traces_sample_rate": clamped_rate,
        "data_collection": {
            "user_info": False,
            "cookies": {"mode": "allowlist", "terms": []},
            "http_headers": {
                "request": {"mode": "allowlist", "terms": []},
            },
            "url_query_params": {"mode": "allowlist", "terms": []},
            "graphql": {"document": False, "variables": False},
            "gen_ai": {"inputs": False, "outputs": False},
            "database_query_data": False,
            "queues": False,
        },
        "before_send": scrub_sentry_event,
        "before_send_transaction": scrub_sentry_event,
    }
    if transport is not None:
        kwargs["transport"] = transport

    sentry_sdk.init(**kwargs)
    return True
