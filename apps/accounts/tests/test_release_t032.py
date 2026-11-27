"""Pre-Release & Release Verification Tests (Task T-032 / M3).

Covers:
1. Phase C(1): Payment callback DEBUG HTML redirect (T-028-FIX) + ADR-006 late-callback
   slot re-check (never double-books, sets refund_required=True on conflict).
2. Phase C(2): Correlation logging across auth & money paths (booking_id, authority)
   with zero PII (no phone numbers, no OTP codes).
3. Production settings invariants (DEBUG=False, fail-closed SECRET_KEY/ALLOWED_HOSTS,
   HSTS, secure cookies, JSON log formatter, no dev seed venues in fresh DB).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import UTC, datetime, time, timedelta

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, override_settings

from apps.accounts.models import UserRole
from apps.accounts.services import get_redis_client, otp_ip_rate_key, otp_phone_rate_key
from apps.accounts.sms import FakeSmsSender, get_sms_sender
from apps.billing.services.payment import handle_payment_callback, initiate_payment_for_booking
from apps.bookings.models import Booking, BookingStatus
from apps.bookings.services import cancel_booking, create_booking_lock
from apps.panoramas.models import Space, TablePin
from apps.venues.models import (
    OperatingHours,
    SubscriptionPlan,
    Venue,
    VenueSubscription,
    VenueType,
)

User = get_user_model()


@pytest.fixture
def release_venue_fixture(db):
    owner = User.objects.create_user(phone="09120003001", role=UserRole.VENUE_OWNER)
    customer_1 = User.objects.create_user(phone="09120004001", role=UserRole.CUSTOMER)
    customer_2 = User.objects.create_user(phone="09120004002", role=UserRole.CUSTOMER)

    venue = Venue.objects.create(
        owner=owner,
        name="کافه انتشار",
        slug="release-cafe",
        city="تهران",
        venue_type=VenueType.CAFE,
        address="خیابان انقلاب",
        is_approved=True,
    )
    now_utc = datetime.now(UTC)
    plan = SubscriptionPlan.objects.create(name="Release Plan", duration_days=30, price_toman=1_000_000)
    VenueSubscription.objects.create(
        venue=venue,
        plan=plan,
        starts_at=now_utc - timedelta(days=1),
        expires_at=now_utc + timedelta(days=29),
        created_by=owner,
    )
    for weekday in range(7):
        OperatingHours.objects.create(
            venue=venue,
            weekday=weekday,
            open_time=time(9, 0),
            close_time=time(23, 0),
        )
    space = Space.objects.create(venue=venue, name="سالن اصلی", display_order=0)
    pin = TablePin.objects.create(
        venue=venue,
        space=space,
        table_number="R1",
        capacity=4,
        reservation_fee_toman=75_000,
    )
    return {"owner": owner, "customer_1": customer_1, "customer_2": customer_2, "venue": venue, "pin": pin}


@pytest.mark.django_db
def test_phase_c_callback_debug_redirect_and_adr006_late_recheck(release_venue_fixture):
    customer_1 = release_venue_fixture["customer_1"]
    customer_2 = release_venue_fixture["customer_2"]
    pin = release_venue_fixture["pin"]

    slot_day = (datetime.now(UTC) + timedelta(days=3)).date()
    slot_time = time(12, 0)

    # 1. DEBUG GET callback with Accept: text/html redirects safely to stored callback_url
    booking_1 = create_booking_lock(
        user=customer_1,
        table_pin=pin,
        slot_date=slot_day,
        slot_start_time=slot_time,
    )
    tx_1, _ = initiate_payment_for_booking(
        user=customer_1,
        booking_id=booking_1.id,
        idempotency_key="t032-redirect-1",
        callback_url="http://localhost:3000/bookings/callback",
    )

    client = Client()
    with override_settings(DEBUG=True):
        resp = client.get(
            f"/api/v1/billing/callback/?authority={tx_1.provider_reference}&Status=OK",
            HTTP_ACCEPT="text/html,application/xhtml+xml",
        )
    assert resp.status_code == 302
    assert resp["Location"].startswith("http://localhost:3000/bookings/callback?")
    assert f"booking_id={booking_1.id}" in resp["Location"]
    assert "booking_status=CONFIRMED" in resp["Location"]

    # 2. ADR-006 late callback on an already-claimed slot -> EXPIRED + refund_required=True
    slot_day_2 = (datetime.now(UTC) + timedelta(days=4)).date()
    booking_late = create_booking_lock(
        user=customer_1,
        table_pin=pin,
        slot_date=slot_day_2,
        slot_start_time=slot_time,
    )
    tx_late, _ = initiate_payment_for_booking(
        user=customer_1,
        booking_id=booking_late.id,
        idempotency_key="t032-late-1",
        callback_url="http://localhost:3000/bookings/callback",
    )
    # Expire booking_late's lock and let customer_2 claim & confirm the exact same slot
    Booking.objects.filter(pk=booking_late.id).update(
        lock_expires_at=datetime.now(UTC) - timedelta(minutes=1)
    )
    booking_winner = create_booking_lock(
        user=customer_2,
        table_pin=pin,
        slot_date=slot_day_2,
        slot_start_time=slot_time,
    )
    booking_winner.transition_to(BookingStatus.CONFIRMED)

    late_result = handle_payment_callback(callback_params={"authority": tx_late.provider_reference, "Status": "OK"})
    assert late_result.booking_status == BookingStatus.EXPIRED
    assert late_result.refund_required is True
    assert Booking.objects.filter(
        table_pin=pin, slot_date=slot_day_2, slot_start_time=slot_time, status=BookingStatus.CONFIRMED
    ).count() == 1


@pytest.mark.django_db
def test_phase_c_correlation_logs_carry_ids_without_pii(release_venue_fixture, caplog):
    pin = release_venue_fixture["pin"]
    probe_phone = "09127778899"

    redis_client = get_redis_client()
    redis_client.delete(otp_phone_rate_key(probe_phone))
    redis_client.delete(otp_ip_rate_key("127.0.0.1"))

    client = Client()
    with caplog.at_level(logging.INFO):
        req_resp = client.post(
            "/api/v1/auth/otp/request/",
            data=json.dumps({"phone": probe_phone}),
            content_type="application/json",
            REMOTE_ADDR="127.0.0.1",
        )
        assert req_resp.status_code == 200
        sender = get_sms_sender()
        assert isinstance(sender, FakeSmsSender)
        otp_code = sender.last_code_for(probe_phone)
        assert otp_code is not None

        ver_resp = client.post(
            "/api/v1/auth/otp/verify/",
            data=json.dumps({"phone": probe_phone, "code": otp_code}),
            content_type="application/json",
        )
        assert ver_resp.status_code == 200

        customer = User.objects.get(phone=probe_phone)
        slot_day = (datetime.now(UTC) + timedelta(days=5)).date()
        booking = create_booking_lock(
            user=customer,
            table_pin=pin,
            slot_date=slot_day,
            slot_start_time=time(14, 0),
        )
        tx, _ = initiate_payment_for_booking(
            user=customer,
            booking_id=booking.id,
            idempotency_key="t032-corr-1",
            callback_url="http://localhost:3000/bookings/callback",
        )
        handle_payment_callback(callback_params={"authority": tx.provider_reference, "Status": "OK"})
        cancel_booking(booking=booking.id, actor=customer)

    joined_logs = "\n".join(rec.getMessage() for rec in caplog.records)
    assert f"booking_id={booking.id}" in joined_logs
    assert f"authority={tx.provider_reference}" in joined_logs
    assert probe_phone not in joined_logs
    assert otp_code not in joined_logs


@pytest.mark.django_db
def test_production_settings_and_no_dev_seed_data_in_clean_db():
    # Clean test DB never contains dev seed venues
    assert not Venue.objects.filter(slug__in=["sample-cafe-dev", "real-cafe-dev"]).exists()

    # Production settings fail closed when SECRET_KEY or ALLOWED_HOSTS is missing
    env_missing_secret = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.production",
        "SECRET_KEY": "",
        "ALLOWED_HOSTS": "mizban.example",
    }
    res = subprocess.run(
        [sys.executable, "manage.py", "check"],
        cwd=settings.BASE_DIR,
        env=env_missing_secret,
        capture_output=True,
        text=True,
    )
    assert res.returncode != 0
    assert "SECRET_KEY" in (res.stderr + res.stdout)

    # Production settings with valid env enforce DEBUG=False, HSTS, secure cookies, JSON logs
    env_valid = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.production",
        "SECRET_KEY": "prod-check-secret-key-not-used",
        "ALLOWED_HOSTS": "mizban.example",
        "SENTRY_DSN": "",
    }
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import django; django.setup(); from django.conf import settings; "
                "assert settings.DEBUG is False; "
                "assert settings.SECURE_SSL_REDIRECT is True; "
                "assert settings.SESSION_COOKIE_SECURE is True; "
                "assert settings.CSRF_COOKIE_SECURE is True; "
                "assert settings.SESSION_COOKIE_HTTPONLY is True; "
                "assert settings.SECURE_HSTS_SECONDS == 31_536_000; "
                "assert settings.LOGGING['handlers']['console']['formatter'] == 'json'; "
                "print('PROD_OK')"
            ),
        ],
        cwd=settings.BASE_DIR,
        env=env_valid,
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, probe.stderr
    assert "PROD_OK" in probe.stdout
