"""Booking service layer - atomic lock creation and cancellation.

Contract (implemented in task T-012, on the T-011 Booking model):

    create_booking_lock(*, user, table_pin, slot_date, slot_start_time,
                        addon_ids=()) -> Booking

Behaviour (TD-004, BR-001, BR-002, Architecture Spec sections 9/12):
- Runs inside transaction.atomic(); the TablePin row is locked with
  select_for_update() before availability is checked (ARCH-002).
- Raises LeadTimeViolationError when the slot starts < 24h from now.
- Raises SlotAlreadyReservedError (409 SLOT_ALREADY_RESERVED) when an
  active lock or confirmed booking overlaps the requested slot.
- On success creates Booking(status=PENDING_PAYMENT, locked_at=now,
  lock_expires_at=now + 10 minutes). Correctness never depends on the
  periodic cleanup task; expired locks simply stop blocking.
"""
from __future__ import annotations


def create_booking_lock(*args, **kwargs):
    raise NotImplementedError("Booking lock service is implemented in task T-012.")
