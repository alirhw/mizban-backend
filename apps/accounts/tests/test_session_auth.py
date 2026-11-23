"""Tests for real Django session authentication and CSRF enforcement (Task T-007 / TD-006).

Replaces test_auth_bridge.py after deleting the MinimalAuth phone-header / Bearer-phone bridge.
"""
from __future__ import annotations

import json

import pytest
from django.test import Client, override_settings

from apps.accounts.models import User, UserRole
from apps.accounts.services import get_redis_client
from apps.accounts.sms import reset_fake_sms_sender
from apps.panoramas.tests.factories import TablePinFactory
from apps.venues.tests.factories import VenueFactory
from core.testing import authenticate_client, login_via_otp

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clean_otp_state():
    sender = reset_fake_sms_sender()
    redis_client = get_redis_client()
    for key in redis_client.scan_iter("otp:*"):
        redis_client.delete(key)
    yield
    sender.reset()
    for key in redis_client.scan_iter("otp:*"):
        redis_client.delete(key)


@pytest.fixture
def client():
    return Client()


# ==============================================================================
# 1. End-to-End OTP Login, Cookie Attributes, /me/, and /logout/
# ==============================================================================


def test_end_to_end_otp_login_sets_httponly_samesite_cookie_and_authenticates_me(client):
    phone = "09121110001"
    user_data = login_via_otp(client, phone, ip="10.10.0.1")

    cookie = client.cookies["sessionid"]
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Lax"

    me = client.get("/api/v1/auth/me/")
    assert me.status_code == 200
    assert me.json() == {
        "id": user_data["id"],
        "phone": phone,
        "role": UserRole.CUSTOMER,
    }


def test_me_and_logout_unauthenticated_return_401(client):
    assert client.get("/api/v1/auth/me/").status_code == 401
    assert client.post("/api/v1/auth/logout/").status_code == 401


def test_logout_flushes_session_and_invalidates_old_cookie(client):
    phone = "09121110002"
    login_via_otp(client, phone, ip="10.10.0.2")
    old_session_key = client.cookies["sessionid"].value

    assert client.get("/api/v1/auth/me/").status_code == 200

    logout_resp = client.post("/api/v1/auth/logout/")
    assert logout_resp.status_code == 200
    assert logout_resp.json() == {"logged_out": True}

    # Current client is now logged out
    assert client.get("/api/v1/auth/me/").status_code == 401

    # Replaying the old session cookie manually also fails
    replay_client = Client()
    replay_client.cookies["sessionid"] = old_session_key
    assert replay_client.get("/api/v1/auth/me/").status_code == 401
    assert replay_client.get("/api/v1/venues/owner/venues").status_code == 401


# ==============================================================================
# 2. Backdoor Deletion Proof (DEBUG=True and DEBUG=False)
# ==============================================================================


@pytest.mark.parametrize("debug_flag", [True, False])
def test_phone_header_and_bearer_phone_backdoors_return_401(client, debug_flag):
    user = User.objects.create_user(phone="09121112233", role=UserRole.VENUE_OWNER)

    with override_settings(DEBUG=debug_flag):
        # X-User-Phone header must be rejected
        r_header = client.get(
            "/api/v1/venues/owner/venues",
            HTTP_X_USER_PHONE=user.phone,
        )
        assert r_header.status_code == 401

        # Authorization: Bearer <phone> must be rejected
        r_bearer = client.get(
            "/api/v1/venues/owner/venues",
            HTTP_AUTHORIZATION=f"Bearer {user.phone}",
        )
        assert r_bearer.status_code == 401

        # Also rejected on /auth/me/
        assert client.get("/api/v1/auth/me/", HTTP_X_USER_PHONE=user.phone).status_code == 401
        assert client.get("/api/v1/auth/me/", HTTP_AUTHORIZATION=f"Bearer {user.phone}").status_code == 401


def test_inactive_user_session_is_rejected_401(client):
    user = User.objects.create_user(phone="09121110003", role=UserRole.CUSTOMER)
    authenticate_client(client, user)
    assert client.get("/api/v1/auth/me/").status_code == 200

    user.is_active = False
    user.save(update_fields=["is_active"])
    assert client.get("/api/v1/auth/me/").status_code == 401


# ==============================================================================
# 3. Role Enforcement & Cross-App Representative Protected Endpoints
# ==============================================================================


def test_role_enforcement_via_session_across_apps(client):
    customer = User.objects.create_user(phone="09121110004", role=UserRole.CUSTOMER)
    owner = User.objects.create_user(phone="09121110005", role=UserRole.VENUE_OWNER)
    venue = VenueFactory(owner=owner, is_approved=True)
    pin = TablePinFactory(venue=venue)

    # Unauthenticated -> 401 on venues, panoramas, bookings
    assert client.get("/api/v1/venues/owner/venues").status_code == 401
    assert client.get(f"/api/v1/panoramas/spaces/{pin.space_id}/pins").status_code == 401
    assert client.post("/api/v1/bookings/999999/cancel/").status_code == 401

    # Customer session -> 403 on owner endpoint, 404 on own/unknown booking cancel (authenticated!)
    authenticate_client(client, customer)
    assert client.get("/api/v1/venues/owner/venues").status_code == 403
    assert client.get(f"/api/v1/panoramas/spaces/{pin.space_id}/pins").status_code == 403
    assert client.post("/api/v1/bookings/999999/cancel/").status_code == 404

    # Venue owner session -> 200 on venues and panoramas
    authenticate_client(client, owner)
    assert client.get("/api/v1/venues/owner/venues").status_code == 200
    assert client.get(f"/api/v1/panoramas/spaces/{pin.space_id}/pins").status_code == 200


# ==============================================================================
# 4. CSRF Protection on Unsafe Methods & /api/v1/auth/csrf/
# ==============================================================================


def test_csrf_enforced_on_unsafe_session_requests_and_succeeds_with_csrf_token():
    csrf_client = Client(enforce_csrf_checks=True)
    phone = "09121110006"
    login_via_otp(csrf_client, phone, ip="10.10.0.6")

    # Unsafe POST with valid session cookie but NO X-CSRFToken header -> 403
    no_csrf = csrf_client.post("/api/v1/auth/logout/")
    assert no_csrf.status_code == 403

    # Obtain CSRF token from /api/v1/auth/csrf/
    csrf_resp = csrf_client.get("/api/v1/auth/csrf/")
    assert csrf_resp.status_code == 200
    assert "csrftoken" in csrf_resp.cookies
    token = csrf_resp.json()["csrf_token"]
    assert token

    # Same unsafe POST with X-CSRFToken header succeeds -> 200
    with_csrf = csrf_client.post(
        "/api/v1/auth/logout/",
        HTTP_X_CSRFTOKEN=token,
    )
    assert with_csrf.status_code == 200
    assert with_csrf.json() == {"logged_out": True}


# ==============================================================================
# 5. Trailing-Slash Tolerance & Public Endpoints Unchanged
# ==============================================================================


def test_session_endpoints_trailing_slash_tolerance(client):
    user = User.objects.create_user(phone="09121110007", role=UserRole.CUSTOMER)
    authenticate_client(client, user)

    assert client.get("/api/v1/auth/csrf").status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 200


def test_public_endpoints_remain_accessible_without_session(client):
    assert client.get("/api/v1/venues/").status_code == 200
    assert client.get("/api/v1/billing/callback/").status_code == 404  # reachable without auth (missing ref)
