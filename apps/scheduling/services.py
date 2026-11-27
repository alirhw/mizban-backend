"""Slot-generation engine (BR-001 / BR-002) - implemented in task T-010.

Contract for generate_slots:
    generate_slots(*, open_time, close_time, on_date, now) -> list[Slot]

- Deterministic: the same inputs always produce the same slots.
- Each slot lasts exactly 90 minutes; consecutive slot starts are exactly
  120 minutes apart (90-minute slot + 30-minute cleaning buffer, BR-001),
  and a slot is only emitted when it fully fits inside the working range
  (ranges crossing midnight are supported).
- Each returned Slot exposes .start / .end (aware UTC datetimes) and
  .is_bookable, which is False when the slot starts less than 24 hours
  after `now` (BR-002) - such slots exist on the calendar but cannot be
  booked.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models, transaction
from django.http import Http404
from django.utils import timezone as dj_timezone

from core.exceptions import InvalidSlotError, SlotAlreadyReservedError
from core.jalali import TEHRAN, parse_jalali_date

if TYPE_CHECKING:
    from apps.venues.models import Venue

SLOT_DURATION = timedelta(minutes=90)
BUFFER_DURATION = timedelta(minutes=30)
CYCLE_DURATION = SLOT_DURATION + BUFFER_DURATION  # 120 minutes
LEAD_TIME_THRESHOLD = timedelta(hours=24)


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime
    is_bookable: bool
    disabled_reason: str | None = None

    @property
    def date(self) -> date:
        return self.start.astimezone(TEHRAN).date()

    @property
    def start_time(self) -> time:
        return self.start.astimezone(TEHRAN).time()


def generate_slots(
    open_time: time,
    close_time: time,
    on_date: date | datetime,
    now: datetime | None = None,
    tz: ZoneInfo = TEHRAN,
) -> list[Slot]:
    """Generate deterministic 90-minute slots with 30-minute buffers.

    Args:
        open_time: Local venue opening time (e.g. 09:00).
        close_time: Local venue closing time (e.g. 13:00 or 02:00 next day).
        on_date: Calendar date for the operating shift.
        now: Current aware UTC datetime used for lead-time calculation.
        tz: Timezone for interpreting venue wall-clock times (default: Asia/Tehran).

    Returns:
        List of Slot objects with start/end in aware UTC and is_bookable status.
    """
    if isinstance(on_date, datetime):
        calendar_date = on_date.date()
    else:
        calendar_date = on_date

    if now is None:
        now = dj_timezone.now()
    elif dj_timezone.is_naive(now):
        now = now.replace(tzinfo=UTC)
    else:
        now = now.astimezone(UTC)

    # 1. Build operating window in local timezone
    open_local = datetime.combine(calendar_date, open_time, tzinfo=tz)
    if close_time <= open_time:
        # Crosses midnight into next calendar day
        close_local = datetime.combine(calendar_date + timedelta(days=1), close_time, tzinfo=tz)
    else:
        close_local = datetime.combine(calendar_date, close_time, tzinfo=tz)

    # 2. Convert to aware UTC (ARCH-006)
    open_utc = open_local.astimezone(UTC)
    close_utc = close_local.astimezone(UTC)

    # 3. Deterministic slot iteration (BR-001 / BR-002)
    slots: list[Slot] = []
    current_start = open_utc

    while current_start + SLOT_DURATION <= close_utc:
        current_end = current_start + SLOT_DURATION
        # BR-002: >= 24h lead time rule
        is_bookable = (current_start - now) >= LEAD_TIME_THRESHOLD
        reason = None if is_bookable else "LEAD_TIME_VIOLATION"

        slots.append(
            Slot(
                start=current_start,
                end=current_end,
                is_bookable=is_bookable,
                disabled_reason=reason,
            )
        )
        current_start += CYCLE_DURATION

    return slots


def resolve_date(date_input: date | datetime | str) -> date:
    """Resolve a date input which may be date, datetime, ISO string, or Jalali string."""
    if isinstance(date_input, datetime):
        return date_input.date()
    if isinstance(date_input, date):
        return date_input

    # String input: try Jalali format first if slash or 13xx/14xx, else ISO
    date_str = str(date_input).strip()
    if "/" in date_str or date_str.startswith("13") or date_str.startswith("14"):
        return parse_jalali_date(date_str.replace("-", "/"))

    # Standard ISO format YYYY-MM-DD
    return date.fromisoformat(date_str)


def get_venue_slots_for_date(
    venue: Venue | int,
    on_date: date | datetime | str,
    now: datetime | None = None,
    table_pin: Any | None = None,
) -> list[Slot]:
    """Retrieve generated slots for a given venue and date.

    Looks up the venue's OperatingHours for on_date.weekday() (0=Monday..6=Sunday).
    If the venue is closed on that weekday, returns an empty list.
    Availability is dynamically computed and NEVER cached (ARCH-004).
    If table_pin is provided, filters available slots using the T-011 availability filter.
    """
    from apps.venues.models import Venue

    if isinstance(venue, int):
        venue_obj = Venue.objects.get(pk=venue)
    else:
        venue_obj = venue

    target_date = resolve_date(on_date)
    # Python weekday: 0=Monday .. 6=Sunday
    weekday = target_date.weekday()

    operating_hours = venue_obj.operating_hours.filter(weekday=weekday).first()
    if not operating_hours:
        return []

    slots = generate_slots(
        open_time=operating_hours.open_time,
        close_time=operating_hours.close_time,
        on_date=target_date,
        now=now,
    )

    if table_pin is not None:
        from apps.bookings.services import filter_available_slots_for_table

        slots = filter_available_slots_for_table(table_pin=table_pin, slots=slots, now=now)

    return slots


BLOCKED_SLOT_LIST_LIMIT = 100


def _find_matching_generated_slot(venue: Any, start_at_utc: datetime, now: datetime) -> Slot | None:
    """Verify start_at_utc matches an exact slot generated for the venue's operating hours."""
    local_date = start_at_utc.astimezone(TEHRAN).date()
    for candidate_date in (local_date, local_date - timedelta(days=1)):
        for slot in get_venue_slots_for_date(venue, on_date=candidate_date, now=now):
            if slot.start == start_at_utc:
                return slot
    return None


def create_blocked_slot(
    *,
    user: Any,
    pin_id: int,
    start_at: datetime,
    reason: str = "",
    now: datetime | None = None,
) -> Any:
    """Create a manual BlockedSlot for one TablePin and one generated slot window (FR-011 / T-026).

    Policies:
    - Owner/admin authorization via authorize_pin_owner (403/404).
    - Past slot (start_at <= now) rejected with InvalidSlotError (400 INVALID_SLOT).
    - start_at must align with an exact generated slot for the pin's venue (422 VALIDATION_ERROR).
    - Acquires TablePin row lock (select_for_update) inside transaction.atomic().
    - Rejects if any CONFIRMED or active PENDING_PAYMENT booking overlaps (409 SLOT_ALREADY_RESERVED).
    - Rejects if any existing BlockedSlot overlaps (409 SLOT_ALREADY_RESERVED).
    """
    from apps.bookings.models import Booking, BookingStatus
    from apps.panoramas.models import TablePin
    from apps.panoramas.services import authorize_pin_owner
    from apps.scheduling.models import BlockedSlot

    current_time = now or dj_timezone.now()
    if dj_timezone.is_naive(current_time):
        current_time = current_time.replace(tzinfo=UTC)
    else:
        current_time = current_time.astimezone(UTC)

    if dj_timezone.is_naive(start_at):
        start_at_utc = start_at.replace(tzinfo=UTC)
    else:
        start_at_utc = start_at.astimezone(UTC)

    pin = authorize_pin_owner(user, pin_id)

    if start_at_utc <= current_time:
        raise InvalidSlotError("Cannot block a slot that has already started or is in the past.")

    matched_slot = _find_matching_generated_slot(pin.venue, start_at_utc, current_time)
    if matched_slot is None:
        raise DjangoValidationError(
            {"start_at": ["start_at must align exactly with a generated slot for this venue."]}
        )

    end_at_utc = matched_slot.end

    with transaction.atomic():
        locked_pin = TablePin.objects.select_for_update().get(pk=pin.pk)

        # Expire stale unpaid holds before checking occupying bookings
        Booking.objects.filter(
            table_pin_id=locked_pin.pk,
            status=BookingStatus.PENDING_PAYMENT,
            lock_expires_at__lte=current_time,
        ).update(status=BookingStatus.EXPIRED, updated_at=current_time)

        has_booking_conflict = (
            Booking.objects.filter(
                table_pin_id=locked_pin.pk,
                start_at__lt=end_at_utc,
                end_at__gt=start_at_utc,
            )
            .filter(
                models.Q(status=BookingStatus.CONFIRMED)
                | models.Q(status=BookingStatus.PENDING_PAYMENT, lock_expires_at__gt=current_time)
            )
            .exists()
        )
        if has_booking_conflict:
            raise SlotAlreadyReservedError(
                "Cannot block a slot that already has a confirmed or pending booking."
            )

        has_block_conflict = BlockedSlot.objects.filter(
            table_pin_id=locked_pin.pk,
            start_at__lt=end_at_utc,
            end_at__gt=start_at_utc,
        ).exists()
        if has_block_conflict:
            raise SlotAlreadyReservedError("This slot is already blocked.")

        return BlockedSlot.objects.create(
            table_pin=locked_pin,
            start_at=start_at_utc,
            end_at=end_at_utc,
            reason=(reason or "").strip(),
            created_by=user,
        )


def list_blocked_slots(
    *,
    user: Any,
    pin_id: int,
    now: datetime | None = None,
    limit: int = BLOCKED_SLOT_LIST_LIMIT,
) -> list:
    """List upcoming blocked slots for an owner's TablePin ordered by start_at."""
    from apps.panoramas.services import authorize_pin_owner
    from apps.scheduling.models import BlockedSlot

    pin = authorize_pin_owner(user, pin_id)
    current_time = now or dj_timezone.now()
    return list(
        BlockedSlot.objects.filter(table_pin=pin, start_at__gte=current_time)
        .order_by("start_at")[:limit]
    )


def delete_blocked_slot(*, user: Any, block_id: int) -> None:
    """Hard-delete a BlockedSlot owned by the caller (Task T-026 / FR-011)."""
    from apps.accounts.models import UserRole
    from apps.scheduling.models import BlockedSlot

    if not (
        getattr(user, "is_staff", False)
        or getattr(user, "role", None) in (UserRole.VENUE_OWNER, UserRole.ADMIN)
    ):
        raise PermissionDenied("Only venue owners or admins can manage blocked slots.")

    block = BlockedSlot.objects.select_related("table_pin__venue").filter(pk=block_id).first()
    if not block:
        raise Http404("Blocked slot not found.")

    if block.table_pin.venue.owner_id != user.id and not (
        user.is_staff or user.role == UserRole.ADMIN
    ):
        raise PermissionDenied("You do not own the venue for this blocked slot.")

    block.delete()
