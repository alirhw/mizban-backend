# Skill: Booking Lock (TD-004)

## What it teaches
How to hold a table for one customer during payment so double booking is
mathematically impossible: a database-level, time-bounded lock inside an
atomic transaction with row locking — no Redis locks, no cleanup-job
dependency.

## Steps
1. All availability logic lives in `apps/bookings/services.py` and the
   named QuerySet `Booking.objects.active_locks_for_slot(table_pin_id,
   slot_date, slot_start_time)` — one definition of "occupied": status
   CONFIRMED, or PENDING_PAYMENT with `lock_expires_at > now` (aware UTC).
2. To create a hold, open `transaction.atomic()`, lock the TablePin row
   with `select_for_update()`, then check `active_locks_for_slot(...)`.
   A conflict raises the domain error → HTTP 409 `SLOT_ALREADY_RESERVED`.
3. Insert the Booking as `PENDING_PAYMENT` with `locked_at = now` and
   `lock_expires_at = now + 10 minutes`. Commit. Only after commit may any
   external call happen (payment token request).
4. Availability reads use the same QuerySet at query time — an expired
   lock is automatically invisible; a periodic Beat task may tidy statuses
   to EXPIRED for reporting, but correctness never depends on it.
5. Confirmation (from the verified payment callback) re-locks the booking
   row with `select_for_update()`, checks the status is still
   PENDING_PAYMENT and the verify arrived before `lock_expires_at`,
   then sets CONFIRMED — all in one transaction.
6. Cancellation (≥36h before slot start, BR-004) runs in one transaction:
   lock the booking row, set CANCELLED, credit the wallet via the wallet
   service (see wallet-ledger skill).

## Example
```python
# apps/bookings/services.py
from django.db import transaction
from django.utils import timezone
from datetime import timedelta

LOCK_TTL = timedelta(minutes=10)

def create_booking_lock(*, user, table_pin, slot_date, slot_start_time):
    with transaction.atomic():
        pin = TablePin.objects.select_for_update().get(pk=table_pin.pk)
        if Booking.objects.active_locks_for_slot(pin.pk, slot_date, slot_start_time).exists():
            raise SlotAlreadyReservedError(...)
        now = timezone.now()
        return Booking.objects.create(
            user=user, table_pin=pin, slot_date=slot_date,
            slot_start_time=slot_start_time, status="PENDING_PAYMENT",
            locked_at=now, lock_expires_at=now + LOCK_TTL,
        )
# transaction committed here — only NOW call the payment gateway.
```

## Common mistakes
- **Banned:** `if table.is_reserved: error` then set a boolean — two
  requests pass the check together (classic race).
- **Banned:** Redis Redlock — extra failure modes, not synchronised with
  the Postgres transaction (rejected in TD-004).
- **Banned:** correctness depending on a cron/Beat sweep — if the sweeper
  dies, tables must still free themselves by timestamp comparison.
- Calling the gateway inside the atomic block (row lock held during a
  slow bank call).
- Checking availability in Python loops instead of the shared QuerySet —
  two definitions of "free" will diverge.
