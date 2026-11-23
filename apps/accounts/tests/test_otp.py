"""Tests for OTP request, verification, rate limiting, and SMS adapters (Task T-006 / TD-006).

Runs against real PostgreSQL and real Redis configured in settings.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, override_settings

from apps.accounts.models import UserRole
from apps.accounts.services import (
    get_redis_client,
    otp_ip_rate_key,
    otp_phone_rate_key,
    otp_redis_key,
)
from apps.accounts.sms import ConsoleSmsSender, FakeSmsSender, get_sms_sender, reset_fake_sms_sender

User = get_user_model()


@pytest.fixture(autouse=True)
def clean_otp_state():
    """Flush OTP Redis keys and reset FakeSmsSender before and after each test."""
    sender = reset_fake_sms_sender()
    client = get_redis_client()
    for key in client.scan_iter("otp:*"):
        client.delete(key)
    yield sender
    sender.reset()
    for key in client.scan_iter("otp:*"):
        client.delete(key)


@pytest.fixture
def client():
    return Client()


# ==============================================================================
# 1. Request: Hash Storage, 5-Digit Code, No Sensitive Logging, FakeSmsSender
# ==============================================================================


@pytest.mark.django_db
def test_otp_request_stores_sha256_hash_not_plaintext_and_never_logs_code_or_phone(
    client, caplog
):
    phone = "09123456789"
    with caplog.at_level(logging.DEBUG):
        resp = client.post(
            "/api/v1/auth/otp/request/",
            data=json.dumps({"phone": phone}),
            content_type="application/json",
            REMOTE_ADDR="10.0.0.1",
        )

    assert resp.status_code == 200
    assert resp.json() == {"sent": True, "expires_in_seconds": 120}

    sender = get_sms_sender()
    assert isinstance(sender, FakeSmsSender)
    assert len(sender.sent_messages) == 1
    sent = sender.sent_messages[0]
    assert sent.phone == phone
    assert re.fullmatch(r"\d{5}", sent.code)

    # Redis stores ONLY SHA-256 hash + attempts=0, with <= 120s TTL
    redis_client = get_redis_client()
    raw = redis_client.get(otp_redis_key(phone))
    assert raw is not None
    assert sent.code not in raw
    data = json.loads(raw)
    assert data["code_hash"] == hashlib.sha256(sent.code.encode("utf-8")).hexdigest()
    assert data["attempts"] == 0
    ttl = redis_client.ttl(otp_redis_key(phone))
    assert 0 < ttl <= 120

    # Neither code nor full phone appears anywhere in logs
    all_logs = "\n".join(rec.getMessage() for rec in caplog.records)
    assert sent.code not in all_logs
    assert phone not in all_logs


@pytest.mark.django_db
def test_otp_request_replaces_previous_code_immediately(client):
    phone = "09121112233"
    r1 = client.post(
        "/api/v1/auth/otp/request/",
        data=json.dumps({"phone": phone}),
        content_type="application/json",
        REMOTE_ADDR="10.0.0.2",
    )
    assert r1.status_code == 200
    sender = get_sms_sender()
    old_code = sender.sent_messages[-1].code

    r2 = client.post(
        "/api/v1/auth/otp/request/",
        data=json.dumps({"phone": phone}),
        content_type="application/json",
        REMOTE_ADDR="10.0.0.2",
    )
    assert r2.status_code == 200
    new_code = sender.sent_messages[-1].code

    if old_code != new_code:
        bad = client.post(
            "/api/v1/auth/otp/verify/",
            data=json.dumps({"phone": phone, "code": old_code}),
            content_type="application/json",
        )
        assert bad.status_code == 400
        assert bad.json()["error_code"] == "OTP_INVALID"

    ok = client.post(
        "/api/v1/auth/otp/verify/",
        data=json.dumps({"phone": phone, "code": new_code}),
        content_type="application/json",
    )
    assert ok.status_code == 200


# ==============================================================================
# 2. Verify Success, Single-Use, Role Preservation, No Session Cookie (T-007 Boundary)
# ==============================================================================


@pytest.mark.django_db
def test_otp_verify_creates_customer_deletes_code_and_sets_no_session_cookie(client):
    phone = "+98 912 345 6700"
    canonical = "09123456700"
    req = client.post(
        "/api/v1/auth/otp/request/",
        data=json.dumps({"phone": phone}),
        content_type="application/json",
        REMOTE_ADDR="10.0.0.3",
    )
    assert req.status_code == 200
    code = get_sms_sender().last_code_for(canonical)
    assert code is not None

    verify = client.post(
        "/api/v1/auth/otp/verify/",
        data=json.dumps({"phone": canonical, "code": code}),
        content_type="application/json",
    )
    assert verify.status_code == 200
    body = verify.json()
    assert body["phone"] == canonical
    assert body["role"] == UserRole.CUSTOMER
    assert isinstance(body["id"], int)

    # T-007 boundary: verify does NOT issue a session cookie yet
    assert "sessionid" not in verify.cookies

    user = User.objects.get(pk=body["id"])
    assert not user.has_usable_password()

    # Single-use: second verify with same code must fail
    replay = client.post(
        "/api/v1/auth/otp/verify/",
        data=json.dumps({"phone": canonical, "code": code}),
        content_type="application/json",
    )
    assert replay.status_code == 400
    assert replay.json()["error_code"] == "OTP_EXPIRED"


@pytest.mark.django_db
def test_otp_verify_preserves_existing_venue_owner_role(client):
    owner = User.objects.create_user(phone="09129998877", role=UserRole.VENUE_OWNER)

    client.post(
        "/api/v1/auth/otp/request/",
        data=json.dumps({"phone": owner.phone}),
        content_type="application/json",
        REMOTE_ADDR="10.0.0.4",
    )
    code = get_sms_sender().last_code_for(owner.phone)

    verify = client.post(
        "/api/v1/auth/otp/verify/",
        data=json.dumps({"phone": owner.phone, "code": code}),
        content_type="application/json",
    )
    assert verify.status_code == 200
    body = verify.json()
    assert body["id"] == owner.id
    assert body["role"] == UserRole.VENUE_OWNER

    owner.refresh_from_db()
    assert owner.role == UserRole.VENUE_OWNER


# ==============================================================================
# 3. Wrong Code, 5-Attempt Burn, and Expiry
# ==============================================================================


@pytest.mark.django_db
def test_otp_wrong_code_increments_attempts_and_5th_failure_burns_code(client):
    phone = "09124445566"
    client.post(
        "/api/v1/auth/otp/request/",
        data=json.dumps({"phone": phone}),
        content_type="application/json",
        REMOTE_ADDR="10.0.0.5",
    )
    real_code = get_sms_sender().last_code_for(phone)
    wrong_code = "00000" if real_code != "00000" else "99999"

    redis_client = get_redis_client()

    # Attempts 1..4 increment counter and keep the code alive
    for expected_attempts in range(1, 5):
        resp = client.post(
            "/api/v1/auth/otp/verify/",
            data=json.dumps({"phone": phone, "code": wrong_code}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "OTP_INVALID"
        stored = json.loads(redis_client.get(otp_redis_key(phone)))
        assert stored["attempts"] == expected_attempts

    # 5th failed attempt burns (deletes) the code
    fifth = client.post(
        "/api/v1/auth/otp/verify/",
        data=json.dumps({"phone": phone, "code": wrong_code}),
        content_type="application/json",
    )
    assert fifth.status_code == 400
    assert fifth.json()["error_code"] == "OTP_INVALID"
    assert redis_client.get(otp_redis_key(phone)) is None

    # Even the real code now fails as expired/missing
    after_burn = client.post(
        "/api/v1/auth/otp/verify/",
        data=json.dumps({"phone": phone, "code": real_code}),
        content_type="application/json",
    )
    assert after_burn.status_code == 400
    assert after_burn.json()["error_code"] == "OTP_EXPIRED"


@pytest.mark.django_db
@override_settings(OTP_TTL_SECONDS=0.001)
def test_otp_expired_code_returns_otp_expired_without_sleeping(client):
    phone = "09125556677"
    req = client.post(
        "/api/v1/auth/otp/request/",
        data=json.dumps({"phone": phone}),
        content_type="application/json",
        REMOTE_ADDR="10.0.0.6",
    )
    assert req.status_code == 200
    code = get_sms_sender().last_code_for(phone)

    # Verify runs after the 1ms Redis PX TTL expires (no sleep() needed)
    verify = client.post(
        "/api/v1/auth/otp/verify/",
        data=json.dumps({"phone": phone, "code": code}),
        content_type="application/json",
    )
    assert verify.status_code == 400
    assert verify.json()["error_code"] == "OTP_EXPIRED"


# ==============================================================================
# 4. Rate Limiting (3 / 10m per phone AND 3 / 10m per IP)
# ==============================================================================


@pytest.mark.django_db
def test_otp_rate_limit_per_phone_blocks_4th_request_429(client):
    phone = "09126667788"
    for idx in range(3):
        resp = client.post(
            "/api/v1/auth/otp/request/",
            data=json.dumps({"phone": phone}),
            content_type="application/json",
            REMOTE_ADDR=f"10.0.1.{idx + 1}",
        )
        assert resp.status_code == 200

    fourth = client.post(
        "/api/v1/auth/otp/request/",
        data=json.dumps({"phone": phone}),
        content_type="application/json",
        REMOTE_ADDR="10.0.1.99",
    )
    assert fourth.status_code == 429
    assert fourth.json()["error_code"] == "OTP_RATE_LIMITED"

    redis_client = get_redis_client()
    assert 0 < redis_client.ttl(otp_phone_rate_key(phone)) <= 600

    # Different phone from a different IP is unaffected
    other = client.post(
        "/api/v1/auth/otp/request/",
        data=json.dumps({"phone": "09126667789"}),
        content_type="application/json",
        REMOTE_ADDR="10.0.1.100",
    )
    assert other.status_code == 200


@pytest.mark.django_db
def test_otp_rate_limit_per_ip_blocks_4th_request_across_different_phones(client):
    same_ip = "10.0.2.50"
    for idx in range(3):
        resp = client.post(
            "/api/v1/auth/otp/request/",
            data=json.dumps({"phone": f"0912777000{idx}"}),
            content_type="application/json",
            REMOTE_ADDR=same_ip,
        )
        assert resp.status_code == 200

    fourth = client.post(
        "/api/v1/auth/otp/request/",
        data=json.dumps({"phone": "09127770009"}),
        content_type="application/json",
        REMOTE_ADDR=same_ip,
    )
    assert fourth.status_code == 429
    assert fourth.json()["error_code"] == "OTP_RATE_LIMITED"

    redis_client = get_redis_client()
    assert 0 < redis_client.ttl(otp_ip_rate_key(same_ip)) <= 600

    # Same new phone from a different IP is unaffected
    other_ip = client.post(
        "/api/v1/auth/otp/request/",
        data=json.dumps({"phone": "09127770009"}),
        content_type="application/json",
        REMOTE_ADDR="10.0.2.51",
    )
    assert other_ip.status_code == 200


# ==============================================================================
# 5. Anti-Enumeration, Validation (422), Trailing Slash, and Adapter Factory
# ==============================================================================


@pytest.mark.django_db
def test_otp_request_response_identical_for_registered_and_unregistered_phones(client):
    registered_phone = "09128881111"
    unregistered_phone = "09128882222"
    User.objects.create_user(phone=registered_phone, role=UserRole.CUSTOMER)

    r_reg = client.post(
        "/api/v1/auth/otp/request/",
        data=json.dumps({"phone": registered_phone}),
        content_type="application/json",
        REMOTE_ADDR="10.0.3.1",
    )
    r_unreg = client.post(
        "/api/v1/auth/otp/request/",
        data=json.dumps({"phone": unregistered_phone}),
        content_type="application/json",
        REMOTE_ADDR="10.0.3.2",
    )
    assert r_reg.status_code == 200
    assert r_unreg.status_code == 200
    assert r_reg.json() == r_unreg.json() == {"sent": True, "expires_in_seconds": 120}


@pytest.mark.django_db
@pytest.mark.parametrize("bad_phone", ["12345", "08123456789", "0912345678", "not-a-phone"])
def test_otp_malformed_phone_returns_422_on_both_endpoints(client, bad_phone):
    req = client.post(
        "/api/v1/auth/otp/request/",
        data=json.dumps({"phone": bad_phone}),
        content_type="application/json",
    )
    assert req.status_code == 422
    assert req.json()["error_code"] == "VALIDATION_ERROR"

    ver = client.post(
        "/api/v1/auth/otp/verify/",
        data=json.dumps({"phone": bad_phone, "code": "12345"}),
        content_type="application/json",
    )
    assert ver.status_code == 422
    assert ver.json()["error_code"] == "VALIDATION_ERROR"


@pytest.mark.django_db
def test_otp_endpoints_trailing_slash_tolerance(client):
    phone = "09129991122"
    req = client.post(
        "/api/v1/auth/otp/request",
        data=json.dumps({"phone": phone}),
        content_type="application/json",
        REMOTE_ADDR="10.0.4.1",
    )
    assert req.status_code == 200
    code = get_sms_sender().last_code_for(phone)

    ver = client.post(
        "/api/v1/auth/otp/verify",
        data=json.dumps({"phone": phone, "code": code}),
        content_type="application/json",
    )
    assert ver.status_code == 200


def test_sms_sender_factory_and_console_debug_guard(capsys, caplog):
    with override_settings(SMS_SENDER="console", DEBUG=False):
        sender = get_sms_sender()
        assert isinstance(sender, ConsoleSmsSender)
        with caplog.at_level(logging.DEBUG):
            sender.send_otp("09123456789", "54321")
        captured = capsys.readouterr()
        assert "54321" not in captured.out
        assert "09123456789" not in captured.out
        assert len(caplog.records) == 0

    with override_settings(SMS_SENDER="console", DEBUG=True):
        sender = get_sms_sender()
        with caplog.at_level(logging.DEBUG):
            sender.send_otp("09123456789", "54321")
        captured = capsys.readouterr()
        assert "54321" in captured.out
        assert "09123456789" not in captured.out
        assert len(caplog.records) == 0
