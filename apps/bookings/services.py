"""Booking service layer - atomic lock creation and cancellation.

Task T-011: Defines the slot availability intersection interface used by
Task T-012 (atomic lock service) and Task T-010 (scheduling).
"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import TYPE_CHECKING, Optional, Union

from django.db import models
from django.utils import timezone

from apps.bookings.models import Booking, BookingStatus

if TYPE_CHECKING:
    from apps.panoramas.models import TablePin


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
        now = timezone.now()

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
    """Filter generated calendar slots against active bookings and locks.

    Interface for slot availability intersection with existing bookings.
    Takes a list of scheduling.Slot objects and returns only those where
    the table has no active CONFIRMED or PENDING_PAYMENT lock.
    """
    if now is None:
        now = timezone.now()

    available = []
    for slot in slots:
        if not is_table_slot_occupied(table_pin=table_pin, start_at=slot.start, now=now):
            available.append(slot)
    return available


def create_booking_lock(*args, **kwargs):
    """Atomic booking lock service placeholder (implemented in Task T-012)."""
    raise NotImplementedError("Booking lock service is implemented in task T-012.")
