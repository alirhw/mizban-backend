# Spec 009 - Booking Auto-Complete After Slot End (FR-22)
Status: Done (Gate G4 Approved) | Lane: Full (bookings state machine) | Implements: FR-22 (prerequisite for BR-09 reviews) | Architecture: ARCH-002, ARCH-006

## 1. Problem and goal
Confirmed bookings remain in `CONFIRMED` status after their 90-minute reservation slot finishes (`end_at`). To enable post-visit reviews under **BR-09** (which permits reviews only on `COMPLETED` bookings) and keep customer booking histories accurate without manual intervention or client-side triggers, `CONFIRMED` bookings must automatically transition to `COMPLETED` once `end_at` has passed.

## 2. User stories
- **US-01** As a customer, I want my confirmed booking to transition to `COMPLETED` after my reserved slot ends, so that my visit history is accurate and I can later submit a review under BR-09.
- **US-02** As operations / the platform system, I want elapsed `CONFIRMED` bookings to be transitioned to `COMPLETED` safely, idempotently, and in bounded deterministic batches, so that concurrent workers never double-transition, deadlock, or touch unpaid/cancelled bookings.

## 3. Requirements (EARS)
- **REQ-COMPLETE-001** The system shall provide a domain service `complete_expired_bookings(now=None) -> int` in `apps/bookings/services.py` that transitions `CONFIRMED` bookings whose slot `end_at <= now` to `COMPLETED` using `Booking.transition_to(BookingStatus.COMPLETED)` and returns the number of transitioned bookings.
- **REQ-COMPLETE-002** When `now` is omitted (`None`), `complete_expired_bookings` shall default `now` to `timezone.now()` in aware UTC (**ARCH-006**); when `now` is provided, it shall be treated/enforced as aware UTC (**ARCH-006**).
- **REQ-COMPLETE-003** Boundary rule: `complete_expired_bookings` shall transition bookings where `end_at <= now` (inclusive of `end_at == now`), and shall not transition bookings where `end_at > now`.
- **REQ-COMPLETE-004** Bounded & deterministic batching: `complete_expired_bookings` shall process at most `500` bookings per invocation, selected in deterministic order `end_at ASC, id ASC`.
- **REQ-COMPLETE-005** Atomicity & concurrency safety (**ARCH-002**): `complete_expired_bookings` shall execute within `transaction.atomic()` and lock eligible `Booking` rows using `select_for_update(skip_locked=True)` on PostgreSQL 16 so concurrent invocations never block each other, deadlock, or double-transition a booking.
- **REQ-COMPLETE-006** Idempotency: re-running `complete_expired_bookings` immediately after a run (or when no eligible `CONFIRMED` bookings have `end_at <= now`) shall mutate zero rows and return `0`.
- **REQ-COMPLETE-007** Non-`CONFIRMED` isolation: `complete_expired_bookings` shall never transition or mutate bookings in `INITIATED`, `PENDING_PAYMENT`, `EXPIRED`, `CANCELLED`, or already-`COMPLETED` status (unpaid `PENDING_PAYMENT` holds expire; they never complete).
- **REQ-COMPLETE-008** Structured logging & zero PII: `complete_expired_bookings` shall emit structured logs recording each transitioned `booking_id` and the total transitioned count, and shall never log PII (no phone numbers, OTP codes, tokens, or secrets).
- **REQ-COMPLETE-009** Celery task: `apps/bookings/tasks.py` shall define `@shared_task(bind=True, name="bookings.complete_expired_bookings", ...)` (`complete_expired_bookings_task`) calling `complete_expired_bookings()`, applying bounded retries only for transient/infrastructure errors and never retrying deterministic errors (e.g., `ValueError`, `TypeError`).
- **REQ-COMPLETE-010** Management command: `apps/bookings/management/commands/complete_expired_bookings.py` (`python manage.py complete_expired_bookings`) shall invoke the same `complete_expired_bookings` service code path, and shall support an optional `--dry-run` flag that lists eligible `booking_id`s (bounded to `500`, ordered by `end_at ASC, id ASC`) without mutating database state.
- **REQ-COMPLETE-011** Read-model visibility (no API/contract change): `COMPLETED` bookings shall be visible to their owning customer in `GET /api/v1/bookings/my/` (`apps/bookings/services.py:561-565`, `list_customer_bookings`, returning `status="COMPLETED"` and `is_cancellable=False`) and `GET /api/v1/bookings/{booking_id}/receipt/` (`RECEIPT_AVAILABLE_STATUSES` at `apps/bookings/services.py:42`), with zero changes to endpoints, schemas, or `api/openapi.snapshot.json`.
- **REQ-COMPLETE-012** Operational schedule (deferred wiring): the recommended production execution cadence is every `15` minutes (via Celery task `bookings.complete_expired_bookings` or `python manage.py complete_expired_bookings`). Configuring the scheduler trigger (Celery Beat schedule or host cron) belongs to **T-032 Phase D deployment**, not T-033.

## 4. Business rules touched
- **FR-22** — Automatic transition of `CONFIRMED` bookings to `COMPLETED` after `end_at` passes.
- **BR-09 dependency** — Post-visit reviews (future task) require `Booking.status == COMPLETED`; auto-completion establishes the prerequisite state transition without implementing reviews.
- **ARCH-002** — No raw SQL; state mutations execute inside `transaction.atomic()` with `select_for_update(skip_locked=True)`.
- **ARCH-006** — All `end_at` and `now` timestamps are evaluated in aware UTC; no Jalali or localized timestamps are stored or compared.
- **Untouched rules** (explicitly unchanged): **BR-001** (90-minute slot + 30-minute cleaning buffer), **BR-002** (24-hour booking lead time), **BR-003 / ARCH-005** (table fee online vs. design add-ons payable in person), **BR-004** (36-hour cancellation window + non-withdrawable wallet refund; `COMPLETED` remains non-cancellable), **BR-005 / BR-006** (venue visibility & subscription expiry survival), **BR-11 / TD-004** (10-minute `PENDING_PAYMENT` booking lock), and **ADR-006** (late payment callback policy for `EXPIRED` bookings).

## 5. Non-functional targets
- **Concurrency & database:** Tested against PostgreSQL 16 using `transaction.atomic()` and `select_for_update(skip_locked=True)`; zero double-transitions and zero deadlocks under concurrent execution.
- **Time handling:** Aware UTC only (**ARCH-006**).
- **Batch bound:** Hard cap of `500` bookings per execution, ordered `end_at ASC, id ASC`.
- **Privacy & logging:** Zero PII in log records or command output (only `booking_id`s, counts, and sanitized error types).
- **Test coverage & quality:** Overall line coverage `>= 80%` (`branch = false`, `apps/` + `core/`) without regressing the measured `95%` baseline; `ruff check .`, `mypy .`, and `./check-contract.sh` pass cleanly.
- **Schema & API stability:** Zero database migrations (`apps/bookings/migrations/` untouched) and zero OpenAPI contract changes (`api/openapi.snapshot.json` untouched).

## 6. Acceptance criteria (Gherkin)

```gherkin
Scenario: 1. Past CONFIRMED booking transitions to COMPLETED
  Given a Booking with status CONFIRMED and end_at = now - 5 minutes
  When complete_expired_bookings(now=now) runs
  Then it returns 1
    And the Booking status in PostgreSQL is COMPLETED.

Scenario: 2. Future CONFIRMED booking stays untouched
  Given a Booking with status CONFIRMED and end_at = now + 30 minutes
  When complete_expired_bookings(now=now) runs
  Then it returns 0
    And the Booking status remains CONFIRMED.

Scenario: 3. Exact boundary end_at == now completes while end_at == now + 1 minute does not
  Given Booking A with status CONFIRMED and end_at = now
    And Booking B with status CONFIRMED and end_at = now + 1 minute
  When complete_expired_bookings(now=now) runs
  Then it returns 1
    And Booking A status is COMPLETED
    And Booking B status remains CONFIRMED.

Scenario: 4. Past PENDING_PAYMENT booking is never completed
  Given a Booking with status PENDING_PAYMENT and end_at = now - 10 minutes
  When complete_expired_bookings(now=now) runs
  Then it returns 0
    And the Booking status remains PENDING_PAYMENT.

Scenario: 5. Past CANCELLED and EXPIRED bookings remain untouched
  Given Booking C with status CANCELLED and end_at = now - 10 minutes
    And Booking E with status EXPIRED and end_at = now - 10 minutes
  When complete_expired_bookings(now=now) runs
  Then it returns 0
    And Booking C remains CANCELLED
    And Booking E remains EXPIRED.

Scenario: 6. Already-COMPLETED booking and idempotent second run return 0
  Given Booking D already in status COMPLETED with end_at = now - 2 hours
    And Booking A in status CONFIRMED with end_at = now - 1 hour
  When complete_expired_bookings(now=now) runs the first time
  Then it returns 1 and Booking A becomes COMPLETED while Booking D stays COMPLETED
  When complete_expired_bookings(now=now) runs a second time immediately with now
  Then it returns 0 and no Booking rows are modified.

Scenario: 7. Bulk run transitions only past CONFIRMED bookings in deterministic end_at order
  Given 3 CONFIRMED bookings with end_at at now - 3h, now - 2h, and now - 1h
    And 2 CONFIRMED bookings with end_at at now + 1h and now + 2h
  When complete_expired_bookings(now=now) runs
  Then it returns 3
    And the 3 past bookings transition to COMPLETED in end_at ASC, id ASC order
    And the 2 future bookings remain CONFIRMED.

Scenario: 8. Management command supports --dry-run and normal execution
  Given 2 CONFIRMED bookings with end_at <= now and 1 CONFIRMED booking with end_at > now
  When "python manage.py complete_expired_bookings --dry-run" runs
  Then stdout lists the 2 eligible booking_ids without PII
    And both bookings remain CONFIRMED in PostgreSQL
  When "python manage.py complete_expired_bookings" runs
  Then both eligible bookings transition to COMPLETED
    And the future booking remains CONFIRMED.

Scenario: 9. Celery task executes auto-completion and retries only on transient errors
  Given Booking A with status CONFIRMED and end_at = now - 15 minutes
  When Celery task "bookings.complete_expired_bookings" (complete_expired_bookings_task) runs
  Then it delegates to complete_expired_bookings() and transitions Booking A to COMPLETED
  When complete_expired_bookings() raises a transient OperationalError
  Then the task schedules a bounded retry
  When complete_expired_bookings() raises a deterministic ValueError
  Then the task does not retry.

Scenario: 10. Completed booking remains visible in customer bookings and split receipt endpoints
  Given Booking A transitioned from CONFIRMED to COMPLETED for customer U
  When customer U requests GET /api/v1/bookings/my/
  Then Booking A is returned with status "COMPLETED" and is_cancellable = false
  When customer U requests GET /api/v1/bookings/{Booking A.id}/receipt/
  Then the response is 200 with status "COMPLETED" and unchanged split receipt totals.
```

## 7. Out of scope (explicit)
- Reviews feature implementation (`FR-24`, `FR-25`, `FR-41`, `BR-09` review creation, rating aggregation, and moderation)
- Notifications (`FR-36`, SMS/email on booking completion)
- Wallet payment (`FR-17`)
- Venue subscriptions (`FR-27`)
- Design-addon management API (`FR-32`)
- Venue submit/rejection workflow (`FR-33`, `FR-37`)
- Admin financial report (`FR-40`)
- Frontend UI changes
- Database schema migrations
- Celery Beat schedule or host cron configuration (belongs to **T-032 Phase D deployment**)
- Any public or admin HTTP endpoint to trigger booking completion

## 8. Open questions
None — operational scheduler trigger (every 15 minutes via Celery Beat or host cron) is explicitly assigned to **T-032 Phase D deployment**.
