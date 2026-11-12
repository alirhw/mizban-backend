"""Concurrency and race condition tests for the booking lock service (TD-004 / Task T-012).

Acceptance criteria:
1. Two simultaneous booking initiate requests on the same table pin and slot:
   exactly one wins ('created'), and exactly one is rejected with SlotAlreadyReservedError ('conflict').
2. Re-acquisition of an expired lock succeeds cleanly (expired locks stop blocking).
3. A lock attempt on an already CONFIRMED booking is rejected with SlotAlreadyReservedError.
4. Slots inside the 24h lead-time window are rejected with LeadTimeViolationError.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.db import connection
from django.utils import timezone
import pytest

from apps.bookings.models import Booking, BookingStatus
from apps.bookings.services import create_booking_lock
from apps.panoramas.tests.factories import TablePinFactory as table_pin_factory
from apps.venues.tests.factories import UserFactory as user_factory
from core.exceptions import LeadTimeViolationError, SlotAlreadyReservedError

pytestmark = [
    pytest.mark.django_db(transaction=True),
]


def _attempt(kwargs):
    try:
        return ("created", create_booking_lock(**kwargs))
    except SlotAlreadyReservedError:
        return ("conflict", None)
    finally:
        connection.close()


def test_two_simultaneous_initiates_exactly_one_wins():
    """THE RACE (TD-004): Two concurrent customers initiate a booking on the same table and slot.

    Exactly one customer wins the lock ('created'); the other customer is rejected ('conflict').
    Zero double-bookings is success criterion #3 of the product definition.
    """
    pin = table_pin_factory()
    slot = pin.next_bookable_slot()
    assert slot is not None, "Failed to resolve next bookable slot for test table pin"

    kwargs = dict(table_pin=pin, slot_date=slot.date, slot_start_time=slot.start_time)
    attempts = [
        dict(user=user_factory(), **kwargs),
        dict(user=user_factory(), **kwargs),
    ]

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(result for result, _ in pool.map(_attempt, attempts))

    assert outcomes == ["conflict", "created"]

    # Verify only ONE booking row exists for this table pin and slot
    assert Booking.objects.filter(
        table_pin=pin,
        slot_date=slot.date,
        slot_start_time=slot.start_time,
        status=BookingStatus.PENDING_PAYMENT,
    ).count() == 1


def test_expired_lock_reacquisition():
    """An expired PENDING_PAYMENT lock (lock_expires_at in the past) does not block a new lock."""
    pin = table_pin_factory()
    slot = pin.next_bookable_slot()
    user_a = user_factory()
    user_b = user_factory()

    now = timezone.now()

    # 1. Customer A acquires lock at `now`
    booking_a = create_booking_lock(
        user=user_a,
        table_pin=pin,
        slot_date=slot.date,
        slot_start_time=slot.start_time,
        now=now,
    )
    assert booking_a.status == BookingStatus.PENDING_PAYMENT
    assert booking_a.lock_expires_at == now + timedelta(minutes=10)

    # 2. At now + 11 minutes (lock has elapsed unpaid), Customer B initiates booking
    elapsed_now = now + timedelta(minutes=11)
    booking_b = create_booking_lock(
        user=user_b,
        table_pin=pin,
        slot_date=slot.date,
        slot_start_time=slot.start_time,
        now=elapsed_now,
    )
    assert booking_b.pk != booking_a.pk
    assert booking_b.status == BookingStatus.PENDING_PAYMENT
    assert booking_b.customer == user_b

    # 3. Customer A's old booking was transitioned to EXPIRED
    booking_a.refresh_from_db()
    assert booking_a.status == BookingStatus.EXPIRED


def test_lock_attempt_on_already_confirmed_booking_rejected():
    """A lock attempt on an already CONFIRMED booking is rejected with SlotAlreadyReservedError."""
    pin = table_pin_factory()
    slot = pin.next_bookable_slot()
    user_a = user_factory()
    user_b = user_factory()

    # 1. Customer A holds and confirms a booking
    booking_a = create_booking_lock(
        user=user_a,
        table_pin=pin,
        slot_date=slot.date,
        slot_start_time=slot.start_time,
    )
    booking_a.transition_to(BookingStatus.CONFIRMED)

    # 2. Customer B attempts to lock the same table and slot -> rejected
    with pytest.raises(SlotAlreadyReservedError):
        create_booking_lock(
            user=user_b,
            table_pin=pin,
            slot_date=slot.date,
            slot_start_time=slot.start_time,
        )


def test_lock_attempt_inside_24h_lead_time_raises_error():
    """Attempting to lock a slot starting in less than 24h raises LeadTimeViolationError (BR-002)."""
    pin = table_pin_factory()
    user = user_factory()
    now = timezone.now()

    # Slot 12 hours from now
    target_dt = now + timedelta(hours=12)
    with pytest.raises(LeadTimeViolationError):
        create_booking_lock(
            user=user,
            table_pin=pin,
            slot_date=target_dt.date(),
            slot_start_time=target_dt.time(),
            now=now,
        )
