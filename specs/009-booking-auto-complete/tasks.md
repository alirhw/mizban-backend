# Tasks 009 - Booking Auto-Complete After Slot End (T-033 / FR-22)
Rules: one owner per task, max ~400 changed lines, tests named up front,
no two parallel tasks edit the same file, migrations for bookings/wallets
are flagged for human review (none expected for T-033).

| ID | Task | Owner | Depends on | Files (max) | Tests | DoD |
|----|------|-------|------------|-------------|-------|-----|
| **T-033-01** | Spec & Plan for booking auto-complete (FR-22) | `requirements-analyst` / `planner` | None | `specs/009-booking-auto-complete/spec.md`, `specs/009-booking-auto-complete/tasks.md` | N/A (spec + Gherkin criteria) | Done (Gate G4 Approved) — Spec follows `000-template` + `001-booking-lock` style; all 10 Gherkin scenarios, EARS REQs, untouched rules, and T-032 Phase D deferral documented. |
| **T-033-02** | Auto-complete service, Celery task & management command | `booking-lock-engineer` | T-033-01 | `apps/bookings/services.py`, `apps/bookings/tasks.py`, `apps/bookings/management/__init__.py`, `apps/bookings/management/commands/__init__.py`, `apps/bookings/management/commands/complete_expired_bookings.py` | Verified by `apps/bookings/tests/test_booking_auto_complete.py` | Done (Gate G4 Approved) — `complete_expired_bookings(now=None) -> int` uses `transaction.atomic()` + `select_for_update(skip_locked=True)` (ARCH-002), aware UTC (ARCH-006), `end_at <= now`, `CONFIRMED` only, max 500 ordered `end_at ASC, id ASC`, `Booking.transition_to(COMPLETED)`, structured non-PII logs; Celery task `bookings.complete_expired_bookings` (`bind=True`, bounded transient retry only); `manage.py complete_expired_bookings` (`--dry-run` non-mutating); zero migrations; <= 400 lines. |
| **T-033-03** | PostgreSQL test suite for booking auto-complete | `test-engineer` | T-033-01, T-033-02 | `apps/bookings/tests/test_booking_auto_complete.py` | 14 tests in `test_booking_auto_complete.py` (`416 passed`, `95%` coverage) | Done (Gate G4 Approved) — All 10 Gherkin scenarios + `skip_locked` concurrency + batch cap + `INITIATED` exclusion + post-completion 409 cancel rejection pass on PostgreSQL 16; 0 failed, 0 skipped. |
| **T-033-04** | Code & Security Review | `code-reviewer` + `security-engineer` | T-033-02, T-033-03 | *(read-only review; 0 code edits)* | `manage.py check`, `pytest --cov`, OpenAPI snapshot diff (0 lines) | Done (Gate G4 Approved) — Code Reviewer: `approve`; Security Engineer: `approve`. |

### Gate T-033 Approval Notes (2026-11-27)
1. **Gate G4 Decision:** Approved by human for commit (`feat(bookings): auto-complete bookings after slot end (T-033)`).
2. **Condition (1) — Lint / Typecheck:** `ruff` and `mypy` are not installed in local `.venv`; run CI lint/typecheck before release/merge.
3. **Condition (2) — Accepted Info Items:** (a) no composite `(status, end_at, id)` index on `Booking` (deferred; migrations out of scope for T-033); (b) Celery task catch-all `except Exception` retry bounded at `max_retries=3`.

## Parallel groups
- **Group A (Spec & Plan):** `T-033-01`
- **Group B (Build & Tests — disjoint owned files):** `T-033-02` (`booking-lock-engineer`: `apps/bookings/{services.py,tasks.py,management/...}`) and `T-033-03` (`test-engineer`: `apps/bookings/tests/test_booking_auto_complete.py` — fail-first tests can be drafted in parallel, final verification runs after `T-033-02` lands)
- **Group C (Independent Verification & Review):** `T-033-04` (`code-reviewer` + `security-engineer`)

## Estimates
| Task | Estimated Diff | Estimated Tokens | Estimated Cost | Estimated Elapsed |
|------|----------------|------------------|----------------|-------------------|
| T-033-01 | ~190 lines (docs) | ~12k | ~$0.06 | ~5 min |
| T-033-02 | ~180–240 lines | ~20k | ~$0.12 | ~10 min |
| T-033-03 | ~260–350 lines | ~22k | ~$0.13 | ~12 min |
| T-033-04 | 0 lines (review) | ~14k | ~$0.08 | ~8 min |
| **Feature Total** | **~440–590 code+test lines (~190 spec)** | **~68k** | **~$0.39** | **~35 min** |
