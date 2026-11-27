# Tasks 012 - Venue Review Workflow, Submission & Rejection Reason (T-036 / FR-33, FR-37, FR-39)
Rules: one owner per task, max ~400 changed lines, tests named up front,
no two parallel tasks edit the same file, migrations for bookings/wallets
are flagged for human review (none for T-036; `apps/venues/migrations/0004_*` is under `platform-engineer`).

> **Note:** `VenueNotSubmittableError` (`error_code="VENUE_NOT_SUBMITTABLE"`, HTTP `409`) already exists in `core/exceptions.py` (lines 204–209), so no `backend-api-engineer` task is required.

| ID | Task | Owner | Depends on | Files (max) | Tests | DoD |
|----|------|-------|------------|-------------|-------|-----|
| **T-036-01** | Spec & Plan for venue review state machine, submit endpoint, and rejection reason (FR-33/FR-37/FR-39) | `requirements-analyst` / `planner` | None | `specs/012-venue-review/spec.md`, `specs/012-venue-review/tasks.md` | N/A (spec + Gherkin criteria) | Spec follows `000-template`; 4-state `VenueReviewStatus`, `0004_*` migration fields, `is_approved` sync (`BR-005`), `/submit` (`409 VENUE_NOT_SUBMITTABLE`), `VenueRejectIn` (`extra="forbid"`, non-blank <= 1000), `/approve`, schema privacy, 8 Gherkin scenarios, and explicit out-of-scope follow-ups (`T-039` notifications, `frontend/` panel, `APPROVED` edit-reset) documented. |
| **T-036-02** | `VenueReviewStatus` model fields & forward migration `0004_*` | `platform-engineer` | T-036-01 | `apps/venues/models.py`, `apps/venues/migrations/0004_*.py` | Verified by `apps/venues/tests/test_venue_review.py` & `apps/venues/tests/test_models.py` | `VenueReviewStatus(TextChoices)` (`DRAFT`, `PENDING_REVIEW`, `APPROVED`, `REJECTED`) added; `Venue` gains `review_status` (default `DRAFT`), `rejection_reason` (`TextField(blank=True, default="")`), and `submitted_for_review_at` (`DateTimeField(null=True, blank=True)`); single clean forward migration `0004_*` generated and applied; <= 60 lines. |
| **T-036-03** | Review schemas, services, API endpoints & admin action sync | `platform-engineer` | T-036-01, T-036-02 | `apps/venues/schemas.py`, `apps/venues/services.py`, `apps/venues/api.py`, `apps/venues/admin.py` | Verified by `apps/venues/tests/test_venue_review.py` & `apps/venues/tests/test_owner_api.py` | `VenueOwnerOut` includes `review_status`, `rejection_reason`, `submitted_for_review_at`; `VenueApprovalOut` includes `review_status`, `rejection_reason: str = ""`; `VenueRejectIn(extra="forbid")` validates stripped non-blank `reason` (1..1000 chars); public schemas unchanged; `submit_venue_for_review` (`DRAFT`/`REJECTED` -> `PENDING_REVIEW`, clears `rejection_reason`, sets `submitted_for_review_at`, `409 VenueNotSubmittableError` from `PENDING_REVIEW`/`APPROVED`), `approve_venue` (`DRAFT`/`PENDING_REVIEW`/`REJECTED` -> `APPROVED`, `is_approved=True`, clears `rejection_reason`), `reject_venue` (`REJECTED`, `is_approved=False`, stores stripped `reason`), all with `select_for_update()` + `transaction.on_commit(invalidate_venue_cache)`; `POST /owner/venues/{venue_id}/submit` & updated `POST /admin/venues/{venue_id}/reject` wired; `admin.py` actions keep `review_status` synced; <= 200 lines. |
| **T-036-04** | PostgreSQL test suite for venue review & update existing `/reject` tests | `test-engineer` | T-036-01, T-036-03 | `apps/venues/tests/test_venue_review.py`, `apps/venues/tests/test_owner_api.py` | `apps/venues/tests/test_venue_review.py`, `apps/venues/tests/test_owner_api.py` | Covers all 8 Gherkin scenarios: `DRAFT` default, `/submit` from `DRAFT` & `REJECTED` (no cross-app preconditions, cache invalidation), `409 VENUE_NOT_SUBMITTABLE` from `PENDING_REVIEW`/`APPROVED`, `/reject` with `VenueRejectIn` + `422` validation (missing body, blank, >1000 chars, extra fields), owner edit of `REJECTED` venue + resubmit clearing `rejection_reason`, `/approve` from `DRAFT`/`PENDING_REVIEW`/`REJECTED` clearing `rejection_reason` + `BR-005` public visibility without leaking review fields, IDOR/auth (`401`, `403`, `404`); existing `/reject` call in `test_owner_api.py` updated with `{"reason": ...}`; 0 failed, 0 skipped on PostgreSQL. |
| **T-036-05** | Review & OpenAPI snapshot update | `code-reviewer` + `security-engineer` *(+ human gate for `api/openapi.snapshot.json`)* | T-036-03, T-036-04 | `api/openapi.snapshot.json` *(protected path — human gate)* | `manage.py check`, `pytest`, `./check-contract.sh` | Code Reviewer & Security Engineer approve; `api/openapi.snapshot.json` updated and `./check-contract.sh` passes cleanly. |

## Parallel groups
- **Group A (Spec & Plan):** `T-036-01`
- **Group B1 (Model & Migration):** `T-036-02` (`platform-engineer`: `apps/venues/models.py`, `apps/venues/migrations/0004_*.py`)
- **Group B2 (Service/API Build & Tests — disjoint owned files):** `T-036-03` (`platform-engineer`: `apps/venues/schemas.py`, `apps/venues/services.py`, `apps/venues/api.py`, `apps/venues/admin.py`) and `T-036-04` (`test-engineer`: `apps/venues/tests/test_venue_review.py`, `apps/venues/tests/test_owner_api.py` — fail-first tests can be drafted in parallel, final verification runs after `T-036-03` lands)
- **Group C (Independent Review & Protected-Path Contract Update):** `T-036-05` (`code-reviewer` + `security-engineer` + human-gated `api/openapi.snapshot.json` update)

## Estimates
| Task | Estimated Diff | Estimated Tokens | Estimated Cost | Estimated Elapsed |
|------|----------------|------------------|----------------|-------------------|
| T-036-01 | ~140 lines (docs) | ~10k | ~$0.05 | ~5 min |
| T-036-02 | ~45 lines + migration | ~6k | ~$0.03 | ~4 min |
| T-036-03 | ~140–180 lines | ~15k | ~$0.08 | ~10 min |
| T-036-04 | ~240–300 lines | ~18k | ~$0.10 | ~10 min |
| T-036-05 | ~60 lines (`openapi.snapshot.json`) + review | ~12k | ~$0.07 | ~6 min |
| **Feature Total** | **~485–585 code+test lines (~140 spec)** | **~61k** | **~$0.33** | **~35 min** |
