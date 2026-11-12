"""Booking service layer - atomic lock creation and cancellation.

Task T-012:
- create_booking_lock inside transaction.atomic() with TablePin.objects.select_for_update()
- On success creates Booking(status=PENDING_PAYMENT, locked_at=now, lock_expires_at=now + 10m)
- On contention the second concurrent initiate fails cleanly with SlotAlreadyReservedError (HTTP 409)
- Expired locks (lock_expires_at in the past) do not block a new lock
- Respects slot-generation rules (BR-001/BR-002) and availability interface
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, Any, Iterable, Optional, Union

from django.db import models, transaction
from django.utils import timezone as dj_timezone

from apps.bookings.models import Booking, BookingAddon, BookingStatus
from core.exceptions import LeadTimeViolationError, SlotAlreadyReservedError
from core.jalali import TEHRAN

if TYPE_CHECKING:
    from apps.panoramas.models import TablePin

LOCK_TTL = timedelta(minutes=10)
SLOT_DURATION = timedelta(minutes=90)
LEAD_TIME_THRESHOLD = timedelta(hours=24)


def is_table_slot_occupied(
    table_pin: Union[TablePin, int],
    start_at: Optional[datetime] = None,
    slot_date: Optional[date] = None,
    slot_start_time: Optional[time] = None,
    now: Optional[datetime] = None,
) -> bool:
    """Check if a table pin is occupied by an active booking or lock.

    INTERFACE SPECIFICATION FOR TASK T-012 (Lock Service) & T-013 (Initiate Booking):
    A slot is considered occupied if any Booking exists with:
      - status == CONFIRMED, OR
      - status == PENDING_PAYMENT with lock_expires_at > now (active hold).
    Cancelled, expired, or completed bookings do not occupy the slot.
    ARCH-004: Computed at query-time from DB; never cached.
    """
    pin_id = table_pin if isinstance(table_pin, int) else table_pin.pk
    if now is None:
        now = dj_timezone.now()

    qs = Booking.objects.filter(table_pin_id=pin_id)
    if start_at is not None:
        qs = qs.filter(start_at=start_at)
    elif slot_date is not None and slot_start_time is not None:
        qs = qs.filter(slot_date=slot_date, slot_start_time=slot_start_time)
    else:
        raise ValueError("Must provide either start_at or both slot_date and slot_start_time.")

    return qs.filter(
        models.Q(status=BookingStatus.CONFIRMED)
        | models.Q(status=BookingStatus.PENDING_PAYMENT, lock_expires_at__gt=now)
    ).exists()


def filter_available_slots_for_table(
    table_pin: Union[TablePin, int],
    slots: list,
    now: Optional[datetime] = None,
) -> list:
    """Filter generated calendar slots against active bookings and locks."""
    if now is None:
        now = dj_timezone.now()

    available = []
    for slot in slots:
        if not is_table_slot_occupied(table_pin=table_pin, start_at=slot.start, now=now):
            available.append(slot)
    return available


def create_booking_lock(
    *,
    user: Any,
    table_pin: Union[TablePin, int],
    slot_date: date,
    slot_start_time: time,
    addon_ids: Iterable[int] = (),
    now: Optional[datetime] = None,
) -> Booking:
    """Acquire a 10-minute temporary reservation lock for a table pin and slot (TD-004).

    Guarantees:
    - Atomicity: Runs inside transaction.atomic() with select_for_update() on the TablePin row.
    - Concurrency safety: Zero double-bookings under concurrent attempts; exactly one wins.
    - BR-002: Rejects slots starting less than 24h from now with LeadTimeViolationError.
    - REQ-LOCK-005: Stale expired locks (lock_expires_at <= now) are marked EXPIRED and do not block.
    - Overlapping active locks (CONFIRMED or unexpired PENDING_PAYMENT) raise SlotAlreadyReservedError (409).
    """
    from apps.panoramas.models import TablePin
    from apps.venues.models import DesignAddon

    if now is None:
        now = dj_timezone.now()
    elif dj_timezone.is_naive(now):
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    # 1. Determine slot start/end in aware UTC (ARCH-006)
    local_start = datetime.combine(slot_date, slot_start_time, tzinfo=TEHRAN)
    start_at_utc = local_start.astimezone(timezone.utc)
    end_at_utc = start_at_utc + SLOT_DURATION

    # 2. BR-002: Lead time validation (>= 24 hours from now)
    if start_at_utc - now < LEAD_TIME_THRESHOLD:
        raise LeadTimeViolationError(
            "Bookings must be initiated at least 24 hours before the slot start time."
        )

    pin_id = table_pin if isinstance(table_pin, int) else table_pin.pk

    # 3. Concurrency-critical lock execution
    with transaction.atomic():
        # Lock the TablePin row to serialize concurrent booking attempts on the same table
        pin = TablePin.objects.select_for_update().get(pk=pin_id)

        # REQ-LOCK-005: Expire any stale locks that have elapsed unpaid
        # This frees the DB partial unique constraint and maintains correctness without celery
        Booking.objects.filter(
            table_pin_id=pin.pk,
            slot_date=slot_date,
            slot_start_time=slot_start_time,
            status=BookingStatus.PENDING_PAYMENT,
            lock_expires_at__lte=now,
        ).update(status=BookingStatus.EXPIRED, updated_at=now)

        # REQ-LOCK-003: Check if an active confirmed booking or active lock exists
        if Booking.objects.active_locks_for_slot(pin.pk, slot_date, slot_start_time, now=now).exists():
            raise SlotAlreadyReservedError(
                "This table is currently reserved or locked by another customer for this slot."
            )

        # Determine table reservation fee (default 50,000 Toman platform share)
        table_fee = getattr(pin, "reservation_fee_toman", 50_000) or 50_000

        # Create Booking row in PENDING_PAYMENT with 10-minute TTL
        booking = Booking.objects.create(
            venue=pin.venue,
            table_pin=pin,
            customer=user,
            status=BookingStatus.PENDING_PAYMENT,
            start_at=start_at_utc,
            end_at=end_at_utc,
            slot_date=slot_date,
            slot_start_time=slot_start_time,
            locked_at=now,
            lock_expires_at=now + LOCK_TTL,
            amount_online_toman=table_fee,
            amount_in_person_toman=0,
        )

        # REQ-LOCK-006: Attach selected design addons with price snapshot (BR-003)
        if addon_ids:
            addons = DesignAddon.objects.filter(id__in=addon_ids, venue=pin.venue, is_active=True)
            total_addon_fee = 0
            booking_addons = []
            for addon in addons:
                booking_addons.append(
                    BookingAddon(
                        booking=booking,
                        design_addon=addon,
                        price_snapshot_toman=addon.fee,
                    )
                )
                total_addon_fee += addon.fee

            if booking_addons:
                BookingAddon.objects.bulk_create(booking_addons)
                booking.amount_in_person_toman = total_addon_fee
                booking.save(update_fields=["amount_in_person_toman", "updated_at"])

        return booking


def initiate_booking(
    *,
    user: Any,
    table_pin_id: int,
    slot_date: Union[date, str],
    slot_start_time: Union[time, str],
    venue_id: Optional[int] = None,
    addon_ids: Iterable[int] = (),
    now: Optional[datetime] = None,
) -> Booking:
    """Initiate a booking lock from an API request (Task T-013).

    Validates:
    - Role: caller must be CUSTOMER (raises PermissionDenied -> 403).
    - TablePin: exists and is_active (raises Http404 or TableNotBookableError -> 400).
    - Venue: if venue_id provided, must match pin.venue_id (VenueMismatchError -> 400).
    - BR-005: venue must be approved and have active subscription (VenueNotBookableError -> 400).
    - Operating hours: slot must be within venue operating hours if configured (InvalidSlotError -> 400).
    - Date / time parsing: converts Gregorian/Jalali strings to canonical date and time.
    - Concurrency & lead time: delegates to atomic create_booking_lock (TD-004).
    """
    from django.core.exceptions import PermissionDenied
    from django.http import Http404

    from apps.accounts.models import UserRole
    from apps.bookings.schemas import resolve_time
    from apps.panoramas.models import TablePin
    from apps.scheduling.services import get_venue_slots_for_date
    from apps.venues.models import SubscriptionStatus
    from core.exceptions import (
        InvalidSlotError,
        TableNotBookableError,
        VenueMismatchError,
        VenueNotBookableError,
    )
    from core.jalali import resolve_date

    if now is None:
        now = dj_timezone.now()
    elif dj_timezone.is_naive(now):
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    # 1. Role enforcement: CUSTOMER only
    if not user or getattr(user, "role", None) != UserRole.CUSTOMER:
        raise PermissionDenied("Only customers can initiate bookings.")

    # 2. Date and time resolution
    resolved_date = resolve_date(slot_date)
    resolved_time = resolve_time(slot_start_time)

    # 3. TablePin and Venue resolution
    pin = TablePin.objects.select_related("venue").filter(pk=table_pin_id).first()
    if not pin:
        raise Http404("Table pin not found.")

    if not pin.is_active:
        raise TableNotBookableError("This table is currently not available for reservations.")

    if venue_id is not None and pin.venue_id != venue_id:
        raise VenueMismatchError("The specified table does not belong to this venue.")

    venue = pin.venue
    # BR-005: Admin-approved and active subscription
    if not venue.is_approved or venue.subscription_status != SubscriptionStatus.ACTIVE:
        raise VenueNotBookableError("This venue is not currently accepting reservations.")

    # 4. Validate that requested slot is in operating hours
    if venue.operating_hours.exists():
        slots = get_venue_slots_for_date(venue, on_date=resolved_date, now=now)
        if not any(s.start_time == resolved_time for s in slots):
            raise InvalidSlotError("The requested slot is outside the venue's operating hours.")

    # 5. Acquire atomic booking lock (TD-004)
    return create_booking_lock(
        user=user,
        table_pin=pin,
        slot_date=resolved_date,
        slot_start_time=resolved_time,
        addon_ids=addon_ids,
        now=now,
    )

