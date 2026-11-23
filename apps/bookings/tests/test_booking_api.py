"""API tests for Initiate Booking endpoint (Task T-013).

POST /api/v1/bookings/initiate/
Exposing the atomic create_booking_lock service from T-012.

Acceptance criteria:
1. Happy path returns 201 PENDING_PAYMENT with 10-minute lock, lock_expires_at, and Jalali times.
2. Double initiate returns 409 (SLOT_ALREADY_RESERVED).
3. A second customer cannot initiate on another customer's locked slot (409).
4. Initiate inside 24h returns 400 (LEAD_TIME_VIOLATION).
5. Validation errors return 422 with standard error envelope (VALIDATION_ERROR).
6. Role enforcement: Only CUSTOMER can initiate (401 unauthenticated, 403 for owner/admin).
7. Unapproved or inactive venue returns 400 (VENUE_NOT_BOOKABLE).
8. Inactive table pin returns 400 (TABLE_NOT_BOOKABLE).
9. Venue mismatch returns 400 (VENUE_MISMATCH).
10. Operating hours validation returns 400 (INVALID_SLOT) for invalid slot times.
11. Expired lock allows subsequent initiate to succeed.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import json

from django.core.cache import cache
from django.test import Client
from django.utils import timezone as dj_timezone
import pytest

from apps.accounts.models import UserRole
from apps.bookings.models import Booking, BookingAddon, BookingStatus
from core.testing import authenticate_client
from apps.panoramas.tests.factories import TablePinFactory
from apps.venues.models import SubscriptionStatus
from apps.venues.tests.factories import DesignAddonFactory, UserFactory, VenueFactory
from core.jalali import format_jalali, to_jalali


@pytest.fixture(autouse=True)
def setup_test_env(settings):
    settings.DEBUG = True
    cache.clear()
    yield
    cache.clear()


class ApiClientHelper:
    def __init__(self, client: Client):
        self.client = client

    def post_json(self, path: str, data: dict, user=None):
        if user:
            authenticate_client(self.client, user)
        else:
            self.client.logout()
        return self.client.post(
            path,
            data=json.dumps(data),
            content_type="application/json",
        )

    def get(self, path: str, user=None):
        if user:
            authenticate_client(self.client, user)
        else:
            self.client.logout()
        return self.client.get(path)


@pytest.fixture
def api(client):
    return ApiClientHelper(client)


@pytest.fixture
def customer_user():
    return UserFactory(role=UserRole.CUSTOMER, phone="09121112233")


@pytest.fixture
def other_customer_user():
    return UserFactory(role=UserRole.CUSTOMER, phone="09124445566")


@pytest.fixture
def owner_user():
    return UserFactory(role=UserRole.VENUE_OWNER, phone="09127778899")


@pytest.fixture
def admin_user():
    return UserFactory(role=UserRole.ADMIN, phone="09120000000", is_staff=True)


@pytest.fixture
def active_venue(owner_user):
    return VenueFactory(
        owner=owner_user,
        is_approved=True,
        subscription_status=SubscriptionStatus.ACTIVE,
    )


@pytest.fixture
def table_pin(active_venue):
    # TablePinFactory automatically populates 7 days of 08:00 - 23:00 operating hours
    return TablePinFactory(venue=active_venue, is_active=True)


@pytest.mark.django_db
def test_initiate_booking_happy_path(api, customer_user, table_pin):
    """Happy path: Customer reserves a slot >= 24h ahead -> 201 PENDING_PAYMENT with 10m lock."""
    # Find a valid slot >= 24h ahead
    target_date = (dj_timezone.now() + timedelta(days=2)).date()
    target_time_str = "10:00"

    payload = {
        "table_pin_id": table_pin.id,
        "slot_date": target_date.isoformat(),
        "slot_start_time": target_time_str,
    }

    resp = api.post_json("/api/v1/bookings/initiate/", payload, user=customer_user)
    assert resp.status_code == 201
    data = resp.json()

    assert data["status"] == BookingStatus.PENDING_PAYMENT
    assert data["table_pin_id"] == table_pin.id
    assert data["venue_id"] == table_pin.venue_id
    assert "booking_id" in data
    assert data["booking_id"] == data["id"]
    assert data["amount_online_toman"] == 50_000
    assert data["amount_in_person_toman"] == 0

    # 10-minute lock verification (TD-004)
    locked_at = datetime.fromisoformat(data["locked_at"])
    expires_at = datetime.fromisoformat(data["lock_expires_at"])
    diff = (expires_at - locked_at).total_seconds()
    assert abs(diff - 600) < 5  # Exactly 600s (10 minutes)

    # Jalali presentation fields (ARCH-006)
    assert data["start_jalali"] != ""
    assert data["end_jalali"] != ""
    assert data["jalali_date"] != ""

    # DB state verification
    booking = Booking.objects.get(id=data["booking_id"])
    assert booking.customer == customer_user
    assert booking.status == BookingStatus.PENDING_PAYMENT
    assert booking.lock_expires_at > dj_timezone.now()


@pytest.mark.django_db
def test_initiate_booking_with_design_addons(api, customer_user, table_pin):
    """Design addons are snapshotted on the booking and marked payable in person (BR-003)."""
    addon1 = DesignAddonFactory(venue=table_pin.venue, fee=20_000, is_active=True)
    addon2 = DesignAddonFactory(venue=table_pin.venue, fee=35_000, is_active=True)

    target_date = (dj_timezone.now() + timedelta(days=2)).date()
    payload = {
        "table_pin_id": table_pin.id,
        "slot_date": target_date.isoformat(),
        "slot_start_time": "12:00",
        "addon_ids": [addon1.id, addon2.id],
    }

    resp = api.post_json("/api/v1/bookings/initiate/", payload, user=customer_user)
    assert resp.status_code == 201
    data = resp.json()

    assert data["amount_online_toman"] == 50_000
    assert data["amount_in_person_toman"] == 55_000

    booking = Booking.objects.get(id=data["booking_id"])
    assert booking.amount_in_person_toman == 55_000
    assert booking.addons.count() == 2

    snapshots = {a.design_addon_id: a.price_snapshot_toman for a in booking.addons.all()}
    assert snapshots[addon1.id] == 20_000
    assert snapshots[addon2.id] == 35_000


@pytest.mark.django_db
def test_initiate_booking_with_jalali_date_string(api, customer_user, table_pin):
    """Jalali date strings (e.g. '1404/10/15') are properly resolved."""
    target_dt = dj_timezone.now() + timedelta(days=3)
    jalali_str = format_jalali(target_dt, fmt="%Y/%m/%d")

    payload = {
        "table_pin_id": table_pin.id,
        "slot_date": jalali_str,
        "slot_start_time": "14:00",
    }

    resp = api.post_json("/api/v1/bookings/initiate/", payload, user=customer_user)
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == BookingStatus.PENDING_PAYMENT

    booking = Booking.objects.get(id=data["booking_id"])
    assert booking.slot_date == target_dt.astimezone(dj_timezone.get_current_timezone()).date()


@pytest.mark.django_db
def test_double_initiate_returns_409(api, customer_user, table_pin):
    """Double initiate for the same table and slot returns 409 SLOT_ALREADY_RESERVED."""
    target_date = (dj_timezone.now() + timedelta(days=2)).date()
    payload = {
        "table_pin_id": table_pin.id,
        "slot_date": target_date.isoformat(),
        "slot_start_time": "16:00",
    }

    # 1. First initiate succeeds
    resp1 = api.post_json("/api/v1/bookings/initiate/", payload, user=customer_user)
    assert resp1.status_code == 201

    # 2. Second initiate for same customer & slot fails with 409
    resp2 = api.post_json("/api/v1/bookings/initiate/", payload, user=customer_user)
    assert resp2.status_code == 409
    err = resp2.json()
    assert err["error_code"] == "SLOT_ALREADY_RESERVED"
    assert "reserved" in err["message"].lower() or "locked" in err["message"].lower()


@pytest.mark.django_db
def test_second_customer_cannot_initiate_on_locked_slot(
    api, customer_user, other_customer_user, table_pin
):
    """Customer B cannot initiate on a slot locked by Customer A (409 SLOT_ALREADY_RESERVED)."""
    target_date = (dj_timezone.now() + timedelta(days=2)).date()
    payload = {
        "table_pin_id": table_pin.id,
        "slot_date": target_date.isoformat(),
        "slot_start_time": "18:00",
    }

    # Customer A acquires hold
    resp_a = api.post_json("/api/v1/bookings/initiate/", payload, user=customer_user)
    assert resp_a.status_code == 201

    # Customer B attempts to acquire same hold -> rejected 409
    resp_b = api.post_json("/api/v1/bookings/initiate/", payload, user=other_customer_user)
    assert resp_b.status_code == 409
    err = resp_b.json()
    assert err["error_code"] == "SLOT_ALREADY_RESERVED"


@pytest.mark.django_db
def test_initiate_inside_24h_lead_time_returns_400(api, customer_user, table_pin):
    """Initiating a slot starting less than 24 hours from now returns 400 LEAD_TIME_VIOLATION (BR-002)."""
    # Slot 6 hours from now
    target_dt = dj_timezone.now() + timedelta(hours=6)
    target_date = target_dt.astimezone(dj_timezone.get_current_timezone()).date()
    target_time_str = "08:00"

    payload = {
        "table_pin_id": table_pin.id,
        "slot_date": target_date.isoformat(),
        "slot_start_time": target_time_str,
    }

    resp = api.post_json("/api/v1/bookings/initiate/", payload, user=customer_user)
    assert resp.status_code == 400
    err = resp.json()
    assert err["error_code"] == "LEAD_TIME_VIOLATION"
    assert "24 hours" in err["message"].lower()

    # Verify no booking was persisted
    assert not Booking.objects.filter(
        table_pin=table_pin,
        slot_date=target_date,
        slot_start_time=time(8, 0),
    ).exists()


@pytest.mark.django_db
def test_initiate_booking_unauthenticated_returns_401(api, table_pin):
    """Unauthenticated calls return 401 Unauthorized."""
    target_date = (dj_timezone.now() + timedelta(days=2)).date()
    payload = {
        "table_pin_id": table_pin.id,
        "slot_date": target_date.isoformat(),
        "slot_start_time": "10:00",
    }
    resp = api.post_json("/api/v1/bookings/initiate/", payload, user=None)
    assert resp.status_code == 401


@pytest.mark.django_db
def test_role_enforcement_non_customers_forbidden(api, owner_user, admin_user, table_pin):
    """Role enforcement: Venue owners and Admins cannot initiate customer bookings (403 FORBIDDEN)."""
    target_date = (dj_timezone.now() + timedelta(days=2)).date()
    payload = {
        "table_pin_id": table_pin.id,
        "slot_date": target_date.isoformat(),
        "slot_start_time": "10:00",
    }

    # 1. Owner attempt
    resp_owner = api.post_json("/api/v1/bookings/initiate/", payload, user=owner_user)
    assert resp_owner.status_code == 403
    err_owner = resp_owner.json()
    assert err_owner["error_code"] == "FORBIDDEN"

    # 2. Admin attempt
    resp_admin = api.post_json("/api/v1/bookings/initiate/", payload, user=admin_user)
    assert resp_admin.status_code == 403
    err_admin = resp_admin.json()
    assert err_admin["error_code"] == "FORBIDDEN"


@pytest.mark.django_db
def test_validation_errors_return_standard_envelope(api, customer_user):
    """Malformed payloads return 422 VALIDATION_ERROR with standard envelope."""
    # 1. Invalid date format
    resp1 = api.post_json(
        "/api/v1/bookings/initiate/",
        {"table_pin_id": 1, "slot_date": "not-a-date", "slot_start_time": "10:00"},
        user=customer_user,
    )
    assert resp1.status_code == 422
    err1 = resp1.json()
    assert err1["error_code"] == "VALIDATION_ERROR"
    assert "errors" in err1["details"]

    # 2. Invalid time format
    resp2 = api.post_json(
        "/api/v1/bookings/initiate/",
        {"table_pin_id": 1, "slot_date": "2026-05-10", "slot_start_time": "99:99"},
        user=customer_user,
    )
    assert resp2.status_code == 422
    err2 = resp2.json()
    assert err2["error_code"] == "VALIDATION_ERROR"

    # 3. Non-positive table_pin_id
    resp3 = api.post_json(
        "/api/v1/bookings/initiate/",
        {"table_pin_id": 0, "slot_date": "2026-05-10", "slot_start_time": "10:00"},
        user=customer_user,
    )
    assert resp3.status_code == 422
    err3 = resp3.json()
    assert err3["error_code"] == "VALIDATION_ERROR"


@pytest.mark.django_db
def test_unapproved_or_inactive_venue_returns_400(api, customer_user, owner_user):
    """BR-005: Cannot initiate on unapproved or subscription-inactive venues (400 VENUE_NOT_BOOKABLE)."""
    target_date = (dj_timezone.now() + timedelta(days=2)).date()

    # 1. Unapproved venue
    unapproved_venue = VenueFactory(
        owner=owner_user,
        is_approved=False,
        subscription_status=SubscriptionStatus.ACTIVE,
    )
    pin_unapproved = TablePinFactory(venue=unapproved_venue)

    resp_unapp = api.post_json(
        "/api/v1/bookings/initiate/",
        {"table_pin_id": pin_unapproved.id, "slot_date": target_date.isoformat(), "slot_start_time": "10:00"},
        user=customer_user,
    )
    assert resp_unapp.status_code == 400
    assert resp_unapp.json()["error_code"] == "VENUE_NOT_BOOKABLE"

    # 2. Inactive subscription venue
    inactive_venue = VenueFactory(
        owner=owner_user,
        is_approved=True,
        subscription_status=SubscriptionStatus.INACTIVE,
    )
    pin_inactive_sub = TablePinFactory(venue=inactive_venue)

    resp_inact = api.post_json(
        "/api/v1/bookings/initiate/",
        {"table_pin_id": pin_inactive_sub.id, "slot_date": target_date.isoformat(), "slot_start_time": "10:00"},
        user=customer_user,
    )
    assert resp_inact.status_code == 400
    assert resp_inact.json()["error_code"] == "VENUE_NOT_BOOKABLE"


@pytest.mark.django_db
def test_venue_mismatch_returns_400(api, customer_user, active_venue, table_pin, owner_user):
    """Providing venue_id that does not match table_pin.venue_id returns 400 VENUE_MISMATCH."""
    other_venue = VenueFactory(
        owner=owner_user,
        is_approved=True,
        subscription_status=SubscriptionStatus.ACTIVE,
    )
    target_date = (dj_timezone.now() + timedelta(days=2)).date()

    payload = {
        "table_pin_id": table_pin.id,
        "venue_id": other_venue.id,
        "slot_date": target_date.isoformat(),
        "slot_start_time": "10:00",
    }
    resp = api.post_json("/api/v1/bookings/initiate/", payload, user=customer_user)
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "VENUE_MISMATCH"


@pytest.mark.django_db
def test_outside_operating_hours_slot_returns_400(api, customer_user, table_pin):
    """Requesting a time slot outside operating hours returns 400 INVALID_SLOT."""
    target_date = (dj_timezone.now() + timedelta(days=2)).date()

    # Operating hours are 08:00 - 23:00, with 90m slots and 30m buffers:
    # 08:00, 10:00, 12:00, 14:00, 16:00, 18:00, 20:00.
    # 03:00 is outside operating hours.
    payload = {
        "table_pin_id": table_pin.id,
        "slot_date": target_date.isoformat(),
        "slot_start_time": "03:00",
    }
    resp = api.post_json("/api/v1/bookings/initiate/", payload, user=customer_user)
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "INVALID_SLOT"


@pytest.mark.django_db
def test_expired_lock_frees_slot_for_another_customer(
    api, customer_user, other_customer_user, table_pin
):
    """An unpaid lock that has expired (lock_expires_at in past) permits a new initiate."""
    target_date = (dj_timezone.now() + timedelta(days=2)).date()
    target_time_str = "10:00"
    payload = {
        "table_pin_id": table_pin.id,
        "slot_date": target_date.isoformat(),
        "slot_start_time": target_time_str,
    }

    # 1. Customer A initiates
    resp_a = api.post_json("/api/v1/bookings/initiate/", payload, user=customer_user)
    assert resp_a.status_code == 201
    booking_a = Booking.objects.get(id=resp_a.json()["booking_id"])

    # 2. Simulate expiration of Customer A's lock
    past_time = dj_timezone.now() - timedelta(minutes=1)
    booking_a.lock_expires_at = past_time
    booking_a.save(update_fields=["lock_expires_at"])

    # 3. Customer B initiates for same slot -> succeeds with fresh lock
    resp_b = api.post_json("/api/v1/bookings/initiate/", payload, user=other_customer_user)
    assert resp_b.status_code == 201
    booking_b = Booking.objects.get(id=resp_b.json()["booking_id"])
    assert booking_b.pk != booking_a.pk
    assert booking_b.customer == other_customer_user
    assert booking_b.status == BookingStatus.PENDING_PAYMENT

    # 4. Old booking transitioned to EXPIRED
    booking_a.refresh_from_db()
    assert booking_a.status == BookingStatus.EXPIRED


@pytest.mark.django_db
def test_initiate_booking_nonexistent_table_pin_returns_404(api, customer_user):
    """Requesting a non-existent table pin returns 404 NOT_FOUND."""
    target_date = (dj_timezone.now() + timedelta(days=2)).date()
    payload = {
        "table_pin_id": 999999,
        "slot_date": target_date.isoformat(),
        "slot_start_time": "10:00",
    }
    resp = api.post_json("/api/v1/bookings/initiate/", payload, user=customer_user)
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "NOT_FOUND"


@pytest.mark.django_db
def test_initiate_booking_rejects_debug_auth_when_debug_false(client, customer_user, table_pin, settings):
    """Security guard (T-009): Bearer token lookup via phone is strictly disabled when DEBUG=False."""
    settings.DEBUG = False

    target_date = (dj_timezone.now() + timedelta(days=2)).date()
    payload = {
        "table_pin_id": table_pin.id,
        "slot_date": target_date.isoformat(),
        "slot_start_time": "10:00",
    }
    resp = client.post(
        "/api/v1/bookings/initiate/",
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {customer_user.phone}",
    )
    assert resp.status_code == 401

