"""Reproduction and verification tests for T-046 m2 (public slots 404 & 422)."""
from __future__ import annotations

from datetime import time, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.venues.models import OperatingHours, SubscriptionPlan, Venue, VenueReviewStatus, VenueSubscription

User = get_user_model()


@pytest.fixture
def slots_fixture(db):
    owner = User.objects.create_user(phone="09120001001", role=UserRole.VENUE_OWNER)
    plan = SubscriptionPlan.objects.create(
        name="Basic",
        duration_days=30,
        price_toman=100_000,
    )
    now = timezone.now()

    approved_active = Venue.objects.create(
        owner=owner,
        name="Active Cafe",
        slug="active-cafe-m2",
        city="Tehran",
        venue_type="CAFE",
        address="Addr 1",
        is_approved=True,
        review_status=VenueReviewStatus.APPROVED,
    )
    VenueSubscription.objects.create(
        venue=approved_active,
        plan=plan,
        starts_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=29),
        created_by=owner,
    )

    unapproved = Venue.objects.create(
        owner=owner,
        name="Draft Cafe",
        slug="draft-cafe-m2",
        city="Tehran",
        venue_type="CAFE",
        address="Addr 2",
        is_approved=False,
        review_status=VenueReviewStatus.DRAFT,
    )
    VenueSubscription.objects.create(
        venue=unapproved,
        plan=plan,
        starts_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=29),
        created_by=owner,
    )

    expired_sub = Venue.objects.create(
        owner=owner,
        name="Expired Cafe",
        slug="expired-cafe-m2",
        city="Tehran",
        venue_type="CAFE",
        address="Addr 3",
        is_approved=True,
        review_status=VenueReviewStatus.APPROVED,
    )
    VenueSubscription.objects.create(
        venue=expired_sub,
        plan=plan,
        starts_at=now - timedelta(days=31),
        expires_at=now - timedelta(days=1),
        created_by=owner,
    )

    for v in (approved_active, unapproved, expired_sub):
        OperatingHours.objects.create(
            venue=v,
            weekday=0,
            open_time=time(9, 0),
            close_time=time(15, 0),
        )

    return {
        "approved_active": approved_active,
        "unapproved": unapproved,
        "expired_sub": expired_sub,
    }


@pytest.mark.django_db
def test_get_slots_returns_404_for_unapproved_or_expired_subscription_venue(slots_fixture):
    client = Client()
    target_date = (timezone.now() + timedelta(days=3)).date().isoformat()

    r_ok = client.get(
        f"/api/v1/scheduling/venues/{slots_fixture['approved_active'].id}/slots?date={target_date}"
    )
    assert r_ok.status_code == 200

    r_unapproved = client.get(
        f"/api/v1/scheduling/venues/{slots_fixture['unapproved'].id}/slots?date={target_date}"
    )
    assert r_unapproved.status_code == 404

    r_expired = client.get(
        f"/api/v1/scheduling/venues/{slots_fixture['expired_sub'].id}/slots?date={target_date}"
    )
    assert r_expired.status_code == 404


@pytest.mark.django_db
def test_get_slots_returns_422_for_invalid_date_query_param(slots_fixture):
    client = Client()
    venue_id = slots_fixture["approved_active"].id

    for bad_date in ("not-a-date", "1404/13/40", "2026-99-99"):
        resp = client.get(f"/api/v1/scheduling/venues/{venue_id}/slots?date={bad_date}")
        assert resp.status_code == 422, f"Expected 422 for date={bad_date!r}, got {resp.status_code}"
