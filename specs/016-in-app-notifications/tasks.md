# Tasks 016 - In-App Notifications (T-039 / FR-36, BR-10, BR-16)
Rules: one owner per task, max ~400 changed lines, tests named up front,
no two parallel tasks edit the same file, ownership follows `ownership.yaml` strictly.

| ID | Task | Owner | Depends on | Files (max) | Tests | DoD |
|----|------|-------|------------|-------------|-------|-----|
| **T-039-01** | Spec & Plan for in-app notifications (FR-36, BR-10, BR-16) | `requirements-analyst` / `planner` | None | `specs/016-in-app-notifications/spec.md`, `specs/016-in-app-notifications/tasks.md` | N/A (spec + Gherkin criteria) | Spec follows `000-template`; G1 project decisions explicitly labeled as **PROJECT decisions, NOT SRS facts**; 4 types, `VENUE_OWNER`-only recipient matrix, nullable `SET_NULL` FKs (`booking`, `venue`), pagination `50`/`100`, read-time Persian copy without PII, no `DELETE` endpoint / no purge job in v1, synchronous same-transaction triggers, `BR-10`, `BR-16`, 4 Gherkin scenarios, and explicit out-of-scope follow-ups (`frontend/` panels, retention/purge job) documented. |
| **T-039-02** | `apps/notifications` model, migration, Persian renderer, schemas, services & Ninja router | `notifications-engineer` | T-039-01 | `apps/notifications/__init__.py`, `apps/notifications/apps.py`, `apps/notifications/models.py`, `apps/notifications/migrations/0001_initial.py`, `apps/notifications/schemas.py`, `apps/notifications/services.py`, `apps/notifications/api.py` *(note: `"apps.notifications"` is already registered in `config/settings/base.py` `INSTALLED_APPS`)* | Verified by `apps/notifications/tests/test_notifications.py` | `Notification` model with 4 `NotificationType` choices, `recipient` (`CASCADE`), `booking` & `venue` (`SET_NULL`, nullable), `is_read` (default `False`), `created_at` (no `read_at` field), `Meta.ordering = ["-created_at"]`, and index `["recipient", "is_read", "-created_at"]`; `0001_initial.py` generated cleanly; `create_notification(*, recipient, type, booking=None, venue=None)`, `list_my_notifications` (default 50, max 100, deterministic `-created_at, -id` tie-breaker), `unread_count`, `mark_as_read` (404/403/200 idempotent), `mark_all_as_read`, and read-time Persian copy renderer (no `phone`/`email`) implemented in `services.py`; `NotificationOut(extra="forbid")` (`id`, `type`, `booking_id`, `venue_id`, `title`, `body`, `is_read`, `created_at`), `UnreadCountOut`, `MarkAllReadOut` (`marked: int`) in `schemas.py`; `GET /`, `GET /unread-count`, `POST /{notification_id}/read`, `POST /read-all` (no `DELETE`) in `api.py` with `auth=auth`; zero SMS/email calls (`BR-10`); <= 300 lines. |
| **T-039-03** | Mount `/notifications` router in `config/api.py` | `backend-api-engineer` | T-039-02 | `config/api.py` | Verified by `apps/notifications/tests/test_notifications.py` | `apps.notifications.api.router` mounted at `"/notifications"` in `config/api.py` (`/api/v1/notifications`); `python manage.py check` passes; <= 10 lines. |
| **T-039-04** | Wire `BOOKING_CONFIRMED` notification in `apps/billing/services/payment.py` | `finance-engineer` | T-039-02 | `apps/billing/services/payment.py` | Verified by `apps/notifications/tests/test_notifications.py` | `create_notification` called synchronously inside `transaction.atomic()` on transition to `BookingStatus.CONFIRMED` in both `handle_payment_callback` and `pay_booking_with_wallet` (`recipient=booking.venue.owner`, `type=BOOKING_CONFIRMED`, `booking=booking`); no duplicate row on idempotent replay; <= 30 lines. |
| **T-039-05** | Wire `BOOKING_CANCELLED` notification in `apps/bookings/services.py` | `booking-lock-engineer` | T-039-02 | `apps/bookings/services.py` | Verified by `apps/notifications/tests/test_notifications.py` | `create_notification` called synchronously inside `transaction.atomic()` in `cancel_booking` on transition to `BookingStatus.CANCELLED` (Case (a) `CONFIRMED -> CANCELLED` and Case (c) `PENDING_PAYMENT -> CANCELLED`; never on Case (d) idempotent replay); `recipient=locked_booking.venue.owner`, `type=BOOKING_CANCELLED`, `booking=locked_booking`; <= 25 lines. |
| **T-039-06** | Wire `VENUE_APPROVED` & `VENUE_REJECTED` notifications in `apps/venues/services.py` | `platform-engineer` | T-039-02 | `apps/venues/services.py` | Verified by `apps/notifications/tests/test_notifications.py` | `create_notification` called synchronously inside `transaction.atomic()` in `approve_venue` (`VENUE_APPROVED`, `venue=venue`, `booking=None`) and `reject_venue` (`VENUE_REJECTED`, `venue=venue`, `booking=None`) with `recipient=venue.owner`; <= 25 lines. |
| **T-039-07** | PostgreSQL tests for notifications, triggers, BR-16 isolation & BR-10 | `test-engineer` | T-039-02, T-039-03, T-039-04, T-039-05, T-039-06 | `apps/notifications/tests/__init__.py`, `apps/notifications/tests/test_notifications.py` | `apps/notifications/tests/test_notifications.py` | Covers all 4 Gherkin scenarios: `BOOKING_CONFIRMED` (callback + wallet), `BOOKING_CANCELLED` (incl. no duplicate on idempotent cancel), `VENUE_APPROVED`, `VENUE_REJECTED`; 0 rows for `CUSTOMER`/`ADMIN`; 0 SMS/email calls (`BR-10`); `GET /`, pagination clamping (`50`/`100`), Persian `title`/`body` without PII, `GET /unread-count`, `POST /{id}/read` (200 + idempotent 200), `POST /read-all`; `401` unauth, `403 FORBIDDEN` cross-user (`BR-16`), `404` missing, rollback atomicity, and `SET_NULL` fallback rendering; 0 failed, 0 skipped on PostgreSQL; <= 280 lines. |
| **T-039-08** | Review & OpenAPI snapshot update | `code-reviewer` + `security-engineer` *(+ human gate for `api/openapi.snapshot.json`)* | T-039-03, T-039-04, T-039-05, T-039-06, T-039-07 | `api/openapi.snapshot.json` *(protected path — human gate)* | `manage.py check`, `pytest`, `./check-contract.sh` | Code Reviewer & Security Engineer approve; `api/openapi.snapshot.json` updated and `./check-contract.sh` passes cleanly. |

## Parallel groups
- **Group A (Spec & Plan):** `T-039-01`
- **Group B1 (Core App):** `T-039-02` (`notifications-engineer`)
- **Group B2 (Router Mount, Trigger Wiring & Tests — disjoint owned files, all depend on `T-039-02`):**
  - `T-039-03` (`backend-api-engineer`: `config/api.py`)
  - `T-039-04` (`finance-engineer`: `apps/billing/services/payment.py`)
  - `T-039-05` (`booking-lock-engineer`: `apps/bookings/services.py`)
  - `T-039-06` (`platform-engineer`: `apps/venues/services.py`)
  - `T-039-07` (`test-engineer`: `apps/notifications/tests/*` — drafted in parallel, final verification run after `T-039-03..06` land)
- **Group C (Independent Review & Protected-Path Contract Update):** `T-039-08` (`code-reviewer` + `security-engineer` + human-gated `api/openapi.snapshot.json` update)

## Estimates
| Task | Estimated Diff | Estimated Tokens | Estimated Cost | Estimated Elapsed |
|------|----------------|------------------|----------------|-------------------|
| T-039-01 | ~160 lines (docs) | ~8k | ~$0.04 | ~4 min |
| T-039-02 | ~250–300 lines | ~14k | ~$0.07 | ~10 min |
| T-039-03 | ~5 lines | ~2k | ~$0.01 | ~1 min |
| T-039-04 | ~20–30 lines | ~4k | ~$0.02 | ~3 min |
| T-039-05 | ~15–25 lines | ~4k | ~$0.02 | ~3 min |
| T-039-06 | ~15–25 lines | ~4k | ~$0.02 | ~3 min |
| T-039-07 | ~220–280 lines | ~12k | ~$0.06 | ~10 min |
| T-039-08 | ~80 lines (`openapi.snapshot.json`) + review | ~10k | ~$0.05 | ~5 min |
| **Feature Total** | **~605–745 code+test lines (~160 spec)** | **~58k** | **~$0.29** | **~39 min** |
