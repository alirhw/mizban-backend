"""Tests for owner manual BlockedSlot creation, listing, deletion, BR-001/FR-011, and concurrency (Task T-026)."""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.contrib.admin.sites import AdminSite
from django.db import connection
from django.test import Client, RequestFactory
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.bookings.models import Booking, BookingStatus
from apps.bookings.services import create_booking_lock
from apps.bookings.tests.factories import BookingFactory
from apps.panoramas.tests.factories import TablePinFactory
from apps.scheduling.admin import BlockedSlotAdmin
from apps.scheduling.models import BlockedSlot
from apps.scheduling.services import create_blocked_slot, get_venue_slots_for_date
from apps.venues.tests.factories import (
    OperatingHoursFactory,
    UserFactory,
    VenueFactory,
    activate_test_subscription,
)
from core.exceptions import SlotAlreadyReservedError
from core.testing import authenticate_client

pytestmark = pytest.mark.django_db


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def owner_user():
    return UserFactory(role=UserRole.VENUE_OWNER)


@pytest.fixture
def other_owner():
    return UserFactory(role=UserRole.VENUE_OWNER)


@pytest.fixture
def customer_user():
    return UserFactory(role=UserRole.CUSTOMER)


@pytest.fixture
def active_venue_and_pin(owner_user):
    venue = VenueFactory(owner=owner_user, is_approved=True)
    activate_test_subscription(venue)
    for wd in range(7):
        OperatingHoursFactory(venue=venue, weekday=wd, open_time="08:00", close_time="23:00")
    pin = TablePinFactory(venue=venue, is_active=True, reservation_fee_toman=50_000)
    return venue, pin


def _get_future_slot(venue, days_ahead: int = 3):
    now = timezone.now()
    target_date = (now + timedelta(days=days_ahead)).date()
    slots = get_venue_slots_for_date(venue, on_date=target_date, now=now)
    assert slots, "Expected generated slots for test venue"
    return slots[0], target_date


# ==============================================================================
# 1. Happy Path, Availability Representation, Booking Rejection, Reason Privacy
# ==============================================================================


def test_owner_blocks_slot_updates_availability_and_blocks_booking(
    client, owner_user, customer_user, active_venue_and_pin
):
    venue, pin = active_venue_and_pin
    slot, target_date = _get_future_slot(venue, days_ahead=3)
    secret_reason = "PRIVATE_VIP_WALKIN_SECRET_TEXT"

    authenticate_client(client, owner_user)
    resp = client.post(
        f"/api/v1/scheduling/pins/{pin.id}/blocked-slots/",
        data=json.dumps({"start_at": slot.start.isoformat(), "reason": secret_reason}),
        content_type="application/json",
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["pin_id"] == pin.id
    assert data["reason"] == secret_reason
    assert data["jalali_start_at"]

    block = BlockedSlot.objects.get(pk=data["id"])
    assert block.start_at == slot.start
    assert block.end_at == slot.start + timedelta(minutes=90)
    assert block.created_by_id == owner_user.id

    # Public availability omits blocked slot identically to a booked slot, and never leaks reason
    avail_resp = client.get(
        f"/api/v1/scheduling/venues/{venue.id}/slots",
        {"date": target_date.isoformat(), "table_pin_id": pin.id},
    )
    assert avail_resp.status_code == 200
    assert secret_reason not in avail_resp.content.decode("utf-8")
    returned_starts = {item["start"] for item in avail_resp.json()}
    assert slot.start.isoformat().replace("+00:00", "Z") not in returned_starts
    assert not any(
        item["start"].startswith(slot.start.strftime("%Y-%m-%dT%H:%M"))
        for item in avail_resp.json()
    )

    # Customer booking initiation fails with exact same SLOT_ALREADY_RESERVED (409) and no reason leak
    authenticate_client(client, customer_user)
    book_resp = client.post(
        "/api/v1/bookings/initiate/",
        data=json.dumps(
            {
                "table_pin_id": pin.id,
                "slot_date": target_date.isoformat(),
                "slot_start_time": slot.start_time.strftime("%H:%M"),
            }
        ),
        content_type="application/json",
    )
    assert book_resp.status_code == 409
    assert book_resp.json()["error_code"] == "SLOT_ALREADY_RESERVED"
    assert secret_reason not in book_resp.content.decode("utf-8")


# ==============================================================================
# 2. Conflict Rules: CONFIRMED / PENDING_PAYMENT Bookings & Duplicate Blocks
# ==============================================================================


def test_block_over_confirmed_booking_rejected_409(client, owner_user, customer_user, active_venue_and_pin):
    venue, pin = active_venue_and_pin
    slot, target_date = _get_future_slot(venue, days_ahead=3)

    booking = BookingFactory(
        venue=venue,
        table_pin=pin,
        customer=customer_user,
        status=BookingStatus.CONFIRMED,
        start_at=slot.start,
        end_at=slot.end,
        slot_date=target_date,
        slot_start_time=slot.start_time,
    )

    authenticate_client(client, owner_user)
    resp = client.post(
        f"/api/v1/scheduling/pins/{pin.id}/blocked-slots/",
        data=json.dumps({"start_at": slot.start.isoformat(), "reason": "Try override"}),
        content_type="application/json",
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "SLOT_ALREADY_RESERVED"
    booking.refresh_from_db()
    assert booking.status == BookingStatus.CONFIRMED
    assert BlockedSlot.objects.filter(table_pin=pin).count() == 0


def test_block_over_active_pending_payment_booking_rejected_409(
    client, owner_user, customer_user, active_venue_and_pin
):
    venue, pin = active_venue_and_pin
    slot, target_date = _get_future_slot(venue, days_ahead=3)

    BookingFactory(
        venue=venue,
        table_pin=pin,
        customer=customer_user,
        status=BookingStatus.PENDING_PAYMENT,
        start_at=slot.start,
        end_at=slot.end,
        slot_date=target_date,
        slot_start_time=slot.start_time,
        lock_expires_at=timezone.now() + timedelta(minutes=8),
    )

    authenticate_client(client, owner_user)
    resp = client.post(
        f"/api/v1/scheduling/pins/{pin.id}/blocked-slots/",
        data=json.dumps({"start_at": slot.start.isoformat()}),
        content_type="application/json",
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "SLOT_ALREADY_RESERVED"


def test_duplicate_block_rejected_409(client, owner_user, active_venue_and_pin):
    venue, pin = active_venue_and_pin
    slot, _ = _get_future_slot(venue, days_ahead=3)

    authenticate_client(client, owner_user)
    r1 = client.post(
        f"/api/v1/scheduling/pins/{pin.id}/blocked-slots/",
        data=json.dumps({"start_at": slot.start.isoformat()}),
        content_type="application/json",
    )
    assert r1.status_code == 201

    r2 = client.post(
        f"/api/v1/scheduling/pins/{pin.id}/blocked-slots/",
        data=json.dumps({"start_at": slot.start.isoformat()}),
        content_type="application/json",
    )
    assert r2.status_code == 409
    assert r2.json()["error_code"] == "SLOT_ALREADY_RESERVED"


# ==============================================================================
# 3. Alignment (422), Past Slot (400), and <24h Owner Blocking Allowed
# ==============================================================================


def test_misaligned_start_at_rejected_422(client, owner_user, active_venue_and_pin):
    venue, pin = active_venue_and_pin
    slot, _ = _get_future_slot(venue, days_ahead=3)
    misaligned = slot.start + timedelta(minutes=17)

    authenticate_client(client, owner_user)
    resp = client.post(
        f"/api/v1/scheduling/pins/{pin.id}/blocked-slots/",
        data=json.dumps({"start_at": misaligned.isoformat()}),
        content_type="application/json",
    )
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "VALIDATION_ERROR"


def test_past_slot_rejected_400_invalid_slot(client, owner_user, active_venue_and_pin):
    venue, pin = active_venue_and_pin
    past_date = (timezone.now() - timedelta(days=2)).date()
    past_slot = get_venue_slots_for_date(venue, on_date=past_date, now=timezone.now())[0]

    authenticate_client(client, owner_user)
    resp = client.post(
        f"/api/v1/scheduling/pins/{pin.id}/blocked-slots/",
        data=json.dumps({"start_at": past_slot.start.isoformat()}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == "INVALID_SLOT"


def test_owner_can_block_slot_less_than_24h_ahead(client, owner_user, active_venue_and_pin):
    venue, pin = active_venue_and_pin
    now = timezone.now()
    # Find a slot that is > now but < 24h away (e.g. tomorrow or today)
    near_slot = None
    for offset in (0, 1):
        d = (now + timedelta(days=offset)).date()
        for s in get_venue_slots_for_date(venue, on_date=d, now=now):
            if now < s.start < now + timedelta(hours=24):
                near_slot = s
                break
        if near_slot:
            break
    assert near_slot is not None

    authenticate_client(client, owner_user)
    resp = client.post(
        f"/api/v1/scheduling/pins/{pin.id}/blocked-slots/",
        data=json.dumps({"start_at": near_slot.start.isoformat(), "reason": "Same-day maintenance"}),
        content_type="application/json",
    )
    assert resp.status_code == 201


# ==============================================================================
# 4. List Upcoming, Unblock (Hard Delete), and Past Block Cleanup
# ==============================================================================


def test_list_returns_only_upcoming_ordered_and_unblock_makes_slot_bookable(
    client, owner_user, customer_user, active_venue_and_pin
):
    venue, pin = active_venue_and_pin
    now = timezone.now()

    # Create a past block directly in DB
    past_start = now - timedelta(hours=5)
    past_block = BlockedSlot.objects.create(
        table_pin=pin,
        start_at=past_start,
        end_at=past_start + timedelta(minutes=90),
        reason="Past",
        created_by=owner_user,
    )

    # Create two upcoming blocks in reverse order
    s_later, _ = _get_future_slot(venue, days_ahead=4)
    s_sooner, target_date = _get_future_slot(venue, days_ahead=2)

    authenticate_client(client, owner_user)
    r_later = client.post(
        f"/api/v1/scheduling/pins/{pin.id}/blocked-slots/",
        data=json.dumps({"start_at": s_later.start.isoformat(), "reason": "Later"}),
        content_type="application/json",
    )
    r_sooner = client.post(
        f"/api/v1/scheduling/pins/{pin.id}/blocked-slots/",
        data=json.dumps({"start_at": s_sooner.start.isoformat(), "reason": "Sooner"}),
        content_type="application/json",
    )
    assert r_later.status_code == 201 and r_sooner.status_code == 201

    list_resp = client.get(f"/api/v1/scheduling/pins/{pin.id}/blocked-slots/")
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert [item["id"] for item in items] == [r_sooner.json()["id"], r_later.json()["id"]]

    # Unblock sooner slot -> 204, slot becomes bookable again
    del_resp = client.delete(f"/api/v1/scheduling/blocked-slots/{r_sooner.json()['id']}/")
    assert del_resp.status_code == 204
    assert not BlockedSlot.objects.filter(pk=r_sooner.json()["id"]).exists()

    # Deleting a past block also succeeds (cleanup allowed)
    del_past = client.delete(f"/api/v1/scheduling/blocked-slots/{past_block.id}/")
    assert del_past.status_code == 204

    authenticate_client(client, customer_user)
    book_resp = client.post(
        "/api/v1/bookings/initiate/",
        data=json.dumps(
            {
                "table_pin_id": pin.id,
                "slot_date": target_date.isoformat(),
                "slot_start_time": s_sooner.start_time.strftime("%H:%M"),
            }
        ),
        content_type="application/json",
    )
    assert book_resp.status_code == 201


# ==============================================================================
# 5. Ownership & Auth (401 / 403 / 404) & Read-Only Admin
# ==============================================================================


def test_blocked_slot_permissions_and_readonly_admin(
    client, owner_user, other_owner, customer_user, active_venue_and_pin
):
    venue, pin = active_venue_and_pin
    slot, _ = _get_future_slot(venue, days_ahead=3)

    # Unauthenticated -> 401
    assert client.post(f"/api/v1/scheduling/pins/{pin.id}/blocked-slots/").status_code == 401
    assert client.get(f"/api/v1/scheduling/pins/{pin.id}/blocked-slots/").status_code == 401
    assert client.delete("/api/v1/scheduling/blocked-slots/1/").status_code == 401

    # Create block as real owner
    authenticate_client(client, owner_user)
    created = client.post(
        f"/api/v1/scheduling/pins/{pin.id}/blocked-slots/",
        data=json.dumps({"start_at": slot.start.isoformat()}),
        content_type="application/json",
    )
    assert created.status_code == 201
    block_id = created.json()["id"]

    # Customer -> 403 on create, list, delete
    authenticate_client(client, customer_user)
    assert (
        client.post(
            f"/api/v1/scheduling/pins/{pin.id}/blocked-slots/",
            data=json.dumps({"start_at": slot.start.isoformat()}),
            content_type="application/json",
        ).status_code
        == 403
    )
    assert client.get(f"/api/v1/scheduling/pins/{pin.id}/blocked-slots/").status_code == 403
    assert client.delete(f"/api/v1/scheduling/blocked-slots/{block_id}/").status_code == 403

    # Foreign owner -> 403 on create, list, delete
    authenticate_client(client, other_owner)
    assert (
        client.post(
            f"/api/v1/scheduling/pins/{pin.id}/blocked-slots/",
            data=json.dumps({"start_at": slot.start.isoformat()}),
            content_type="application/json",
        ).status_code
        == 403
    )
    assert client.get(f"/api/v1/scheduling/pins/{pin.id}/blocked-slots/").status_code == 403
    assert client.delete(f"/api/v1/scheduling/blocked-slots/{block_id}/").status_code == 403

    # Unknown pin / block -> 404
    authenticate_client(client, owner_user)
    assert client.get("/api/v1/scheduling/pins/999999/blocked-slots/").status_code == 404
    assert client.delete("/api/v1/scheduling/blocked-slots/999999/").status_code == 404

    # Read-only Django Admin
    admin_inst = BlockedSlotAdmin(BlockedSlot, AdminSite())
    rf = RequestFactory()
    req = rf.get("/admin/scheduling/blockedslot/")
    req.user = owner_user
    assert admin_inst.has_add_permission(req) is False
    assert admin_inst.has_change_permission(req) is False
    assert admin_inst.has_delete_permission(req) is False


# ==============================================================================
# 6. PostgreSQL Concurrency Race: Block Creation vs Booking Initiation
# ==============================================================================


@pytest.mark.django_db(transaction=True)
def test_concurrency_race_block_vs_booking_serialises_on_pin_lock():
    """Concurrent create_blocked_slot and create_booking_lock on the same pin/slot:
    exactly one succeeds and the other fails cleanly with SlotAlreadyReservedError.
    """
    owner = UserFactory(role=UserRole.VENUE_OWNER)
    customer = UserFactory(role=UserRole.CUSTOMER)
    venue = VenueFactory(owner=owner, is_approved=True)
    activate_test_subscription(venue)
    for wd in range(7):
        OperatingHoursFactory(venue=venue, weekday=wd, open_time="08:00", close_time="23:00")
    pin = TablePinFactory(venue=venue, is_active=True, reservation_fee_toman=50_000)

    slot, target_date = _get_future_slot(venue, days_ahead=3)
    barrier = threading.Barrier(2)

    def attempt_block():
        barrier.wait()
        try:
            create_blocked_slot(user=owner, pin_id=pin.id, start_at=slot.start, reason="Race block")
            return "block_won"
        except SlotAlreadyReservedError:
            return "block_lost"
        finally:
            connection.close()

    def attempt_book():
        barrier.wait()
        try:
            create_booking_lock(
                user=customer,
                table_pin=pin.id,
                slot_date=target_date,
                slot_start_time=slot.start_time,
            )
            return "book_won"
        except SlotAlreadyReservedError:
            return "book_lost"
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_block = executor.submit(attempt_block)
        f_book = executor.submit(attempt_book)
        outcomes = {f_block.result(), f_book.result()}

    assert outcomes in ({"block_won", "book_lost"}, {"book_won", "block_lost"})
    blocks = BlockedSlot.objects.filter(table_pin=pin, start_at=slot.start).count()
    bookings = Booking.objects.filter(table_pin=pin, start_at=slot.start).count()
    assert blocks + bookings == 1
