"""Reproduction and verification tests for T-046 m14 (callback_url allowlist on initiate)."""
from __future__ import annotations

import json
import uuid
from datetime import time, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.bookings.models import Booking, BookingStatus
from apps.panoramas.models import Space, TablePin
from apps.venues.models import SubscriptionPlan, Venue, VenueReviewStatus, VenueSubscription

User = get_user_model()


@pytest.mark.django_db
def test_initiate_payment_rejects_disallowed_callback_url_with_422():
    owner = User.objects.create_user(phone="09120003001", role=UserRole.VENUE_OWNER)
    customer = User.objects.create_user(phone="09120003002", role=UserRole.CUSTOMER)
    plan = SubscriptionPlan.objects.create(name="Pro", duration_days=30, price_toman=100_000)
    now = timezone.now()

    venue = Venue.objects.create(
        owner=owner,
        name="Callback Cafe",
        slug="callback-cafe-m14",
        city="Tehran",
        venue_type="CAFE",
        address="Addr",
        is_approved=True,
        review_status=VenueReviewStatus.APPROVED,
    )
    VenueSubscription.objects.create(
        venue=venue,
        plan=plan,
        starts_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=29),
        created_by=owner,
    )
    space = Space.objects.create(venue=venue, name="Main")
    pin = TablePin.objects.create(
        venue=venue,
        space=space,
        table_number="T1",
        capacity=4,
        yaw=0.0,
        pitch=0.0,
        reservation_fee_toman=50_000,
    )
    start_at = now + timedelta(days=2)
    booking = Booking.objects.create(
        venue=venue,
        table_pin=pin,
        customer=customer,
        slot_date=start_at.date(),
        slot_start_time=time(10, 0),
        start_at=start_at,
        end_at=start_at + timedelta(minutes=90),
        status=BookingStatus.PENDING_PAYMENT,
        lock_expires_at=now + timedelta(minutes=10),
        amount_online_toman=50_000,
        amount_in_person_toman=0,
    )

    client = Client()
    client.force_login(customer)

    for bad_url in (
        "https://evil.example/phish",
        "//evil.example/phish",
        "javascript:alert(1)",
        "",
    ):
        resp = client.post(
            "/api/v1/billing/initiate/",
            data=json.dumps(
                {
                    "booking_id": booking.id,
                    "idempotency_key": str(uuid.uuid4()),
                    "callback_url": bad_url,
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 422, f"Expected 422 for callback_url={bad_url!r}, got {resp.status_code}"

    resp_ok = client.post(
        "/api/v1/billing/initiate/",
        data=json.dumps(
            {
                "booking_id": booking.id,
                "idempotency_key": str(uuid.uuid4()),
                "callback_url": "http://localhost:3000/payment/callback",
            }
        ),
        content_type="application/json",
    )
    assert resp_ok.status_code == 201
