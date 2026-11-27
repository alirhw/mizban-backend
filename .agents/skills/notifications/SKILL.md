# Skill: In-App Notifications (FR-36, BR-10, BR-16)

## What it teaches
How booking events reach the right person inside the app — a new confirmed
booking and a cancellation in the venue-owner panel with an unread marker,
and a status change visible in the customer panel — with no SMS and no
email involved at all.

## Decided (T-039, 2026-11-27) — these replace the proposals below; do not re-open them
- The app EXISTS: `apps/notifications/` with `notifications-engineer:
  write: ["apps/notifications/**"]` in `ownership.yaml`.
- Type list is exactly `BOOKING_CONFIRMED`, `BOOKING_CANCELLED`,
  `VENUE_APPROVED`, `VENUE_REJECTED` — no others in v1.
- Recipient matrix (owner-only for booking events): the venue owner gets
  a row for a new CONFIRMED booking and for a cancellation; the CUSTOMER
  gets NO row (they see the status change in `GET /api/v1/bookings/my/`).
  Venue rows ARE included: `VENUE_APPROVED` and `VENUE_REJECTED` (with
  the rejection reason in the body).
- The model has TWO nullable FKs, both `SET_NULL`: `booking` and `venue`
  (venue rows have no booking).
- List pagination: default 50, max 100.

## Steps
1. Home: a NEW app `apps/notifications/` (decided T-039:
   `apps/notifications/`, entry `notifications-engineer` in
   `ownership.yaml`). Do NOT bolt notifications onto bookings
   or accounts without that decision: `ownership.yaml` must gain an
   entry for the new app at G2/G3, or the pre-edit hook will bounce the
   work. The notification rows are a distinct domain, like reviews.
2. Model: `Notification` — `recipient` (FK to the user), `type`
   (decided T-039: exactly `BOOKING_CONFIRMED`, `BOOKING_CANCELLED`,
   `VENUE_APPROVED`, `VENUE_REJECTED`), `booking` (FK, nullable,
   `SET_NULL`) and `venue` (FK, nullable, `SET_NULL` — venue rows have
   no booking); never `CASCADE` away audit data, `is_read` (default
   False), `created_at`. Title/body text is Persian UI copy, pinned by
   the UX Designer at G2 — the service stores the type + booking
   reference, and the copy is rendered from them, not free-typed per row.
3. Creation is synchronous, in the SAME transaction as the state change
   that triggers it: the bookings service (confirm / cancel) calls the
   notifications service before commit. A notification must never be
   lost because a background job failed — if the design ever moves
   creation to Celery, it must prove at-least-once delivery at G2.
4. Recipients (FR-36): the venue owner gets a row for a new CONFIRMED
   booking on their venue and for a cancellation of one of their venue's
   bookings. The customer sees a booking's status change in their own
   panel (`GET /api/v1/bookings/my/`); decided T-039: the customer gets
   NO Notification row. The venue owner also gets a row when their venue
   is approved (`VENUE_APPROVED`) and when it is rejected
   (`VENUE_REJECTED`, with the reason in the body).
5. No SMS, no email (BR-10): notifications are in-app only; SMS is used
   only for OTP. Never call the SMS provider from notification code, and
   never add an email field to the model.
6. Read API: list ONLY the requesting user's own notifications (BR-16 —
   a user accesses only their own data), newest first, bounded
   pagination (default 50, max 100 — decided T-039). An unread-count
   endpoint and `mark-as-read` (single + mark-all) are part of the same
   task; marking another user's notification read is a 403, not a
   silent no-op.
7. Privacy (BR-13): a notification body never contains a customer's
   phone number. It may name the table/slot/venue — the exact fields
   are pinned at G2.
8. No delete endpoint in v1 unless the G1 spec says so. Retention /
   cleanup of old rows is a separate, later decision — do not invent a
   purge job in this task.

## Example
```python
# apps/bookings/services.py — the trigger lives with the state change
with transaction.atomic():
    booking.transition_to(BookingStatus.CONFIRMED)
    create_notification(
        recipient=booking.venue.owner,
        type=NotificationType.BOOKING_CONFIRMED,
        booking=booking,
    )
# Same transaction: if the confirm rolls back, no notification exists.
```

## Common mistakes
- Sending booking notifications by SMS (BR-10 violation — SMS is OTP-only).
- Creating the notification in a view, or after the transaction commits
  without a retry story — a crash then loses it silently.
- Listing all notifications to any logged-in user (BR-16: own data only).
- Putting the customer's phone number in the notification body (BR-13).
- Inventing the recipient matrix ("surely the customer wants one too")
  instead of pinning it at G1.
- Adding a notifications app without an `ownership.yaml` entry — the
  work bounces at the pre-edit hook and the gate packet has to explain why.
