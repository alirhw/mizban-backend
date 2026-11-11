"""FAIL-FIRST targets for the slot engine (BR-001 / BR-002) - task T-010.

These tests define the expected behaviour of
apps.scheduling.services.generate_slots BEFORE it is implemented, so the
suite stays green via an explicit skip until T-010 lands. Remove the
skip marker in T-010 and make them pass; do not weaken the assertions.

Contract under test (see services.py docstring): slots are 90 minutes,
starts are 120 minutes apart (30-minute cleaning buffer), slots must fit
inside the working range, and a slot starting < 24h from `now` is not
bookable (BR-002).
"""
from datetime import datetime, time, timedelta, timezone

import pytest

from apps.scheduling.services import generate_slots

pytestmark = pytest.mark.skip(reason="pending T-010 slot engine (apps.scheduling.services.generate_slots)")

NOW = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
DAY = datetime(2026, 1, 5, tzinfo=timezone.utc).date()  # > 24h after NOW


def test_slots_are_90_minutes_with_30_minute_buffer():
    slots = generate_slots(open_time=time(9, 0), close_time=time(13, 0), on_date=DAY, now=NOW)
    assert len(slots) == 2  # 09:00-10:30 and 11:00-12:30 fit; 13:00 start would overrun closing
    for slot in slots:
        assert slot.end - slot.start == timedelta(minutes=90)
    starts = [slot.start for slot in slots]
    assert starts[1] - starts[0] == timedelta(minutes=120)


def test_slots_inside_24h_lead_are_not_bookable():
    soon = NOW + timedelta(hours=12)
    slots = generate_slots(open_time=time(9, 0), close_time=time(13, 0), on_date=soon.date(), now=NOW)
    assert slots, "calendar slots should still be generated"
    assert all(not slot.is_bookable for slot in slots)
