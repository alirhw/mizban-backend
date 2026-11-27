# Tasks 015 - Review Moderation: Admin Hide/Show (T-038 / FR-41, BR-13)
Rules: one owner per task, max ~400 changed lines, tests named up front,
no two parallel tasks edit the same file, no migrations/model/caching changes.

| ID | Task | Owner | Depends on | Files (max) | Tests | DoD |
|----|------|-------|------------|-------------|-------|-----|
| **T-038-01** | Spec & Plan for review moderation (FR-41, BR-13) | `requirements-analyst` / `planner` | None | `specs/015-review-moderation/spec.md`, `specs/015-review-moderation/tasks.md` | N/A (spec + Gherkin criteria) | Spec follows `000-template`; hide/show-only (`is_visible`, no `DELETE`), admin-only (`is_staff` or `UserRole.ADMIN`), idempotent 200 no-op, `GET /admin/`, `POST /admin/{review_id}/hide`, `POST /admin/{review_id}/show`, `ReviewAdminOut` (`extra="forbid"`, no PII), zero migrations/model/cache changes, 4 Gherkin scenarios, and explicit out-of-scope follow-ups (`frontend/` admin UI, `apps/reviews/admin.py`) documented. |
| **T-038-02** | Admin moderation schema, services & Ninja endpoints | `platform-engineer` | T-038-01 | `apps/reviews/schemas.py`, `apps/reviews/services.py`, `apps/reviews/api.py` | Verified by `apps/reviews/tests/test_reviews.py` | `ReviewAdminOut(extra="forbid")` exposes `id`, `booking_id`, `venue_id`, `table_number`, `rating`, `text`, `reviewer_name` (first name or `"Customer"`), `created_at`, `is_visible` with zero PII (`BR-13`); `_require_admin` enforces `is_staff` or `UserRole.ADMIN` (`PermissionDenied` -> `403`); `list_admin_reviews` filters by optional `venue_id`/`is_visible` with `_clamp_pagination(limit, offset)` and `select_related("booking__table_pin", "booking__customer")`; `set_review_visibility` raises `Http404` when missing, saves `update_fields=["is_visible"]` only on change, and returns `200` `ReviewAdminOut` idempotently on no-op; `GET /admin/`, `POST /admin/{review_id}/hide`, `POST /admin/{review_id}/show` wired with `auth=auth` and no `DELETE` endpoint; <= 120 lines. |
| **T-038-03** | PostgreSQL tests for admin review moderation | `test-engineer` | T-038-01, T-038-02 | `apps/reviews/tests/test_reviews.py` | `apps/reviews/tests/test_reviews.py` | Covers all 4 Gherkin scenarios: `GET /admin/` filtering (`venue_id`, `is_visible`), pagination clamping (`limit` `1..100`, `offset >= 0`), `ReviewAdminOut` shape & PII exclusion; `POST /admin/{id}/hide` & `/show` toggling `is_visible` without deleting row and reflecting in public `GET /venues/{id}/`; idempotent 200 no-op when already hidden/shown; `401` unauthenticated, `403 FORBIDDEN` for `VENUE_OWNER` (including venue's own owner) and `CUSTOMER` (including author), `404` for missing `review_id`; 0 failed, 0 skipped on PostgreSQL. |
| **T-038-04** | Review & OpenAPI snapshot update | `code-reviewer` + `security-engineer` *(+ human gate for `api/openapi.snapshot.json`)* | T-038-02, T-038-03 | `api/openapi.snapshot.json` *(protected path — human gate)* | `manage.py check`, `pytest`, `./check-contract.sh` | Code Reviewer & Security Engineer approve; `api/openapi.snapshot.json` updated and `./check-contract.sh` passes cleanly. |

## Parallel groups
- **Group A (Spec & Plan):** `T-038-01`
- **Group B (Build & Tests — disjoint owned files):** `T-038-02` (`platform-engineer`: `apps/reviews/schemas.py`, `apps/reviews/services.py`, `apps/reviews/api.py`) and `T-038-03` (`test-engineer`: `apps/reviews/tests/test_reviews.py` — fail-first tests can be drafted in parallel, final verification runs after `T-038-02` lands)
- **Group C (Independent Review & Protected-Path Contract Update):** `T-038-04` (`code-reviewer` + `security-engineer` + human-gated `api/openapi.snapshot.json` update)

## Estimates
| Task | Estimated Diff | Estimated Tokens | Estimated Cost | Estimated Elapsed |
|------|----------------|------------------|----------------|-------------------|
| T-038-01 | ~120 lines (docs) | ~8k | ~$0.04 | ~4 min |
| T-038-02 | ~80–110 lines | ~8k | ~$0.04 | ~6 min |
| T-038-03 | ~130–170 lines | ~10k | ~$0.05 | ~7 min |
| T-038-04 | ~60 lines (`openapi.snapshot.json`) + review | ~10k | ~$0.05 | ~5 min |
| **Feature Total** | **~270–340 code+test lines (~120 spec)** | **~36k** | **~$0.18** | **~22 min** |
