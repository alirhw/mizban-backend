# Tasks 014 - Reviews Backend: Submit & Public/Customer Reads (T-037 / FR-24, FR-25, BR-09, BR-13)
Rules: one owner per task, max ~400 changed lines, tests named up front,
no two parallel tasks edit the same file, migrations for bookings/wallets
are flagged for human review (none for T-037; `apps/reviews/migrations/0001_initial.py` is under `platform-engineer`).

> **Note:** `ReviewNotAllowedError` (`403 REVIEW_NOT_ALLOWED`), `ReviewNotEligibleError` (`409 REVIEW_NOT_ELIGIBLE`), and `ReviewAlreadyExistsError` (`409 REVIEW_ALREADY_EXISTS`) already exist in `core/exceptions.py` (lines 212–234), and `reviews_router` is already mounted at `/reviews` in `config/api.py` (line 76), so no `backend-api-engineer` task is required.

| ID | Task | Owner | Depends on | Files (max) | Tests | DoD |
|----|------|-------|------------|-------------|-------|-----|
| **T-037-01** | Spec & Plan for reviews backend (FR-24/FR-25, BR-09/BR-13) | `requirements-analyst` / `planner` | None | `specs/014-reviews-backend/spec.md`, `specs/014-reviews-backend/tasks.md` | N/A (spec + Gherkin criteria) | Spec follows `000-template`; G1 decided values explicitly labeled as PROJECT decisions (NOT SRS facts); `Review` model + `0001_initial.py`, `BR-09` `select_for_update()` eligibility, read-time visible-only `average_rating`, 4 endpoints under `/api/v1/reviews`, 7 Gherkin scenarios, and explicit out-of-scope follow-ups (`T-038` moderation, venue schema enrichment, customer edit/delete, `frontend/` UI) documented. |
| **T-037-02** | `Review` model & initial migration `0001_initial.py` | `platform-engineer` | T-037-01 | `apps/reviews/models.py`, `apps/reviews/migrations/0001_initial.py` | Verified by `apps/reviews/tests/test_reviews.py` | `Review` (`booking` FK CASCADE `related_name="reviews"`, `rating: IntegerField`, `text: TextField`, `is_visible=True`, `created_at`), `ordering=["-created_at"]`, `UniqueConstraint(fields=["booking"], name="unique_review_per_booking")`, `CheckConstraint(rating__gte=1, rating__lte=5)` added without duplicate `venue`/`table_pin` FKs; clean `0001_initial.py` generated and applied; <= 70 lines. |
| **T-037-03** | Review schemas, services & Ninja endpoints | `platform-engineer` | T-037-01, T-037-02 | `apps/reviews/schemas.py`, `apps/reviews/services.py`, `apps/reviews/api.py` | Verified by `apps/reviews/tests/test_reviews.py` | `ReviewCreateIn(extra="forbid")` validates `StrictInt` 1–5 and stripped non-blank `text` <= 1000; `ReviewPublicOut` exposes `id`, `rating`, `text`, `reviewer_name` (first name or `"Customer"`), `table_number`, `created_at` with zero PII and no `booking_id`/`is_visible` (`BR-13`/`NFR-28`); `ReviewMineOut(ReviewPublicOut)` adds `booking_id` and `is_visible`; `ReviewListOut` returns `average_rating` (1 decimal, `null` when 0 visible), `review_count`, `reviews: list[ReviewPublicOut]`; `limit=20` clamped `1..100` and `offset=0` clamped `>= 0` in `services.py`; non-CUSTOMER role raises `PermissionDenied` (`403 FORBIDDEN`); `create_review` locks `Booking` via `select_for_update()` inside `transaction.atomic()` enforcing `404`/`403 REVIEW_NOT_ALLOWED`/`409 REVIEW_NOT_ELIGIBLE`/`409 REVIEW_ALREADY_EXISTS`; `POST /` (201), `GET /venues/{venue_id}/` (200/404), `GET /tables/{table_pin_id}/` (200/404), `GET /my/` (200/403) wired; <= 260 lines. |
| **T-037-04** | PostgreSQL test suite for reviews backend | `test-engineer` | T-037-01, T-037-03 | `apps/reviews/tests/test_reviews.py` | `apps/reviews/tests/test_reviews.py` | Covers all 7 Gherkin scenarios + DB constraints: `POST /` happy path (201, stripped text), `409 REVIEW_NOT_ELIGIBLE` (non-COMPLETED & future `end_at`), `409 REVIEW_ALREADY_EXISTS`, `401`/`403 FORBIDDEN` (non-CUSTOMER)/`403 REVIEW_NOT_ALLOWED` (wrong customer)/`404`, G1 `422` validation (`bool`/`float`/`str`/0/6 rating, blank/>1000 text, extra field), public `/venues/{id}/` & `/tables/{id}/` pagination (`limit`/`offset` clamping), visible-only `average_rating` (1 decimal & `null`), `reviewer_name` (`"Customer"` fallback) & no `booking_id`/`is_visible`/PII, `404` missing venue/table, and `/my/` including hidden reviews; 0 failed, 0 skipped on PostgreSQL. |
| **T-037-05** | Review & OpenAPI snapshot update | `code-reviewer` + `security-engineer` *(+ human gate for `api/openapi.snapshot.json`)* | T-037-03, T-037-04 | `api/openapi.snapshot.json` *(protected path — human gate)* | `manage.py check`, `pytest`, `./check-contract.sh` | Code Reviewer & Security Engineer approve; `api/openapi.snapshot.json` updated and `./check-contract.sh` passes cleanly. |

## Parallel groups
- **Group A (Spec & Plan):** `T-037-01`
- **Group B1 (Model & Migration):** `T-037-02` (`platform-engineer`: `apps/reviews/models.py`, `apps/reviews/migrations/0001_initial.py`)
- **Group B2 (Service/API Build & Tests — disjoint owned files):** `T-037-03` (`platform-engineer`: `apps/reviews/schemas.py`, `apps/reviews/services.py`, `apps/reviews/api.py`) and `T-037-04` (`test-engineer`: `apps/reviews/tests/test_reviews.py` — fail-first tests can be drafted in parallel, final verification runs after `T-037-03` lands)
- **Group C (Independent Review & Protected-Path Contract Update):** `T-037-05` (`code-reviewer` + `security-engineer` + human-gated `api/openapi.snapshot.json` update)

## Estimates
| Task | Estimated Diff | Estimated Tokens | Estimated Cost | Estimated Elapsed |
|------|----------------|------------------|----------------|-------------------|
| T-037-01 | ~140 lines (docs) | ~10k | ~$0.05 | ~5 min |
| T-037-02 | ~50 lines + migration | ~6k | ~$0.03 | ~4 min |
| T-037-03 | ~180–230 lines | ~16k | ~$0.08 | ~10 min |
| T-037-04 | ~260–320 lines | ~18k | ~$0.10 | ~10 min |
| T-037-05 | ~80 lines (`openapi.snapshot.json`) + review | ~12k | ~$0.07 | ~6 min |
| **Feature Total** | **~570–680 code+test lines (~140 spec)** | **~62k** | **~$0.33** | **~35 min** |
