# Tasks 018 - Hygiene Batch 2 (T-043)
Rules: one owner per task, max ~400 changed lines, tests named up front,
no two parallel tasks edit the same file, only `apps/reviews/` has an index migration (`0002_*`).

| ID | Task | Owner | Depends on | Files (max) | Tests | DoD |
|----|------|-------|------------|-------------|-------|-----|
| **T-043-01** | Spec, Plan & `014` constraint name alignment (Items 5c, 7, 8) | `requirements-analyst` / `planner` | None | `specs/018-hygiene-batch-2/spec.md`, `specs/018-hygiene-batch-2/tasks.md`, `specs/014-reviews-backend/spec.md` | N/A (spec + Gherkin criteria) | Spec follows `000-template`; all 8 T-043 items cited with source packets/tasks; `specs/014-reviews-backend/spec.md:31,82` updated to `review_rating_between_1_and_5`; T-030 OTP IP-spoofing, T-030 CVE/dependency audit, CI setup, and Sentry/Phase D explicitly recorded as open & out of scope. |
| **T-043-02** | Verify & test `TablePinCreateIn`/`TablePinUpdateIn` bounds (Item 1) | `media-engineer` | T-043-01 | `apps/panoramas/schemas.py` *(if needed)*, `apps/panoramas/tests/test_table_pins_api.py` | `apps/panoramas/tests/test_table_pins_api.py` | `TablePinCreateIn` & `TablePinUpdateIn` enforce `StrictInt`, `capacity >= 0` (`ge=0`), and `reservation_fee_toman` `0..9_223_372_036_854_775_807`; isolated 422 tests pass for booleans and out-of-range values. |
| **T-043-03** | Billing `select_related` & explicit `customer_email=""` (Items 2 & 3) | `finance-engineer` | T-043-01 | `apps/billing/services/payment.py` | `apps/billing/tests/test_billing_initiate_and_sandbox.py`, `apps/billing/tests/test_payment_callback.py`, `apps/billing/tests/test_wallet_payment.py` | `handle_payment_callback` and `pay_booking_with_wallet` include `"venue"` and `"venue__owner"` in `Booking` `select_related`; `initiate_payment` sets `customer_email=""` with comment explaining `User` has no `email` field. |
| **T-043-04** | `Review.is_visible` `db_index=True`, `0002_*` migration & `booking__venue_id` check (Item 5) | `platform-engineer` | T-043-01 | `apps/reviews/models.py`, `apps/reviews/migrations/0002_*.py`, `apps/reviews/services.py` *(verify)* | `apps/reviews/tests/test_reviews.py` | `Review.is_visible` has `db_index=True` with generated `0002_*` migration; `list_venue_reviews` uses `booking__venue_id=venue_id`; `makemigrations --check --dry-run` passes with no pending changes. |
| **T-043-05** | 5 isolated T-039 notification tests + `SET_NULL` fallback test (Items 4 & 6a) | `test-engineer` | T-043-03 | `apps/notifications/tests/test_notifications.py` | `apps/notifications/tests/test_notifications.py` | Isolated tests pass for: (1) `handle_payment_callback` notification, (2) idempotent `cancel_booking` replay, (3) `ADMIN` 0 rows, (4) `offset < 0` clamping, (5) mocked 0-SMS assertion, and (6) `SET_NULL` (`booking=None` / `venue=None`) fallback copy. |
| **T-043-06** | `report.py` `ValueError` catch test on `"2026-02-31"` (Item 6b) | `test-engineer` | T-043-01 | `apps/billing/tests/test_admin_financial_report.py` | `apps/billing/tests/test_admin_financial_report.py` | Test passes `"2026-02-31"` (`_ISO_DATE_RE` match -> `date.fromisoformat` `ValueError` -> `422 VALIDATION_ERROR`) and confirms the `except ValueError` branch in `apps/billing/services/report.py:32-35` is covered. |
| **T-043-07** | Review & full verification | `code-reviewer` | T-043-02, T-043-03, T-043-04, T-043-05, T-043-06 | None (read-only verification) | `manage.py check`, `makemigrations --check --dry-run`, `ruff check .`, `mypy .`, `pytest`, `./check-contract.sh` | Code Reviewer approves; all checks and `./check-contract.sh` pass with 0 failures and 0 skipped tests. |

## Parallel groups
- **Group A (Spec & Plan):** `T-043-01`
- **Group B1 (Disjoint Code, Migration & Tests):**
  - `T-043-02` (`media-engineer`: `apps/panoramas/schemas.py`, `apps/panoramas/tests/test_table_pins_api.py`)
  - `T-043-03` (`finance-engineer`: `apps/billing/services/payment.py`)
  - `T-043-04` (`platform-engineer`: `apps/reviews/models.py`, `apps/reviews/migrations/0002_*.py`, `apps/reviews/services.py`)
  - `T-043-06` (`test-engineer`: `apps/billing/tests/test_admin_financial_report.py`)
  *(All 4 tasks in Group B1 touch strictly disjoint files.)*
- **Group B2 (Notification Tests):** `T-043-05` (`test-engineer`: `apps/notifications/tests/test_notifications.py` — runs after `T-043-03` so `handle_payment_callback` `select_related` is in place)
- **Group C (Review & Verification):** `T-043-07`

## Estimates
| Task | Estimated Diff | Estimated Tokens | Estimated Cost | Estimated Elapsed |
|------|----------------|------------------|----------------|-------------------|
| T-043-01 | ~160 lines (docs) | ~8k | ~$0.04 | ~4 min |
| T-043-02 | ~30 lines | ~5k | ~$0.03 | ~3 min |
| T-043-03 | ~10 lines | ~4k | ~$0.02 | ~2 min |
| T-043-04 | ~20 lines + migration | ~5k | ~$0.03 | ~3 min |
| T-043-05 | ~110 lines | ~10k | ~$0.05 | ~6 min |
| T-043-06 | ~20 lines | ~4k | ~$0.02 | ~2 min |
| T-043-07 | 0 lines (review/verify) | ~8k | ~$0.04 | ~5 min |
| **Feature Total** | **~190 code+test lines (~160 docs)** | **~44k** | **~$0.23** | **~25 min** |
