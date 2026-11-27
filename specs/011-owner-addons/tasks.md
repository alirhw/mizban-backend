# Tasks 011 - Venue-Owner Design Add-On Management API (T-035 / FR-32)
Rules: one owner per task, max ~400 changed lines, tests named up front,
no two parallel tasks edit the same file, migrations for bookings/wallets
are flagged for human review (none for T-035).

| ID | Task | Owner | Depends on | Files (max) | Tests | DoD |
|----|------|-------|------------|-------------|-------|-----|
| **T-035-01** | Spec & Plan for venue-owner design add-on CRUD API (FR-32) | `requirements-analyst` / `planner` | None | `specs/011-owner-addons/spec.md`, `specs/011-owner-addons/tasks.md` | N/A (spec + Gherkin criteria) | Spec follows `000-template`; EARS REQs, BR-003/BR-15, IDOR scoping, `ADDON_IN_USE` 409, cache invalidation, 9 Gherkin scenarios, and explicit out-of-scope follow-ups (`image` upload, `frontend/` page) documented. |
| **T-035-02** | Add `AddonInUseError` domain exception | `backend-api-engineer` | T-035-01 | `core/exceptions.py` | Verified by `apps/venues/tests/test_owner_addons.py` | `AddonInUseError(DomainError)` added to `core/exceptions.py` with `error_code = "ADDON_IN_USE"`, `status_code = 409`, and clear default message; <= 15 lines. |
| **T-035-03** | Owner add-on schemas, services & API endpoints | `platform-engineer` | T-035-01, T-035-02 | `apps/venues/schemas.py`, `apps/venues/services.py`, `apps/venues/api.py` | Verified by `apps/venues/tests/test_owner_addons.py` | `DesignAddonCreateIn` (`extra="forbid"`, stripped non-empty `title` <= 200, `fee >= 0`, `is_active: bool = True`) and `DesignAddonUpdateIn` (`extra="forbid"`, all 3 fields required); service functions (`list_owner_venue_addons`, `create_owner_venue_addon`, `get_owner_venue_addon`, `update_owner_venue_addon`, `delete_owner_venue_addon`) using `get_owner_venue`, `venue.design_addons` scoping, `transaction.atomic()`, `ProtectedError -> AddonInUseError`, `transaction.on_commit(invalidate_venue_cache)`; 5 endpoints under `/api/v1/venues/owner/venues/{venue_id}/addons/` returning `200`/`201`/`204`; zero migrations; <= 250 lines. |
| **T-035-04** | PostgreSQL test suite for owner add-on management | `test-engineer` | T-035-01, T-035-03 | `apps/venues/tests/test_owner_addons.py` | `apps/venues/tests/test_owner_addons.py` | Covers all 9 Gherkin scenarios: list active+inactive ordered by title, create 201 + cache invalidation, validation 422 (blank/long title, negative fee, extra fields), retrieve 200, update 200 + BR-15 snapshot immutability (existing booking untouched, new booking uses new fee), deactivate hides from public detail, delete 204 + cache invalidation, delete referenced add-on 409 `ADDON_IN_USE` + row untouched, IDOR (403 non-owner/customer, 404 cross-venue `addon_id`, 401 unauthenticated); 0 failed, 0 skipped on PostgreSQL. |
| **T-035-05** | Review & OpenAPI snapshot update | `code-reviewer` + `security-engineer` *(+ human gate for `api/openapi.snapshot.json`)* | T-035-03, T-035-04 | `api/openapi.snapshot.json` *(protected path — human gate)* | `manage.py check`, `pytest`, `./check-contract.sh` | Code Reviewer & Security Engineer approve; `api/openapi.snapshot.json` updated and `./check-contract.sh` passes cleanly. |

## Parallel groups
- **Group A (Spec & Plan):** `T-035-01`
- **Group B1 (Shared Exception Foundation):** `T-035-02` (`backend-api-engineer`: `core/exceptions.py`)
- **Group B2 (Build & Tests — disjoint owned files):** `T-035-03` (`platform-engineer`: `apps/venues/schemas.py`, `apps/venues/services.py`, `apps/venues/api.py`) and `T-035-04` (`test-engineer`: `apps/venues/tests/test_owner_addons.py` — fail-first tests can be drafted in parallel, final verification runs after `T-035-03` lands)
- **Group C (Independent Review & Protected-Path Contract Update):** `T-035-05` (`code-reviewer` + `security-engineer` + human-gated `api/openapi.snapshot.json` update)

## Estimates
| Task | Estimated Diff | Estimated Tokens | Estimated Cost | Estimated Elapsed |
|------|----------------|------------------|----------------|-------------------|
| T-035-01 | ~145 lines (docs) | ~10k | ~$0.05 | ~5 min |
| T-035-02 | ~10 lines | ~4k | ~$0.02 | ~2 min |
| T-035-03 | ~160–220 lines | ~16k | ~$0.09 | ~10 min |
| T-035-04 | ~220–300 lines | ~18k | ~$0.10 | ~10 min |
| T-035-05 | ~80 lines (`openapi.snapshot.json`) + review | ~12k | ~$0.07 | ~6 min |
| **Feature Total** | **~470–610 code+test lines (~145 spec)** | **~60k** | **~$0.33** | **~33 min** |
