"""Jalali (Solar Hijri) conversion helpers - presentation layer ONLY.

ARCH-006: every timestamp in the backend is UTC. These thin wrappers over
`jdatetime` exist so the API/frontend can *display* Jalali dates and parse
Jalali input at the boundary. Never store a Jalali value in the database.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone as dt_timezone
from typing import Union
from zoneinfo import ZoneInfo

import jdatetime
from django.utils import timezone

TEHRAN = ZoneInfo("Asia/Tehran")
JALALI_DATE_FORMAT = "%Y/%m/%d"
JALALI_DATETIME_FORMAT = "%Y/%m/%d %H:%M"


def to_jalali(value: datetime) -> jdatetime.datetime:
    """Convert an aware UTC datetime to a Jalali datetime (Asia/Tehran)."""
    if timezone.is_naive(value):
        raise ValueError("to_jalali expects a timezone-aware datetime (UTC).")
    return jdatetime.datetime.fromgregorian(datetime=value.astimezone(TEHRAN))


def format_jalali(value: datetime, fmt: str = JALALI_DATETIME_FORMAT) -> str:
    """Format an aware UTC datetime as a Jalali string, e.g. '1404/08/20 19:30'."""
    return to_jalali(value).strftime(fmt)


def parse_jalali_date(value: str, fmt: str = JALALI_DATE_FORMAT) -> date:
    """Parse a Jalali date string ('1404/08/20') into a Gregorian date."""
    return jdatetime.datetime.strptime(value, fmt).date().togregorian()


def parse_jalali_datetime(value: str, fmt: str = JALALI_DATETIME_FORMAT) -> datetime:
    """Parse a Jalali datetime string into an aware UTC datetime.

    The input is interpreted as Asia/Tehran wall-clock time.
    """
    naive_tehran = jdatetime.datetime.strptime(value, fmt).togregorian()
    aware_tehran = naive_tehran.replace(tzinfo=TEHRAN)
    return aware_tehran.astimezone(dt_timezone.utc)


def jalali_slot_window(value: str, fmt: str = JALALI_DATE_FORMAT) -> tuple[datetime, datetime]:
    """Return the UTC (start, end) instants bounding one Jalali calendar day.

    Useful for 'slots of this Jalali date' queries at the API boundary.
    """
    gdate = parse_jalali_date(value, fmt)
    start = datetime.combine(gdate, time.min, tzinfo=TEHRAN).astimezone(dt_timezone.utc)
    end = datetime.combine(gdate, time.max, tzinfo=TEHRAN).astimezone(dt_timezone.utc)
    return start, end


def resolve_date(date_input: Union[date, datetime, str]) -> date:
    """Resolve a date input which may be date, datetime, ISO string, or Jalali string.

    Supports:
    - date / datetime instances
    - Jalali string formats: '1404/10/15', '1404-10-15'
    - ISO Gregorian format: '2026-01-05'
    """
    if isinstance(date_input, datetime):
        return date_input.date()
    if isinstance(date_input, date):
        return date_input

    date_str = str(date_input).strip()
    if "/" in date_str or date_str.startswith("13") or date_str.startswith("14"):
        return parse_jalali_date(date_str.replace("-", "/"))

    return date.fromisoformat(date_str)

