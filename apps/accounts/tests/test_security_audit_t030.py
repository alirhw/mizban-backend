"""Security & Privacy Audit Regression Suite (Task T-030 / M3 Hardening).

Verifies:
1. Unauthenticated requests to protected customer, owner, and admin endpoints return 401.
2. Role enforcement (CUSTOMER vs VENUE_OWNER vs ADMIN) returns 403 on mismatched routes.
3. Cross-user IDOR probes (foreign customer or foreign venue owner) are rejected (403/404).
4. Privacy & secret-leak invariants:
   - Public venue responses never expose owner phone numbers.
   - Owner venue booking responses mask customer phone numbers (never raw full phone).
   - OTP request & verify logs never contain the OTP code or full phone numbers.
   - WalletAdmin and WalletTransactionAdmin forbid add/delete (and change on ledger).
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, time, timedelta

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory

from apps.accounts.models import UserRole
from apps.accounts.services import get_redis_client, otp_ip_rate_key, otp_phone_rate_key
from apps.accounts.sms import FakeSmsSender, get_sms_sender
from apps.bookings.models import Booking, BookingStatus
from apps.panoramas.models import Space, TablePin
from apps.venues.models import (
    OperatingHours,
    SubscriptionPlan,
    Venue,
    VenueSubscription,
    VenueType,
)
from apps.wallets.admin import WalletAdmin, WalletTransactionAdmin
from apps.wallets.models import Wallet, WalletTransaction
from core.testing import authenticate_client

User = get_user_model()


@pytest.fixture
def security_fixture(db):
    owner_a = User.objects.create_user(phone="09120001001", role=UserRole.VENUE_OWNER)
    owner_b = User.objects.create_user(phone="09120001002", role=UserRole.VENUE_OWNER)
    customer_a = User.objects.create_user(phone="09120002001", role=UserRole.CUSTOMER)
    customer_b = User.objects.create_user(phone="09120002002", role=UserRole.CUSTOMER)

    venue_a = Venue.objects.create(
        owner=owner_a,
        name="کافه ممیزی",
        slug="audit-cafe-a",
        city="تهران",
        venue_type=VenueType.CAFE,
        address="خیابان ولیعصر",
        is_approved=True,
    )
    now_utc = datetime.now(UTC)
    plan = SubscriptionPlan.objects.create(name="Monthly", duration_days=30, price_toman=1_000_000)
    VenueSubscription.objects.create(
        venue=venue_a,
        plan=plan,
        starts_at=now_utc - timedelta(days=1),
        expires_at=now_utc + timedelta(days=29),
        created_by=owner_a,
    )
    OperatingHours.objects.create(
        venue=venue_a,
        weekday=0,
        open_time=time(9, 0),
        close_time=time(23, 0),
    )
    space_a = Space.objects.create(venue=venue_a, name="سالن اصلی", display_order=0)
    pin_a = TablePin.objects.create(
        venue=venue_a,
        space=space_a,
        table_number="T1",
        capacity=4,
        reservation_fee_toman=50_000,
    )

    slot_start = datetime.now(UTC) + timedelta(days=3)
    slot_end = slot_start + timedelta(minutes=90)
    booking_a = Booking.objects.create(
        customer=customer_a,
        venue=venue_a,
        table_pin=pin_a,
        start_at=slot_start,
        end_at=slot_end,
        slot_date=slot_start.date(),
        slot_start_time=time(12, 0),
        status=BookingStatus.CONFIRMED,
        amount_online_toman=50_000,
        amount_in_person_toman=0,
    )

    return {
        "owner_a": owner_a,
        "owner_b": owner_b,
        "customer_a": customer_a,
        "customer_b": customer_b,
        "venue_a": venue_a,
        "pin_a": pin_a,
        "booking_a": booking_a,
    }


@pytest.mark.django_db
def test_unauthenticated_requests_rejected_401(security_fixture):
    client = Client()
    booking_a = security_fixture["booking_a"]
    venue_a = security_fixture["venue_a"]
    pin_a = security_fixture["pin_a"]

    protected_gets = [
        "/api/v1/bookings/my/",
        f"/api/v1/bookings/{booking_a.id}/receipt/",
        "/api/v1/wallets/me/",
        "/api/v1/venues/owner/venues",
        f"/api/v1/venues/owner/venues/{venue_a.id}/bookings/",
        f"/api/v1/scheduling/pins/{pin_a.id}/blocked-slots/",
    ]
    for path in protected_gets:
        resp = client.get(path)
        assert resp.status_code == 401, f"Expected 401 for GET {path}, got {resp.status_code}"

    protected_posts = [
        ("/api/v1/bookings/initiate/", {}),
        (f"/api/v1/bookings/{booking_a.id}/cancel/", {}),
        ("/api/v1/billing/initiate/", {}),
        (f"/api/v1/venues/admin/venues/{venue_a.id}/approve", {}),
    ]
    for path, body in protected_posts:
        resp = client.post(path, data=json.dumps(body), content_type="application/json")
        assert resp.status_code == 401, f"Expected 401 for POST {path}, got {resp.status_code}"


@pytest.mark.django_db
def test_role_enforcement_blocks_cross_role_access(security_fixture):
    owner_client = authenticate_client(Client(), security_fixture["owner_a"])
    customer_client = authenticate_client(Client(), security_fixture["customer_a"])
    venue_a = security_fixture["venue_a"]
    booking_a = security_fixture["booking_a"]

    # VENUE_OWNER cannot access CUSTOMER-only endpoints
    assert owner_client.get("/api/v1/bookings/my/").status_code == 403
    assert owner_client.get("/api/v1/wallets/me/").status_code == 403
    assert (
        owner_client.post(
            "/api/v1/billing/initiate/",
            data=json.dumps(
                {
                    "booking_id": booking_a.id,
                    "idempotency_key": "role-probe-1",
                    "callback_url": "http://localhost:3000/cb",
                }
            ),
            content_type="application/json",
        ).status_code
        == 403
    )

    # CUSTOMER cannot access VENUE_OWNER or ADMIN endpoints
    assert customer_client.get("/api/v1/venues/owner/venues").status_code == 403
    assert customer_client.get(f"/api/v1/venues/owner/venues/{venue_a.id}/bookings/").status_code == 403
    assert customer_client.post(f"/api/v1/venues/admin/venues/{venue_a.id}/approve").status_code == 403


@pytest.mark.django_db
def test_cross_user_idor_probes_rejected(security_fixture):
    customer_b_client = authenticate_client(Client(), security_fixture["customer_b"])
    owner_b_client = authenticate_client(Client(), security_fixture["owner_b"])
    booking_a = security_fixture["booking_a"]
    venue_a = security_fixture["venue_a"]
    pin_a = security_fixture["pin_a"]

    # Foreign customer cannot read receipt, cancel, or initiate payment for booking_a
    assert customer_b_client.get(f"/api/v1/bookings/{booking_a.id}/receipt/").status_code in (403, 404)
    assert customer_b_client.post(f"/api/v1/bookings/{booking_a.id}/cancel/").status_code in (403, 404)
    assert (
        customer_b_client.post(
            "/api/v1/billing/initiate/",
            data=json.dumps(
                {
                    "booking_id": booking_a.id,
                    "idempotency_key": "idor-probe-1",
                    "callback_url": "http://localhost:3000/cb",
                }
            ),
            content_type="application/json",
        ).status_code
        in (403, 404)
    )

    # Foreign owner cannot read/update venue_a, its bookings, or its blocked slots
    assert owner_b_client.get(f"/api/v1/venues/owner/venues/{venue_a.id}").status_code in (403, 404)
    assert (
        owner_b_client.put(
            f"/api/v1/venues/owner/venues/{venue_a.id}",
            data=json.dumps({"name": "Hacked"}),
            content_type="application/json",
        ).status_code
        in (403, 404)
    )
    assert owner_b_client.get(f"/api/v1/venues/owner/venues/{venue_a.id}/bookings/").status_code in (403, 404)
    assert owner_b_client.get(f"/api/v1/scheduling/pins/{pin_a.id}/blocked-slots/").status_code in (403, 404)


@pytest.mark.django_db
def test_privacy_no_phone_or_otp_leak_in_responses_and_logs(security_fixture, caplog):
    owner_a = security_fixture["owner_a"]
    customer_a = security_fixture["customer_a"]
    venue_a = security_fixture["venue_a"]

    client = Client()

    # 1. Public venue catalogue/detail never exposes owner phone
    list_resp = client.get("/api/v1/venues/")
    assert list_resp.status_code == 200
    assert owner_a.phone not in list_resp.content.decode("utf-8")

    detail_resp = client.get(f"/api/v1/venues/{venue_a.slug}")
    assert detail_resp.status_code == 200
    assert owner_a.phone not in detail_resp.content.decode("utf-8")

    # 2. Owner bookings endpoint masks customer phone
    owner_client = authenticate_client(Client(), owner_a)
    bookings_resp = owner_client.get(f"/api/v1/venues/owner/venues/{venue_a.id}/bookings/")
    assert bookings_resp.status_code == 200
    body_text = bookings_resp.content.decode("utf-8")
    assert customer_a.phone not in body_text
    payload = bookings_resp.json()
    assert len(payload) == 1
    assert "*" in payload[0]["customer_phone_masked"]

    # 3. OTP request + verify logs never leak OTP code or full phone
    probe_phone = "09123459876"
    redis_client = get_redis_client()
    redis_client.delete(otp_phone_rate_key(probe_phone))
    redis_client.delete(otp_ip_rate_key("127.0.0.1"))

    with caplog.at_level(logging.DEBUG):
        req_resp = client.post(
            "/api/v1/auth/otp/request/",
            data=json.dumps({"phone": probe_phone}),
            content_type="application/json",
            REMOTE_ADDR="127.0.0.1",
        )
        assert req_resp.status_code == 200
        sender = get_sms_sender()
        assert isinstance(sender, FakeSmsSender)
        code = sender.last_code_for(probe_phone)
        assert code is not None

        ver_resp = client.post(
            "/api/v1/auth/otp/verify/",
            data=json.dumps({"phone": probe_phone, "code": code}),
            content_type="application/json",
        )
        assert ver_resp.status_code == 200

    joined_logs = "\n".join(rec.getMessage() for rec in caplog.records)
    assert code not in joined_logs
    assert probe_phone not in joined_logs


@pytest.mark.django_db
def test_wallet_admin_is_strictly_read_only(security_fixture):
    staff_user = User.objects.create_user(
        phone="09120009999", role=UserRole.ADMIN, is_staff=True, is_superuser=True
    )
    req = RequestFactory().get("/admin/")
    req.user = staff_user

    wallet_admin = WalletAdmin(Wallet, AdminSite())
    tx_admin = WalletTransactionAdmin(WalletTransaction, AdminSite())

    assert wallet_admin.has_add_permission(req) is False
    assert wallet_admin.has_delete_permission(req) is False

    assert tx_admin.has_add_permission(req) is False
    assert tx_admin.has_change_permission(req) is False
    assert tx_admin.has_delete_permission(req) is False
