# Tasks — M3 Hardening (Coverage, Security, Observability, Release)

| Task ID | Description | Owner | Status |
| :--- | :--- | :--- | :--- |
| **T-029** | Configure `coverage` + `pytest-cov` per Decision 8 (`apps/` + `core/`, `branch=false`, excluding migrations/tests/`config/*`), measure baseline (`94%`, `383` tests), add 3 regression tests in `apps/venues/tests/test_coverage_hardening.py` (`386 passed`, `94%` overall, `3478` stmts / `192` miss), report `core/jalali.py:45,54-55` bug | `orchestrator` | Done |
| **T-029-FIX** | Fix `timezone.utc` `AttributeError` in `core/jalali.py:45,54-55` (`parse_jalali_datetime`, `jalali_slot_window`) using `datetime.timezone.utc`, add 2 regression tests in `apps/venues/tests/test_coverage_hardening.py` | `orchestrator` | Done |
| **T-030** | Security & Privacy Audit (M3): 0 Critical / 0 High findings; add role/IDOR/privacy/admin regression tests in `apps/accounts/tests/test_security_audit_t030.py`; record 6 Medium/Low/Info Open Items | `orchestrator` | Done |
| **T-031** | Observability (M3): `core/observability.py` (`RequestIdMiddleware`, `PiiScrubbingFilter`, `JsonLogFormatter`, `init_sentry`, `scrub_sentry_event`), production JSON logging, env config, operational alerts checklist in `spec.md`, regression tests in `apps/accounts/tests/test_observability_t031.py` | `orchestrator` | Done |
| **T-032** | Release (M3): Phase A–C complete (`frontend/Dockerfile`, `docker-compose.prod.yml`, `.dockerignore`, `.env.example`, Phase C callback/ADR-006/correlation-log & prod-settings tests in `apps/accounts/tests/test_release_t032.py`, host recommendation & release checklists in `spec.md`). Phase D deployment pending owner host approval | `orchestrator` | Done (Phase D pending host approval) |
