"""Tests for SubscriptionPlan, VenueSubscription, manual activation, BR-005, and owner read API (Task T-025)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
import json

import pytest
from django.contrib.admin.sites import AdminSite
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.test import Client, RequestFactory

from apps.accounts.models import UserRole
from apps.panoramas.models import PanoramaStatus
from apps.panoramas.tests.factories import PanoramaImageFactory, SpaceFactory, TablePinFactory
from apps.venues.admin import VenueSubscriptionAddForm, VenueSubscriptionAdmin
from apps.venues.models import SubscriptionPlan, Venue, VenueSubscription
from apps.venues.services import activate_subscription
from apps.venues.tests.factories import (
    OperatingHoursFactory,
    SubscriptionPlanFactory,
    UserFactory,
    VenueFactory,
)
from core.exceptions import InactiveSubscriptionPlanError
from core.jalali import format_jalali
from core.testing import authenticate_client

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def admin_user():
    return UserFactory(role=UserRole.ADMIN, is_staff=True)


@pytest.fixture
def owner_user():
    return UserFactory(role=UserRole.VENUE_OWNER)


# ==============================================================================
# 1. SubscriptionPlan DB Constraints
# ==============================================================================


def test_subscription_plan_db_constraints():
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SubscriptionPlan.objects.create(name="Zero Days", duration_days=0, price_toman=100_000)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SubscriptionPlan.objects.create(name="Negative Price", duration_days=30, price_toman=-1)

    SubscriptionPlan.objects.create(name="Unique Plan", duration_days=30, price_toman=500_000)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SubscriptionPlan.objects.create(name="Unique Plan", duration_days=60, price_toman=900_000)


# ==============================================================================
# 2. Activation Service & Stacking Rules (UTC arithmetic)
# ==============================================================================


def test_activate_subscription_never_subscribed_starts_at_now(owner_user, admin_user):
    venue = VenueFactory(owner=owner_user, is_approved=True)
    plan = SubscriptionPlanFactory(name="30-Day", duration_days=30, price_toman=300_000)
    t0 = datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt_timezone.utc)

    sub = activate_subscription(venue, plan=plan, activated_by=admin_user, note="INV-101", now=t0)

    assert sub.venue_id == venue.id
    assert sub.plan_id == plan.id
    assert sub.starts_at == t0
    assert sub.expires_at == t0 + timedelta(days=30)
    assert sub.created_by_id == admin_user.id
    assert sub.note == "INV-101"
    assert venue.has_active_subscription(now=t0 + timedelta(days=29, hours=23))
    assert not venue.has_active_subscription(now=t0 + timedelta(days=30))


def test_activate_subscription_stacks_when_active(owner_user, admin_user):
    venue = VenueFactory(owner=owner_user, is_approved=True)
    plan_30 = SubscriptionPlanFactory(duration_days=30)
    plan_90 = SubscriptionPlanFactory(duration_days=90)

    t0 = datetime(2026, 5, 1, 10, 0, 0, tzinfo=dt_timezone.utc)
    sub1 = activate_subscription(venue, plan=plan_30, activated_by=admin_user, now=t0)
    assert sub1.expires_at == t0 + timedelta(days=30)

    # Renew 10 days later while still active -> stacks onto sub1.expires_at
    t1 = t0 + timedelta(days=10)
    sub2 = activate_subscription(venue, plan=plan_90, activated_by=admin_user, now=t1)
    assert sub2.starts_at == sub1.expires_at
    assert sub2.expires_at == sub1.expires_at + timedelta(days=90)
    assert sub2.expires_at == t0 + timedelta(days=120)


def test_activate_subscription_after_expiry_restarts_from_now(owner_user, admin_user):
    venue = VenueFactory(owner=owner_user, is_approved=True)
    plan_30 = SubscriptionPlanFactory(duration_days=30)

    t0 = datetime(2026, 1, 1, 10, 0, 0, tzinfo=dt_timezone.utc)
    sub1 = activate_subscription(venue, plan=plan_30, activated_by=admin_user, now=t0)

    # 15 days after expiry -> restarts at t_after
    t_after = sub1.expires_at + timedelta(days=15)
    sub2 = activate_subscription(venue, plan=plan_30, activated_by=admin_user, now=t_after)
    assert sub2.starts_at == t_after
    assert sub2.expires_at == t_after + timedelta(days=30)


def test_inactive_plan_cannot_be_activated_but_existing_subscription_survives(owner_user, admin_user):
    venue = VenueFactory(owner=owner_user, is_approved=True)
    plan = SubscriptionPlanFactory(duration_days=30, is_active=True)

    t0 = datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt_timezone.utc)
    sub = activate_subscription(venue, plan=plan, activated_by=admin_user, now=t0)

    # Admin deactivates plan
    plan.is_active = False
    plan.save(update_fields=["is_active"])

    # Existing subscription remains active until expiry
    assert venue.has_active_subscription(now=t0 + timedelta(days=15))
    assert sub.expires_at == t0 + timedelta(days=30)

    # New activation using the inactive plan is rejected
    with pytest.raises(InactiveSubscriptionPlanError) as exc_info:
        activate_subscription(venue, plan=plan, activated_by=admin_user, now=t0 + timedelta(days=15))
    assert exc_info.value.error_code == "INACTIVE_SUBSCRIPTION_PLAN"


# ==============================================================================
# 3. BR-005 End-to-End Enforcement (Public List/Detail, Panoramas, Booking)
# ==============================================================================


def test_br005_expired_and_unapproved_venues_blocked_from_public_and_booking(client, owner_user, admin_user):
    from django.utils import timezone as dj_tz

    future_dt = dj_tz.now() + timedelta(days=3)
    future_date = future_dt.date().isoformat()
    customer = UserFactory(role=UserRole.CUSTOMER)
    venue = VenueFactory(owner=owner_user, is_approved=True)
    OperatingHoursFactory(venue=venue, weekday=future_dt.weekday(), open_time="08:00", close_time="23:00")
    space = SpaceFactory(venue=venue, is_active=True)
    pano = PanoramaImageFactory(space=space, status=PanoramaStatus.READY)
    pano.webp_file.save("pano.webp", ContentFile(b"fake-webp"), save=True)
    space.active_panorama = pano
    space.save(update_fields=["active_panorama"])
    pin = TablePinFactory(venue=venue, space=space, is_active=True, reservation_fee_toman=50_000)

    # Create an already-expired subscription
    past_now = datetime(2020, 1, 1, 10, 0, 0, tzinfo=dt_timezone.utc)
    plan = SubscriptionPlanFactory(duration_days=30)
    activate_subscription(venue, plan=plan, activated_by=admin_user, now=past_now)

    # 1. Expired venue absent from public list & 404 on detail + panoramas
    assert not any(v["slug"] == venue.slug for v in client.get("/api/v1/venues/").json())
    assert client.get(f"/api/v1/venues/{venue.slug}").status_code == 404
    assert client.get(f"/api/v1/venues/{venue.slug}/spaces/").status_code == 404
    assert client.get(f"/api/v1/spaces/{space.id}/panorama").status_code == 404

    # 2. Booking initiation fails with VENUE_NOT_BOOKABLE (400)
    authenticate_client(client, customer)
    book_resp = client.post(
        "/api/v1/bookings/initiate/",
        data=json.dumps(
            {
                "table_pin_id": pin.id,
                "slot_date": future_date,
                "slot_start_time": "10:00",
            }
        ),
        content_type="application/json",
    )
    assert book_resp.status_code == 400
    assert book_resp.json()["error_code"] == "VENUE_NOT_BOOKABLE"

    # 3. Activate fresh subscription -> listed, detail 200, panorama readable, bookable
    activate_subscription(venue, plan=plan, activated_by=admin_user)
    cache.clear()

    assert any(v["slug"] == venue.slug for v in client.get("/api/v1/venues/").json())
    assert client.get(f"/api/v1/venues/{venue.slug}").status_code == 200
    assert client.get(f"/api/v1/venues/{venue.slug}/spaces/").status_code == 200
    assert client.get(f"/api/v1/spaces/{space.id}/panorama").status_code == 200
    book_ok = client.post(
        "/api/v1/bookings/initiate/",
        data=json.dumps(
            {
                "table_pin_id": pin.id,
                "slot_date": future_date,
                "slot_start_time": "10:00",
            }
        ),
        content_type="application/json",
    )
    assert book_ok.status_code == 201

    # 4. Unapproved venue with active subscription is still NOT public or bookable
    venue.is_approved = False
    venue.save(update_fields=["is_approved"])
    cache.clear()
    assert not any(v["slug"] == venue.slug for v in client.get("/api/v1/venues/").json())
    assert client.get(f"/api/v1/venues/{venue.slug}").status_code == 404
    book_unapproved = client.post(
        "/api/v1/bookings/initiate/",
        data=json.dumps(
            {
                "table_pin_id": pin.id,
                "slot_date": future_date,
                "slot_start_time": "12:00",
            }
        ),
        content_type="application/json",
    )
    assert book_unapproved.status_code == 400
    assert book_unapproved.json()["error_code"] == "VENUE_NOT_BOOKABLE"


# ==============================================================================
# 4. Owner Read Endpoint (/owner/venues/{venue_id}/subscription/)
# ==============================================================================


def test_owner_subscription_endpoint_active_and_never_subscribed(client, owner_user, admin_user):
    venue = VenueFactory(owner=owner_user, is_approved=True)
    authenticate_client(client, owner_user)

    # Never subscribed -> 200 with inactive defaults
    r0 = client.get(f"/api/v1/venues/owner/venues/{venue.id}/subscription/")
    assert r0.status_code == 200
    assert r0.json() == {
        "is_active": False,
        "plan_name": None,
        "starts_at": None,
        "expires_at": None,
        "jalali_expires_at": None,
        "days_remaining": 0,
        "has_ever_subscribed": False,
    }

    # Activate 30-day plan -> 200 with active details + Jalali presentation
    plan = SubscriptionPlanFactory(name="Gold Monthly", duration_days=30, price_toman=750_000)
    sub = activate_subscription(venue, plan=plan, activated_by=admin_user)

    r1 = client.get(f"/api/v1/venues/owner/venues/{venue.id}/subscription/")
    assert r1.status_code == 200
    data = r1.json()
    assert data["is_active"] is True
    assert data["plan_name"] == "Gold Monthly"
    assert data["jalali_expires_at"] == format_jalali(sub.expires_at)
    assert 29 <= data["days_remaining"] <= 30
    assert data["has_ever_subscribed"] is True

    # Trailing-slash alias works identically
    r_alias = client.get(f"/api/v1/venues/owner/venues/{venue.id}/subscription")
    assert r_alias.status_code == 200
    assert r_alias.json() == data

    # No purchase / POST path exists on subscription endpoint
    r_post = client.post(f"/api/v1/venues/owner/venues/{venue.id}/subscription/")
    assert r_post.status_code in {404, 405}


def test_owner_subscription_endpoint_permissions_401_403_404(client, owner_user):
    venue = VenueFactory(owner=owner_user)
    other_owner = UserFactory(role=UserRole.VENUE_OWNER)
    customer = UserFactory(role=UserRole.CUSTOMER)

    # Unauthenticated -> 401
    assert client.get(f"/api/v1/venues/owner/venues/{venue.id}/subscription/").status_code == 401

    # Another owner -> 403
    authenticate_client(client, other_owner)
    assert client.get(f"/api/v1/venues/owner/venues/{venue.id}/subscription/").status_code == 403

    # Customer -> 403
    authenticate_client(client, customer)
    assert client.get(f"/api/v1/venues/owner/venues/{venue.id}/subscription/").status_code == 403

    # Unknown venue -> 404
    authenticate_client(client, owner_user)
    assert client.get("/api/v1/venues/owner/venues/999999/subscription/").status_code == 404


# ==============================================================================
# 5. Django Admin Add-Only & Delegation Verification
# ==============================================================================


def test_venue_subscription_admin_is_add_only_and_delegates_to_service(owner_user, admin_user):
    venue = VenueFactory(owner=owner_user)
    plan = SubscriptionPlanFactory(duration_days=15)

    model_admin = VenueSubscriptionAdmin(VenueSubscription, AdminSite())
    rf = RequestFactory()
    req = rf.post("/admin/venues/venuesubscription/add/")
    req.user = admin_user

    assert model_admin.has_change_permission(req) is False
    assert model_admin.has_delete_permission(req) is False
    assert set(VenueSubscriptionAddForm.Meta.fields) == {"venue", "plan", "note"}

    form = VenueSubscriptionAddForm(data={"venue": venue.id, "plan": plan.id, "note": "Bank slip #44"})
    assert form.is_valid(), form.errors
    obj = form.save(commit=False)
    model_admin.save_model(req, obj, form, change=False)

    saved = VenueSubscription.objects.get(pk=obj.pk)
    assert saved.created_by_id == admin_user.id
    assert saved.note == "Bank slip #44"
    assert saved.expires_at == saved.starts_at + timedelta(days=15)


# ==============================================================================
# 6. Truthful Derived VenueOwnerOut.subscription_status & Constant Query Count (T-025-FIX)
# ==============================================================================


def test_owner_venue_detail_derives_subscription_status_truthfully(client, owner_user, admin_user):
    venue = VenueFactory(owner=owner_user, is_approved=True)
    authenticate_client(client, owner_user)

    # 1. Never subscribed -> INACTIVE
    r0 = client.get(f"/api/v1/venues/owner/venues/{venue.id}")
    assert r0.status_code == 200
    assert r0.json()["subscription_status"] == "INACTIVE"
    assert r0.json()["is_publicly_visible"] is False

    # 2. Live derived subscription -> ACTIVE (previously stale-lied INACTIVE)
    plan = SubscriptionPlanFactory(duration_days=30)
    activate_subscription(venue, plan=plan, activated_by=admin_user)
    r1 = client.get(f"/api/v1/venues/owner/venues/{venue.id}")
    assert r1.status_code == 200
    assert r1.json()["subscription_status"] == "ACTIVE"
    assert r1.json()["is_publicly_visible"] is True

    # 3. Expired subscription -> INACTIVE
    VenueSubscription.objects.filter(venue=venue).update(
        starts_at=datetime(2020, 1, 1, tzinfo=dt_timezone.utc),
        expires_at=datetime(2020, 2, 1, tzinfo=dt_timezone.utc),
    )
    r2 = client.get(f"/api/v1/venues/owner/venues/{venue.id}")
    assert r2.status_code == 200
    assert r2.json()["subscription_status"] == "INACTIVE"
    assert r2.json()["is_publicly_visible"] is False


def test_owner_venue_list_derives_mixed_statuses_with_constant_queries(
    client, owner_user, admin_user, django_assert_num_queries
):
    plan = SubscriptionPlanFactory(duration_days=30)
    v_active_1 = VenueFactory(owner=owner_user, is_approved=True, name="Active One")
    activate_subscription(v_active_1, plan=plan, activated_by=admin_user)

    authenticate_client(client, owner_user)

    # 1 venue: 2 session/user queries + 3 owner list queries (venues+Exists, operating_hours, design_addons) = 5
    with django_assert_num_queries(5):
        r_one = client.get("/api/v1/venues/owner/venues")
    assert r_one.status_code == 200
    assert len(r_one.json()) == 1
    assert r_one.json()[0]["subscription_status"] == "ACTIVE"

    # Add 4 more venues (mix of active, never subscribed, and expired)
    v_never = VenueFactory(owner=owner_user, is_approved=True, name="Never Subscribed")
    v_expired = VenueFactory(owner=owner_user, is_approved=True, name="Expired One")
    activate_subscription(
        v_expired,
        plan=plan,
        activated_by=admin_user,
        now=datetime(2020, 1, 1, tzinfo=dt_timezone.utc),
    )
    v_active_2 = VenueFactory(owner=owner_user, is_approved=False, name="Active Unapproved")
    activate_subscription(v_active_2, plan=plan, activated_by=admin_user)
    v_active_3 = VenueFactory(owner=owner_user, is_approved=True, name="Active Three")
    activate_subscription(v_active_3, plan=plan, activated_by=admin_user)

    # 5 venues: query count MUST remain exactly 5 (zero N+1)
    with django_assert_num_queries(5):
        r_many = client.get("/api/v1/venues/owner/venues")
    assert r_many.status_code == 200
    by_id = {item["id"]: item for item in r_many.json()}
    assert len(by_id) == 5
    assert by_id[v_active_1.id]["subscription_status"] == "ACTIVE"
    assert by_id[v_active_1.id]["is_publicly_visible"] is True
    assert by_id[v_never.id]["subscription_status"] == "INACTIVE"
    assert by_id[v_never.id]["is_publicly_visible"] is False
    assert by_id[v_expired.id]["subscription_status"] == "INACTIVE"
    assert by_id[v_expired.id]["is_publicly_visible"] is False
    assert by_id[v_active_2.id]["subscription_status"] == "ACTIVE"
    assert by_id[v_active_2.id]["is_publicly_visible"] is False
    assert by_id[v_active_3.id]["subscription_status"] == "ACTIVE"
    assert by_id[v_active_3.id]["is_publicly_visible"] is True
