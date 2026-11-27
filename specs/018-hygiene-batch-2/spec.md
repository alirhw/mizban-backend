# Spec 018 - Hygiene Batch 2 (T-043: T-037 / T-039 / T-040 / T-042 Follow-Ups)
Status: Draft (G1 Pending) | Owner: Platform / Maintenance | Lane: Standard | Implements: T-043 Hygiene Batch 2 (T-037, T-039, T-040, T-042 Follow-Ups) | Architecture: ARCH-001, ARCH-002, ARCH-004

## 1. Problem and goal
Recent gate packets and code reviews (T-037, T-039, T-040, T-042) surfaced small hygiene, query-efficiency, indexing, documentation, and test-coverage follow-ups. This spec defines the exact behavioral, schema, index-migration, query, test, and documentation requirements to close all 8 T-043 scope items cleanly while explicitly leaving T-030 OTP IP-spoofing, T-030 CVE/dependency remediation, CI setup, and Sentry/Phase D out of scope.

## 2. User stories
- **US-01** As a platform engineer, I want `TablePinCreateIn`/`TablePinUpdateIn` bounds (`StrictInt`, `capacity >= 0`, `reservation_fee_toman` `0..9_223_372_036_854_775_807`) verified and tested, and `Review.is_visible` indexed via a dedicated `0002_*` migration with `specs/014-reviews-backend/spec.md` aligned to `review_rating_between_1_and_5`, so that API schemas, DB indexes, and specs match without unnecessary table renames.
- **US-02** As a billing/notification maintainer, I want `handle_payment_callback` and `pay_booking_with_wallet` in `apps/billing/services/payment.py` to `select_related("venue", "venue__owner")`, and `initiate_payment` to pass an explicit `""` for `customer_email` with an explanatory comment (since `accounts.User` has no `email` field), so that notification creation avoids lazy queries and dead `getattr` lookups are removed.
- **US-03** As a QA/test engineer, I want the 5 isolated T-039 notification tests and the 2 reachable uncovered-branch tests (`notifications/services.py` `SET_NULL` fallback and `billing/services/report.py` `ValueError` catch on `"2026-02-31"`), so that all critical notification, idempotency, and date-validation branches are regression-tested.
- **US-04** As a reviewer, I want the intentional T-036 bulk admin reject behavior and the T-040 `/admin/financial-report` no-slash alias behavior explicitly documented, so that future audits do not flag them as regressions.

## 3. Requirements (EARS)

### Item 1 — `TablePinCreateIn` / `TablePinUpdateIn` Bounds (T-042 Reviewer Info)
- **REQ-HYG2-001** **`TablePinCreateIn` and `TablePinUpdateIn` integer & range bounds (`apps/panoramas/schemas.py:28-148`):** `TablePinCreateIn` and `TablePinUpdateIn` shall enforce `StrictInt` on `capacity` (rejecting booleans/floats/strings, `ge=0` at schema field level alongside positive capacity validation) and `StrictInt` on `reservation_fee_toman` with bounds `0..9_223_372_036_854_775_807` (`ge=0, le=9_223_372_036_854_775_807`). Invalid types or out-of-range values shall return HTTP `422` (`VALIDATION_ERROR`), covered by isolated tests in `apps/panoramas/tests/test_table_pins_api.py`.

### Item 2 — Billing `select_related` for `"venue"` and `"venue__owner"` (T-039 Code Reviewer Nit)
- **REQ-HYG2-002** **Eager-load `"venue"` and `"venue__owner"` in `apps/billing/services/payment.py`:**
  - In `handle_payment_callback` (`apps/billing/services/payment.py:385-389`), `Booking.objects.select_for_update().select_related(...)` shall include `"venue"` and `"venue__owner"` (e.g. `.select_related("table_pin", "venue", "venue__owner")`).
  - In `pay_booking_with_wallet` (`apps/billing/services/payment.py:532`), `Booking.objects.select_for_update()` shall include `.select_related("venue", "venue__owner")` so subsequent `BOOKING_CONFIRMED` notification creation (`booking.venue.owner`) does not trigger lazy queries.

### Item 3 — Explicit `""` for `customer_email` in `initiate_payment` (T-042 Reviewer Info)
- **REQ-HYG2-003** **Remove stale `getattr(booking.customer, "email", "")` (`apps/billing/services/payment.py:145`):** In `initiate_payment`, `PaymentInitiateRequest.customer_email` shall be set to explicit `""` with a concise inline comment stating that `accounts.User` has no `email` field, replacing `getattr(booking.customer, "email", "")`.

### Item 4 — 5 Isolated T-039 Notification Tests (T-039 Gate Packet Notes)
- **REQ-HYG2-004** **Isolated T-039 notification regression tests (`apps/notifications/tests/test_notifications.py`):** The test suite shall include 5 isolated tests covering:
  1. `handle_payment_callback` creates a `BOOKING_CONFIRMED` notification for the venue owner on successful payment confirmation.
  2. Idempotent `cancel_booking` replay does not create duplicate `BOOKING_CANCELLED` notifications.
  3. An `ADMIN` user receives `0` notification rows (no customer/owner notifications leak to `ADMIN`).
  4. `offset < 0` is clamped to `0` when listing notifications.
  5. Mocked 0-SMS assertion confirming notification creation/listing triggers `0` SMS provider calls.

### Item 5 — T-037 Review Index, Constraint Alignment & Direct Lookup (T-037 Code Reviewer Nits)
- **REQ-HYG2-005** **`Review.is_visible` database index (`apps/reviews/models.py:17`, `apps/reviews/migrations/0002_*.py`):** `Review.is_visible` shall declare `db_index=True` (`models.BooleanField(default=True, db_index=True)`) accompanied by migration `apps/reviews/migrations/0002_*.py`.
- **REQ-HYG2-006** **Rating constraint name alignment (`specs/014-reviews-backend/spec.md:31,82`):** `specs/014-reviews-backend/spec.md` lines 31 and 82 shall use `review_rating_between_1_and_5` to match `apps/reviews/models.py:29` and avoid an unnecessary database `RenameConstraint` migration.
- **REQ-HYG2-007** **Direct `booking__venue_id` lookup (`apps/reviews/services.py:139`):** Public venue review queries in `apps/reviews/services.py` (`list_venue_reviews`) shall use direct `booking__venue_id=venue_id` lookup (verifying no redundant join/lookup).

### Item 6 — Reachable Uncovered Branches (T-039 / T-040 Gate Packets)
- **REQ-HYG2-008** **`notifications/services.py` `SET_NULL` fallback test (`apps/notifications/tests/test_notifications.py`):** Add tests exercising `render_notification_copy` / `_booking_details` when `notification.booking` is `None` (`BOOKING_CONFIRMED` / `BOOKING_CANCELLED` `SET_NULL` fallback) and `notification.venue` is `None` (`VENUE_APPROVED` / `VENUE_REJECTED` `SET_NULL` fallback), verifying safe Persian fallback copy is returned without `AttributeError`.
- **REQ-HYG2-009** **`billing/services/report.py` `ValueError` catch test (`apps/billing/tests/test_admin_financial_report.py`):** Add a test passing an invalid calendar date matching `_ISO_DATE_RE` (specifically `"2026-02-31"`), verifying `date.fromisoformat` raises `ValueError` and `_parse_iso_date` catches it to raise `DjangoValidationError` / HTTP `422` (`VALIDATION_ERROR`).

### Item 7 (Document-Only) — T-036 Bulk Admin Reject Behavior
- **REQ-HYG2-010** **Document intentional bulk admin reject behavior (`apps/venues/admin.py:59-66`):** `VenueAdmin.reject_selected_venues` sets `is_approved=False` and `review_status=VenueReviewStatus.REJECTED` without updating `rejection_reason` (leaving the prior value, typically `""`), whereas the single-reject API requires a non-blank `rejection_reason`. This behavior is **intentionally left unchanged** in T-043 and is documented here for audit clarity.

### Item 8 (Document-Only) — T-040 Financial Report No-Slash Alias
- **REQ-HYG2-011** **Document intentional `/admin/financial-report` no-slash alias (`apps/billing/api.py:286-298`):** `/admin/financial-report` (`include_in_schema=False`) is intentionally kept alongside the canonical `/admin/financial-report/` route for client convenience; `api/openapi.snapshot.json` contains only the canonical `/api/v1/billing/admin/financial-report/` route with no duplicate `operationId`. This behavior is **intentionally left unchanged** in T-043.

## 4. Business rules touched
- **BR-09 / FR-24 / FR-25** — `Review.is_visible` indexing (`0002_*`) supports visible-only read-time review queries; constraint name `review_rating_between_1_and_5` remains intact without DB rename.
- **FR-36 / BR-10 / BR-16** — In-app notifications remain SMS-free, role-isolated (`ADMIN` sees `0` rows), idempotent on booking cancel replay, and resilient to `SET_NULL` (`booking=None` / `venue=None`).
- **FR-40 / UC-10** — Financial report date parsing rejects impossible calendar dates matching `YYYY-MM-DD` (e.g. `"2026-02-31"`) with `422 VALIDATION_ERROR`; no-slash alias stays excluded from OpenAPI schema.
- **ARCH-001 / ARCH-002** — Business logic stays in `services.py`; `select_related("venue", "venue__owner")` executes inside existing transaction boundaries.

## 5. Non-functional targets
- **Schema & Query Efficiency:** `TablePinCreateIn`/`TablePinUpdateIn` reject booleans and out-of-range fees (`422`); `handle_payment_callback` and `pay_booking_with_wallet` eager-load `venue` and `venue__owner`; `Review.is_visible` is indexed (`db_index=True`).
- **Checks & Contract:** `python manage.py check`, `python manage.py makemigrations --check --dry-run`, `ruff check .`, `mypy .`, `pytest` (PostgreSQL), and `./check-contract.sh` pass with `0` failures and `0` skipped tests. `api/openapi.snapshot.json` remains clean with no duplicate `operationId`.

## 6. Acceptance criteria (Gherkin)

```gherkin
Scenario: 1. TablePin bounds reject booleans and out-of-range values
  Given an authenticated VENUE_OWNER
  When the owner calls TablePin create or update with capacity=true, capacity=-1, reservation_fee_toman=true, or reservation_fee_toman=9223372036854775808
  Then HTTP 422 with error_code "VALIDATION_ERROR" is returned.

Scenario: 2. Payment services eager-load venue/venue__owner and avoid dead email getattr
  Given a Booking for a Venue owned by Owner U
  When handle_payment_callback or pay_booking_with_wallet confirms the booking
  Then Booking is fetched with select_related("venue", "venue__owner")
  When initiate_payment builds PaymentInitiateRequest
  Then customer_email is "" without calling getattr(booking.customer, "email", "").

Scenario: 3. Five isolated T-039 notification tests and SET_NULL fallback pass
  When pytest runs apps/notifications/tests/test_notifications.py
  Then handle_payment_callback notification creation, idempotent cancel_booking replay (no duplicate), ADMIN 0 rows, offset < 0 clamping, mocked 0-SMS assertion, and SET_NULL (booking=None / venue=None) fallback copy all pass.

Scenario: 4. T-037 Review index migration and spec alignment
  When python manage.py migrate and python manage.py makemigrations --check --dry-run run
  Then apps/reviews/migrations/0002_*.py applies cleanly with db_index=True on Review.is_visible
    And specs/014-reviews-backend/spec.md references review_rating_between_1_and_5
    And list_venue_reviews filters directly by booking__venue_id=venue_id.

Scenario: 5. Financial report rejects impossible calendar date "2026-02-31"
  Given an authenticated ADMIN user
  When GET /api/v1/billing/admin/financial-report/?from_date=2026-02-31 is called
  Then _parse_iso_date catches ValueError from date.fromisoformat and returns HTTP 422 with error_code "VALIDATION_ERROR".
```

## 7. Out of scope (explicit)
The following items remain **open** and are **NOT** part of T-043 / Hygiene Batch 2:
- **OTP IP-spoofing (T-030)** — rate-limit / `X-Forwarded-For` spoofing hardening.
- **CVE / dependency audit & remediation (T-030)** — package upgrades or new audit runs.
- **CI setup** — GitHub Actions / CI pipeline configuration.
- **Sentry / Phase D** — live `SENTRY_DSN` wiring and Phase D observability rollout.
- **Changing `VenueAdmin.reject_selected_venues`** (`apps/venues/admin.py:59-66`) — intentionally left unchanged (Item 7).
- **Removing `/admin/financial-report` no-slash alias** (`apps/billing/api.py:292-298`) — intentionally left unchanged (Item 8).

## 8. Open questions
- None. All 8 T-043 scope items are bounded and specified; deferred items are explicitly recorded in Section 7.
