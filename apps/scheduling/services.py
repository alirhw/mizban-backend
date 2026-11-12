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
from datetime import date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, Optional, Union
from zoneinfo import ZoneInfo

from django.utils import timezone as dj_timezone

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
    disabled_reason: Optional[str] = None

    @property
    def date(self) -> date:
        return self.start.astimezone(TEHRAN).date()

    @property
    def start_time(self) -> time:
        return self.start.astimezone(TEHRAN).time()


def generate_slots(
    open_time: time,
    close_time: time,
    on_date: Union[date, datetime],
    now: Optional[datetime] = None,
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
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    # 1. Build operating window in local timezone
    open_local = datetime.combine(calendar_date, open_time, tzinfo=tz)
    if close_time <= open_time:
        # Crosses midnight into next calendar day
        close_local = datetime.combine(calendar_date + timedelta(days=1), close_time, tzinfo=tz)
    else:
        close_local = datetime.combine(calendar_date, close_time, tzinfo=tz)

    # 2. Convert to aware UTC (ARCH-006)
    open_utc = open_local.astimezone(timezone.utc)
    close_utc = close_local.astimezone(timezone.utc)

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


def resolve_date(date_input: Union[date, datetime, str]) -> date:
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
    venue: Union[Venue, int],
    on_date: Union[date, datetime, str],
    now: Optional[datetime] = None,
) -> list[Slot]:
    """Retrieve generated slots for a given venue and date.

    Looks up the venue's OperatingHours for on_date.weekday() (0=Monday..6=Sunday).
    If the venue is closed on that weekday, returns an empty list.
    Availability is dynamically computed and NEVER cached (ARCH-004).
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

    return generate_slots(
        open_time=operating_hours.open_time,
        close_time=operating_hours.close_time,
        on_date=target_date,
        now=now,
    )
