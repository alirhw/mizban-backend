"""Tests for Booking model, constraints, lifecycle, and indexes (Task T-011).

Acceptance criteria:
1. Double-booking the same table+slot is rejected at the DB level (IntegrityError).
2. Cancelled bookings do not block re-booking of the same table+slot.
3. Expired bookings do not block re-booking.
4. Status transitions follow the documented state machine lifecycle.
5. Jalali presentation helpers format UTC instants into Asia/Tehran Jalali strings.
6. DB check constraints enforce end_at > start_at and non-negative amounts.
7. Slot availability intersection interface (is_table_slot_occupied) correctly reflects active holds.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from django.db import IntegrityError, transaction

from apps.accounts.models import UserRole
from apps.bookings.models import Booking, BookingAddon, BookingStatus
from apps.bookings.services import is_table_slot_occupied
from apps.panoramas.tests.factories import TablePinFactory
from apps.venues.tests.factories import DesignAddonFactory, UserFactory, VenueFactory
from core.exceptions import InvalidStatusTransitionError

pytestmark = pytest.mark.django_db


@pytest.fixture
def venue():
    owner = UserFactory(role=UserRole.VENUE_OWNER)
    return VenueFactory(owner=owner)


@pytest.fixture
def table_pin(venue):
    return TablePinFactory(venue=venue, table_number="T1")


@pytest.fixture
def customer():
    return UserFactory(role=UserRole.CUSTOMER)


def test_booking_creation_and_auto_sync(venue, table_pin, customer):
    """Booking auto-derives local slot_date, slot_start_time, end_at and venue."""
    start_utc = datetime(2026, 1, 10, 15, 30, tzinfo=UTC)  # 19:00 Tehran
    booking = Booking.objects.create(
        customer=customer,
        table_pin=table_pin,
        start_at=start_utc,
        status=BookingStatus.INITIATED,
    )

    assert booking.venue == venue
    assert booking.end_at == start_utc + timedelta(minutes=90)
    assert booking.slot_date is not None
    assert booking.slot_start_time is not None

    # Jalali presentation helpers
    assert booking.jalali_date != ""
    assert booking.jalali_start_datetime != ""
    assert booking.jalali_end_datetime != ""
    assert "/" in booking.jalali_date


def test_double_booking_rejected_at_db_level(table_pin, customer):
    """Two active bookings on the same table_pin and slot raise IntegrityError at DB level."""
    slot_start = datetime(2026, 1, 10, 15, 30, tzinfo=UTC)

    # 1. Create first CONFIRMED booking
    Booking.objects.create(
        table_pin=table_pin,
        customer=customer,
        start_at=slot_start,
        status=BookingStatus.CONFIRMED,
    )

    # 2. Attempt second CONFIRMED booking on same table and slot -> DB unique violation
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Booking.objects.create(
                table_pin=table_pin,
                customer=customer,
                start_at=slot_start,
                status=BookingStatus.CONFIRMED,
            )

    # 3. Attempt PENDING_PAYMENT booking on same table and slot -> DB unique violation
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Booking.objects.create(
                table_pin=table_pin,
                customer=customer,
                start_at=slot_start,
                status=BookingStatus.PENDING_PAYMENT,
            )


def test_cancelled_booking_does_not_block_rebooking(table_pin, customer):
    """Cancelled bookings do not block another customer from booking the slot."""
    slot_start = datetime(2026, 1, 10, 15, 30, tzinfo=UTC)

    # 1. Create booking and cancel it
    b1 = Booking.objects.create(
        table_pin=table_pin,
        customer=customer,
        start_at=slot_start,
        status=BookingStatus.INITIATED,
    )
    b1.transition_to(BookingStatus.CANCELLED)
    assert b1.status == BookingStatus.CANCELLED

    # 2. Another customer books the exact same slot -> succeeds
    customer2 = UserFactory(role=UserRole.CUSTOMER)
    b2 = Booking.objects.create(
        table_pin=table_pin,
        customer=customer2,
        start_at=slot_start,
        status=BookingStatus.CONFIRMED,
    )
    assert b2.pk is not None
    assert b2.status == BookingStatus.CONFIRMED


def test_expired_booking_does_not_block_rebooking(table_pin, customer):
    """Expired bookings do not block new bookings on the slot."""
    slot_start = datetime(2026, 1, 10, 15, 30, tzinfo=UTC)

    # 1. Create booking and let it expire
    b1 = Booking.objects.create(
        table_pin=table_pin,
        customer=customer,
        start_at=slot_start,
        status=BookingStatus.INITIATED,
    )
    b1.transition_to(BookingStatus.EXPIRED)

    # 2. New booking can be created
    customer2 = UserFactory(role=UserRole.CUSTOMER)
    b2 = Booking.objects.create(
        table_pin=table_pin,
        customer=customer2,
        start_at=slot_start,
        status=BookingStatus.CONFIRMED,
    )
    assert b2.pk is not None


def test_status_transitions_follow_lifecycle(table_pin, customer):
    """Booking state machine enforces valid transitions and rejects invalid ones."""
    slot_start = datetime(2026, 1, 10, 15, 30, tzinfo=UTC)
    b = Booking.objects.create(
        table_pin=table_pin,
        customer=customer,
        start_at=slot_start,
        status=BookingStatus.INITIATED,
    )

    # Valid: INITIATED -> PENDING_PAYMENT
    b.transition_to(BookingStatus.PENDING_PAYMENT)
    assert b.status == BookingStatus.PENDING_PAYMENT

    # Valid: PENDING_PAYMENT -> CONFIRMED
    b.transition_to(BookingStatus.CONFIRMED)
    assert b.status == BookingStatus.CONFIRMED

    # Valid: CONFIRMED -> COMPLETED
    b.transition_to(BookingStatus.COMPLETED)
    assert b.status == BookingStatus.COMPLETED

    # Invalid: COMPLETED is terminal -> cannot transition to CONFIRMED
    with pytest.raises(InvalidStatusTransitionError):
        b.transition_to(BookingStatus.CONFIRMED)


def test_cancellation_from_pending_payment(table_pin, customer):
    """Pending payment bookings can transition to CANCELLED upon customer abort."""
    b = Booking.objects.create(
        table_pin=table_pin,
        customer=customer,
        start_at=datetime(2026, 1, 10, 15, 30, tzinfo=UTC),
        status=BookingStatus.PENDING_PAYMENT,
    )
    b.transition_to(BookingStatus.CANCELLED)
    assert b.status == BookingStatus.CANCELLED


def test_invalid_transition_from_initiated_to_completed_rejected(table_pin, customer):
    """INITIATED cannot jump directly to COMPLETED."""
    b = Booking.objects.create(
        table_pin=table_pin,
        customer=customer,
        start_at=datetime(2026, 1, 10, 15, 30, tzinfo=UTC),
        status=BookingStatus.INITIATED,
    )
    with pytest.raises(InvalidStatusTransitionError):
        b.transition_to(BookingStatus.COMPLETED)


def test_booking_end_after_start_check_constraint(table_pin, customer):
    """end_at must be strictly greater than start_at."""
    start_utc = datetime(2026, 1, 10, 15, 30, tzinfo=UTC)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Booking.objects.create(
                table_pin=table_pin,
                customer=customer,
                start_at=start_utc,
                end_at=start_utc,  # Violates end_at > start_at
                status=BookingStatus.INITIATED,
            )


def test_booking_amounts_non_negative_check_constraint(table_pin, customer):
    """Amounts cannot be negative."""
    start_utc = datetime(2026, 1, 10, 15, 30, tzinfo=UTC)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Booking.objects.create(
                table_pin=table_pin,
                customer=customer,
                start_at=start_utc,
                amount_online_toman=-1000,
                status=BookingStatus.INITIATED,
            )


def test_is_table_slot_occupied_interface(table_pin, customer):
    """Slot availability intersection interface correctly identifies occupied slots."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    slot_start = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)

    # 1. Unbooked slot is NOT occupied
    assert not is_table_slot_occupied(table_pin, start_at=slot_start, now=now)

    # 2. Active PENDING_PAYMENT with lock_expires_at in the future IS occupied
    booking = Booking.objects.create(
        table_pin=table_pin,
        customer=customer,
        start_at=slot_start,
        status=BookingStatus.PENDING_PAYMENT,
        locked_at=now,
        lock_expires_at=now + timedelta(minutes=10),
    )
    assert is_table_slot_occupied(table_pin, start_at=slot_start, now=now)

    # 3. PENDING_PAYMENT with lock_expires_at in the past is NOT occupied (lock elapsed)
    assert not is_table_slot_occupied(
        table_pin,
        start_at=slot_start,
        now=now + timedelta(minutes=11),
    )

    # 4. CONFIRMED booking IS occupied
    booking.status = BookingStatus.CONFIRMED
    booking.save()
    assert is_table_slot_occupied(table_pin, start_at=slot_start, now=now)

    # 5. CANCELLED booking is NOT occupied
    booking.status = BookingStatus.CANCELLED
    booking.save()
    assert not is_table_slot_occupied(table_pin, start_at=slot_start, now=now)


def test_booking_addon_snapshot(table_pin, customer, venue):
    """BookingAddon takes a price snapshot of the design addon."""
    addon = DesignAddonFactory(venue=venue, fee=200_000)
    booking = Booking.objects.create(
        table_pin=table_pin,
        customer=customer,
        start_at=datetime(2026, 1, 10, 15, 30, tzinfo=UTC),
        status=BookingStatus.CONFIRMED,
    )
    booking_addon = BookingAddon.objects.create(
        booking=booking,
        design_addon=addon,
        price_snapshot_toman=addon.fee,
    )
    assert booking_addon.price_snapshot_toman == 200_000
    assert booking.addons.count() == 1
