"""Tests for the slot engine (BR-001 / BR-002) - task T-010.

Contract under test (see services.py docstring):
- Deterministic 90-minute slots with 30-minute cleaning buffer (120-minute cycle).
- Slots must fit inside the working range (including cross-midnight shifts).
- Lead-time rule (BR-002): a slot starting < 24h from `now` is not bookable.
- Boundary test: exactly 24h00m ahead is bookable, 23h59m is not.
- Closed weekdays return empty slot list.
- All timestamps in aware UTC; presentation formatting in Jalali.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from django.test import Client
import pytest

from apps.accounts.models import UserRole
from apps.scheduling.services import (
    LEAD_TIME_THRESHOLD,
    SLOT_DURATION,
    generate_slots,
    get_venue_slots_for_date,
)
from apps.venues.models import OperatingHours, SubscriptionStatus, Venue
from apps.venues.tests.factories import OperatingHoursFactory, UserFactory, VenueFactory
from core.jalali import TEHRAN

NOW = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
DAY = datetime(2026, 1, 5, tzinfo=timezone.utc).date()  # > 24h after NOW


def test_slots_are_90_minutes_with_30_minute_buffer():
    """Unskipped fail-first test: 90-minute slots separated by 30-minute buffers."""
    slots = generate_slots(open_time=time(9, 0), close_time=time(13, 0), on_date=DAY, now=NOW)
    assert len(slots) == 2  # 09:00-10:30 and 11:00-12:30 fit; 13:00 start would overrun closing
    for slot in slots:
        assert slot.end - slot.start == timedelta(minutes=90)
    starts = [slot.start for slot in slots]
    assert starts[1] - starts[0] == timedelta(minutes=120)


def test_slots_inside_24h_lead_are_not_bookable():
    """Unskipped fail-first test: slots starting < 24h from now have is_bookable=False."""
    soon = NOW + timedelta(hours=12)
    slots = generate_slots(open_time=time(9, 0), close_time=time(13, 0), on_date=soon.date(), now=NOW)
    assert slots, "calendar slots should still be generated"
    assert all(not slot.is_bookable for slot in slots)
    assert all(slot.disabled_reason == "LEAD_TIME_VIOLATION" for slot in slots)


def test_cross_midnight_hours_generates_slots_across_midnight():
    """Operating hours crossing midnight (e.g. 20:00 to 02:00) generate slots extending into next day."""
    # 20:00 - 02:00 (next day) gives a 6-hour window (360 minutes).
    # Slot 0: 20:00 - 21:30 (buffer to 22:00)
    # Slot 1: 22:00 - 23:30 (buffer to 00:00)
    # Slot 2: 00:00 - 01:30 (buffer to 02:00)
    # Candidate Slot 3 starts at 02:00 -> overrun close (02:00 + 90m > 02:00) -> not emitted.
    slots = generate_slots(open_time=time(20, 0), close_time=time(2, 0), on_date=DAY, now=NOW)
    assert len(slots) == 3

    for slot in slots:
        assert slot.end - slot.start == SLOT_DURATION

    # Starts spaced 120 minutes
    assert slots[1].start - slots[0].start == timedelta(minutes=120)
    assert slots[2].start - slots[1].start == timedelta(minutes=120)

    # Slot 2 starts on the next calendar day in local time
    slot2_local_start = slots[2].start.astimezone(TEHRAN)
    assert slot2_local_start.date() == DAY + timedelta(days=1)
    assert slot2_local_start.time() == time(0, 0)
    assert slot2_local_start.hour == 0
    assert slot2_local_start.minute == 0


def test_exact_24h_boundary_bookability():
    """Exact 24h boundary test: exactly 24h00m is bookable; 23h59m59s is not."""
    # Let open_time = 10:00 Tehran. 10:00 Tehran = 06:30 UTC.
    target_date = date(2026, 1, 2)
    open_t = time(10, 0)
    close_t = time(14, 0)

    # Slot 0 starts at 2026-01-02 06:30:00 UTC.
    # Case 1: now is exactly 24h before slot start (2026-01-01 06:30:00 UTC) -> bookable (>= 24h)
    now_exact_24h = datetime(2026, 1, 1, 6, 30, 0, tzinfo=timezone.utc)
    slots = generate_slots(open_time=open_t, close_time=close_t, on_date=target_date, now=now_exact_24h)
    assert slots[0].is_bookable is True
    assert slots[0].disabled_reason is None

    # Case 2: now is 1 second later (2026-01-01 06:30:01 UTC) -> 23h 59m 59s -> NOT bookable
    now_23h_59m_59s = datetime(2026, 1, 1, 6, 30, 1, tzinfo=timezone.utc)
    slots = generate_slots(open_time=open_t, close_time=close_t, on_date=target_date, now=now_23h_59m_59s)
    assert slots[0].is_bookable is False
    assert slots[0].disabled_reason == "LEAD_TIME_VIOLATION"

    # Case 3: now is 1 second earlier (2026-01-01 06:29:59 UTC) -> 24h 00m 01s -> bookable
    now_24h_01s = datetime(2026, 1, 1, 6, 29, 59, tzinfo=timezone.utc)
    slots = generate_slots(open_time=open_t, close_time=close_t, on_date=target_date, now=now_24h_01s)
    assert slots[0].is_bookable is True
    assert slots[0].disabled_reason is None


@pytest.mark.django_db
def test_venue_closed_weekday_returns_empty_slots():
    """When a venue has no OperatingHours for the target date's weekday, return empty list."""
    owner = UserFactory(role=UserRole.VENUE_OWNER)
    venue = VenueFactory(owner=owner)

    # 2026-01-05 is a Monday (weekday 0)
    monday = date(2026, 1, 5)
    assert monday.weekday() == 0

    # Configure operating hours ONLY for Tuesday (weekday 1)
    OperatingHoursFactory(
        venue=venue,
        weekday=1,  # Tuesday
        open_time=time(10, 0),
        close_time=time(18, 0),
    )

    # Query for Monday -> Venue is closed -> empty list
    slots_monday = get_venue_slots_for_date(venue, on_date=monday, now=NOW)
    assert slots_monday == []

    # Query for Tuesday -> Venue is open -> slots generated
    tuesday = date(2026, 1, 6)
    slots_tuesday = get_venue_slots_for_date(venue, on_date=tuesday, now=NOW)
    assert len(slots_tuesday) > 0


@pytest.mark.django_db
def test_get_venue_slots_for_date_with_jalali_date_string():
    """get_venue_slots_for_date supports Jalali date string inputs (e.g. '1404/10/15')."""
    owner = UserFactory(role=UserRole.VENUE_OWNER)
    venue = VenueFactory(owner=owner)

    # 1404/10/15 corresponds to 2026-01-05 (Monday, weekday 0)
    # Configure OperatingHours for weekday 0 (Monday)
    OperatingHoursFactory(
        venue=venue,
        weekday=0,
        open_time=time(9, 0),
        close_time=time(13, 0),
    )

    slots = get_venue_slots_for_date(venue, on_date="1404/10/15", now=NOW)
    assert len(slots) == 2
    assert slots[0].start.astimezone(TEHRAN).time() == time(9, 0)
    assert slots[1].start.astimezone(TEHRAN).time() == time(11, 0)


@pytest.mark.django_db
def test_scheduling_api_endpoint():
    """API endpoint GET /api/v1/scheduling/venues/{venue_id}/slots returns typed SlotOut schemas."""
    client = Client()
    owner = UserFactory(role=UserRole.VENUE_OWNER)
    venue = VenueFactory(owner=owner, is_approved=True, subscription_status=SubscriptionStatus.ACTIVE)

    # Weekday 0 (Monday)
    OperatingHoursFactory(
        venue=venue,
        weekday=0,
        open_time=time(9, 0),
        close_time=time(13, 0),
    )

    # Query via Gregorian date
    response = client.get(f"/api/v1/scheduling/venues/{venue.id}/slots?date=2026-01-05")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert "start" in data[0]
    assert "end" in data[0]
    assert "is_bookable" in data[0]
    assert "start_jalali" in data[0]
    assert "end_jalali" in data[0]
    assert data[0]["start_jalali"] != ""
