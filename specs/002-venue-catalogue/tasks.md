# Tasks 002 — Venue Catalogue & Owner Operations (Task T-009)

| ID | Task | Owner | Depends on | Files | Tests | DoD |
|---|---|---|---|---|---|---|
| T-009-01 | Minimal authenticated identity bridge for Ninja | platform-engineer | None | `apps/accounts/auth.py` | Auth tests | Caller resolved to User |
| T-009-02 | Schemas for public, owner, admin venue APIs | platform-engineer | T-009-01 | `apps/venues/schemas.py` | Schema validation | No phone exposure, explicit fields |
| T-009-03 | Venue service layer & cache invalidation | platform-engineer | T-009-02 | `apps/venues/services.py` | Unit tests | Atomic writes, on_commit invalidation |
| T-009-04 | Ninja router endpoints (public, owner, admin) | platform-engineer | T-009-03 | `apps/venues/api.py`, `apps/venues/admin.py` | API tests | IDOR prevention, role checks |
| T-009-05 | Acceptance & Security test suite | test-engineer | T-009-04 | `apps/venues/tests/test_owner_api.py` | Integration tests | All tests pass |

## Parallel Groups
- Phase 1: Auth bridge + Schemas + Services + Endpoints (T-009-01 .. 04)
- Phase 2: Comprehensive Test Suite (T-009-05)
- Phase 3: Code Review & Security Audit -> Gate Packet
