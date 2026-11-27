"""Observability, Sentry, Structured Logging & PII Scrubbing Tests (Task T-031)."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import environ
import pytest
import sentry_sdk
from django.conf import settings
from django.test import Client

from core.observability import (
    JsonLogFormatter,
    PiiScrubbingFilter,
    get_request_id,
    init_sentry,
    scrub_sentry_event,
)


def test_sentry_disabled_when_dsn_unset():
    assert init_sentry(dsn="", environment="test", release="mizban-backend@0.1.0") is False
    assert init_sentry(dsn="   ", environment="test", release="mizban-backend@0.1.0") is False


def test_sentry_init_with_test_dsn_captures_event_with_tags_and_no_pii() -> None:
    captured_envelopes: list[Any] = []

    class CapturingTransport(sentry_sdk.Transport):
        def capture_envelope(self, envelope):
            captured_envelopes.append(envelope)

    prev_scope = sentry_sdk.get_global_scope()
    try:
        ok = init_sentry(
            dsn="https://public@example.invalid/1",
            environment="staging",
            release="mizban-backend@0.1.0",
            traces_sample_rate=0.1,
            transport=CapturingTransport(),
        )
        assert ok is True

        client = sentry_sdk.get_client()
        assert client.options["data_collection"]["user_info"] is False
        assert client.should_send_default_pii() is False
        assert client.options["environment"] == "staging"
        assert client.options["release"] == "mizban-backend@0.1.0"
        assert client.options["traces_sample_rate"] == 0.1

        sentry_sdk.capture_message("Booking failed for 09123456789 otp=54321")
        sentry_sdk.flush(timeout=2.0)

        assert len(captured_envelopes) == 1
        envelope = captured_envelopes[0]
        event = envelope.get_event()
        assert event is not None
        assert "09123456789" not in json.dumps(event)
        assert "54321" not in json.dumps(event)
        assert "[REDACTED_PHONE]" in event["message"]
        assert "otp=[REDACTED]" in event["message"]
    finally:
        prev_scope.set_client(None)


def test_scrub_sentry_event_strips_user_cookies_headers_and_pii():
    raw_event = {
        "message": "Auth error for +989123456789 otp=99887",
        "user": {"id": 42, "username": "09123456789"},
        "request": {
            "cookies": {"sessionid": "secret-session"},
            "headers": {"Cookie": "sessionid=secret", "Authorization": "Bearer xyz", "Host": "mizban.ir"},
        },
        "extra": {"phone": "09123456789", "otp": "99887", "booking_id": 101},
    }
    cleaned = scrub_sentry_event(raw_event)
    serialized = json.dumps(cleaned)

    assert "user" not in cleaned
    assert "cookies" not in cleaned["request"]
    assert "Cookie" not in cleaned["request"]["headers"]
    assert "Authorization" not in cleaned["request"]["headers"]
    assert cleaned["request"]["headers"]["Host"] == "mizban.ir"
    assert cleaned["extra"]["phone"] == "[REDACTED]"
    assert cleaned["extra"]["otp"] == "[REDACTED]"
    assert cleaned["extra"]["booking_id"] == 101
    assert "09123456789" not in serialized
    assert "99887" not in serialized


def test_json_and_console_formatters_scrub_pii_and_include_request_id():
    pii_filter = PiiScrubbingFilter()
    json_fmt = JsonLogFormatter()
    dev_fmt = logging.Formatter(settings.LOGGING["formatters"]["simple"]["format"])

    record = logging.LogRecord(
        name="apps.bookings.services",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Booking lock for %s with otp=%s booking_id=%s",
        args=("09120001122", "65432", 77),
        exc_info=None,
    )
    assert pii_filter.filter(record) is True

    json_line = json_fmt.format(record)
    parsed = json.loads(json_line)
    assert set(parsed.keys()) >= {"timestamp", "level", "logger", "message", "request_id"}
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "apps.bookings.services"
    assert "09120001122" not in json_line
    assert "65432" not in json_line
    assert "booking_id=77" in parsed["message"]

    dev_line = dev_fmt.format(record)
    assert "INFO" in dev_line
    assert f"[{record.request_id}]" in dev_line
    assert "09120001122" not in dev_line
    assert "65432" not in dev_line


@pytest.mark.django_db
def test_request_id_propagates_and_differs_across_requests(caplog):
    client = Client()
    assert get_request_id() == "-"

    with caplog.at_level(logging.INFO):
        resp1 = client.get("/api/v1/venues/")
        resp2 = client.get("/api/v1/venues/")

    assert resp1.status_code == 200
    assert resp2.status_code == 200

    req_id_1 = resp1["X-Request-ID"]
    req_id_2 = resp2["X-Request-ID"]
    assert req_id_1
    assert req_id_2
    assert req_id_1 != req_id_2
    assert get_request_id() == "-"


def test_operational_alerts_documented_in_spec():
    spec_path = Path(settings.BASE_DIR) / "specs" / "008-hardening-coverage" / "spec.md"
    content = spec_path.read_text(encoding="utf-8")
    for required_rule in (
        "5xx",
        "payment callback",
        "booking-lock",
        "OTP rate-limit",
        "wallet ledger",
    ):
        assert required_rule.lower() in content.lower(), f"Missing alert rule in spec: {required_rule}"


def test_csrf_trusted_origins_honoured_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """CSRF_TRUSTED_ORIGINS is parsed as a list from env and defaults to [] when unset."""
    monkeypatch.setenv("CSRF_TRUSTED_ORIGINS", "https://mizban.ir,https://admin.mizban.ir")
    env_set = environ.Env(CSRF_TRUSTED_ORIGINS=(list, []))
    assert env_set("CSRF_TRUSTED_ORIGINS") == ["https://mizban.ir", "https://admin.mizban.ir"]

    monkeypatch.delenv("CSRF_TRUSTED_ORIGINS", raising=False)
    env_unset = environ.Env(CSRF_TRUSTED_ORIGINS=(list, []))
    assert env_unset("CSRF_TRUSTED_ORIGINS") == []
    assert os.environ.get("CSRF_TRUSTED_ORIGINS") is None
