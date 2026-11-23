"""Shared test helpers for Miz Ban API tests (Task T-007).

Provides one central helper to establish a real Django session on a test Client,
replacing the deleted MinimalAuth phone-header / Bearer-phone test bridge.
"""
from __future__ import annotations

import json
from typing import Any

from django.conf import settings
from django.test import Client

from apps.accounts.services import get_redis_client, otp_ip_rate_key, otp_phone_rate_key
from apps.accounts.sms import FakeSmsSender, get_sms_sender


def authenticate_client(client: Client, user: Any) -> Client:
    """Establish a real Django session for `user` on `client`."""
    client.force_login(user, backend="django.contrib.auth.backends.ModelBackend")
    return client


def login_via_otp(client: Client, phone: str, *, ip: str = "127.0.0.1") -> dict[str, Any]:
    """Drive the full OTP request -> verify flow using FakeSmsSender and return the verify JSON."""
    redis_client = get_redis_client()
    redis_client.delete(otp_phone_rate_key(phone))
    redis_client.delete(otp_ip_rate_key(ip))

    req_resp = client.post(
        "/api/v1/auth/otp/request/",
        data=json.dumps({"phone": phone}),
        content_type="application/json",
        REMOTE_ADDR=ip,
    )
    assert req_resp.status_code == 200, req_resp.content

    sender = get_sms_sender()
    assert isinstance(sender, FakeSmsSender), f"Expected FakeSmsSender, got {type(sender)}"
    code = sender.last_code_for(phone)
    assert code is not None

    # Fetch CSRF token if client enforces CSRF checks
    headers: dict[str, str] = {}
    if getattr(client, "enforce_csrf_checks", False):
        csrf_resp = client.get("/api/v1/auth/csrf/")
        csrf_token = csrf_resp.json()["csrf_token"]
        headers["HTTP_X_CSRFTOKEN"] = csrf_token

    ver_resp = client.post(
        "/api/v1/auth/otp/verify/",
        data=json.dumps({"phone": phone, "code": code}),
        content_type="application/json",
        **headers,
    )
    assert ver_resp.status_code == 200, ver_resp.content
    assert settings.SESSION_COOKIE_NAME in ver_resp.cookies
    return ver_resp.json()
