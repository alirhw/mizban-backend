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
from datetime import datetime


@dataclass(frozen=True)
class Slot:
    start: datetime
    end: datetime
    is_bookable: bool


def generate_slots(*args, **kwargs) -> list[Slot]:
    raise NotImplementedError("Slot engine is implemented in task T-010.")
