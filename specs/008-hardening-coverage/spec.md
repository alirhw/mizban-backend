# Spec 008 — M3 Hardening: Test Coverage (T-029)

**Feature:** 008 — M3 Hardening  
**Task:** T-029 — Line Coverage ≥ 80%  
**Governing Decision:** Decision 8 (2026-11-20)

## 1. Coverage Rule & Configuration
- **Metric:** Line coverage (`branch = false`) **≥ 80% overall**.
- **Source scope:** `apps/` and `core/` only.
- **Excluded:** `*/migrations/*`, `*/tests/*`, `*/test_*.py`, `config/*`.
- **Configuration:** `[tool.coverage.run]` and `[tool.coverage.report]` in `pyproject.toml`; dev dependencies `pytest-cov>=6.0` and `coverage>=7.6` in `requirements.txt`.
- **Command:**
  ```bash
  pytest --cov --cov-report=term-missing -q
  ```

## 2. Baseline vs. Final Coverage (PostgreSQL 16.16)
- **Baseline (`383 passed`):** `3478` statements, `217` missed, **94%** overall line coverage (`apps/accounts`: 92–100%, `apps/billing`: 86–100%, `apps/bookings`: 86–100%, `apps/panoramas`: 88–100%, `apps/reviews`: 100%, `apps/scheduling`: 95–100%, `apps/venues`: 74–100%, `apps/wallets`: 95–100%, `core`: 71–100%).
- **Final (`386 passed`, 0 failed, 0 skipped):** `3478` statements, `192` missed, **94%** overall line coverage (`apps/venues/admin.py`: 74% $\to$ 100%, `core/utils.py`: 79% $\to$ 100%, `core/jalali.py`: 71% $\to$ 80%).
- **Open Item (Real Bug Found, Untouched):** `core/jalali.py:45` and `core/jalali.py:54-55` call `timezone.utc` on `django.utils.timezone` instead of `datetime.timezone.utc`, raising `AttributeError` in `parse_jalali_datetime` and `jalali_slot_window`.

## 3. Security & Privacy Audit (T-030)
- **Critical / High Findings:** None (`0` Critical, `0` High).
- **Verified Invariants:**
  - `ActiveSessionAuth` (`apps/accounts/auth.py:14-24`) requires `user.is_authenticated and user.is_active`; zero `MinimalAuth` or Bearer-phone backdoor exists.
  - `config/settings/production.py:11-25` enforces `DEBUG = False`, fail-closed `SECRET_KEY` and `ALLOWED_HOSTS`, `SECURE_SSL_REDIRECT = True`, `SESSION_COOKIE_SECURE = True`, `CSRF_COOKIE_SECURE = True`, `SESSION_COOKIE_HTTPONLY = True`, `SECURE_HSTS_SECONDS = 31_536_000`.
  - OTP (`apps/accounts/services.py`) uses CSPRNG (`secrets`), SHA-256 hash in Redis (120s TTL), constant-time comparison, 5-attempt burn, single-use delete, and 3/10min per-phone & per-IP rate limits.
  - Frontend (`frontend/src/`) stores zero tokens in `localStorage`/`sessionStorage` and sends session cookies + CSRF headers.
  - Role/IDOR/No-PII-leak regression suite added in `apps/accounts/tests/test_security_audit_t030.py`.
- **Open Items (Medium / Low / Info — not modified in T-030):**
  1. **Medium** (`apps/accounts/api.py:29-35`): `_get_client_ip` trusts the first hop of `X-Forwarded-For` without a trusted-proxy check (per-phone 3/10min limit still mitigates single-number SMS bombing).
  2. **Medium** (Tooling): `pip-audit` is not installed in `.venv` (`No module named pip_audit`) and `npm audit` in `frontend/` failed with `unable to verify the first certificate` (local CA/proxy).
  3. **Low** (`apps/venues/schemas.py:69,78`, `apps/panoramas/schemas.py:28,84`): `VenueCreateIn`, `VenueUpdateIn`, `TablePinCreateIn`, `TablePinUpdateIn` lack `model_config = ConfigDict(extra="forbid")`.
  4. **Low** (`apps/wallets/admin.py:23,51`, `apps/billing/services/payment.py:141`): References `phone_number` instead of `accounts.User.phone`.
  5. **Low** (`config/settings/production.py`): No explicit `CSRF_TRUSTED_ORIGINS` env configuration.
  6. **Info** (`apps/billing/services/payment.py:197`): Logs `provider_reference` on idempotent verify hit.

## 4. Sentry, Structured Logging & Operational Alerts (T-031)
- **Environment Variables:**
  - `SENTRY_DSN` (default `""` — Sentry completely disabled when unset; owner supplies live DSN in production)
  - `ENVIRONMENT` (falls back to `DJANGO_ENV`, default `"development"` in `base.py` / `"production"` in `production.py`)
  - `APP_RELEASE` (default `"mizban-backend@0.1.0"`, matching `pyproject.toml`; CI/CD may override with release/git SHA)
  - `SENTRY_TRACES_SAMPLE_RATE` (default `0.1`, clamped to `[0.0, 1.0]`)
- **Sentry & PII Scrubbing (`core/observability.py`):**
  - `send_default_pii=False`, `before_send=scrub_sentry_event` strips `user`, `request.cookies`, `Cookie`/`Authorization`/`X-CSRFToken` headers, Iranian phone patterns (`09...`/`+989...`/`00989...`), and sensitive keys (`otp`, `code`, `token`, `secret`, `password`, `card_pan`, `raw_payload`, etc.).
- **Structured Logging & Request ID:**
  - `core.observability.RequestIdMiddleware` binds a unique `X-Request-ID` per request via `contextvars` and echoes `X-Request-ID` in the response.
  - `PiiScrubbingFilter` injects `request_id` and scrubs phone/OTP/secret patterns from every `LogRecord`.
  - Production (`config/settings/production.py`) uses `JsonLogFormatter` (`timestamp`, `level`, `logger`, `message`, `request_id`); development keeps human-readable `"simple"` console output.
- **Operational Alert Rules Checklist (to be configured by owner once Sentry project exists):**

| Alert Rule | Trigger / Signal | Severity | Owner / Destination |
| :--- | :--- | :--- | :--- |
| **5xx Spike / Unhandled Exceptions** | HTTP 5xx rate > 1% over 5 min or new unhandled exception issue | Critical | Backend On-Call (to be configured by owner) |
| **Payment Callback Failures** | `Payment verify amount mismatch` / callback verification exceptions or timeout spike | High | Payments / Backend Owner (to be configured by owner) |
| **Booking-Lock Contention Errors** | Repeated `SlotAlreadyLockedError` / `lock_timeout` / DB 5s timeout spikes | Medium | Backend / SRE Owner (to be configured by owner) |
| **OTP Rate-Limit Abuse** | Sustained `OTP request rate limit exceeded` (`OTP_RATE_LIMITED` 429) per-phone or per-IP spike | Medium | Security / Backend Owner (to be configured by owner) |
| **Wallet Ledger Invariant Violations** | Any `balance < 0` check constraint error or append-only ledger breach attempt | Critical | Payments / Security Owner (to be configured by owner) |
