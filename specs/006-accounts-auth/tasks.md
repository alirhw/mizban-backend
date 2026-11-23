# Tasks: Phase PH-02 — Identity & Authentication (WS-IDENTITY)

## Roadmap & Tracking

- [x] **T-005 — Custom User Model (`apps/accounts/models.py`)**
  - Canonical Iranian mobile `phone` (`09xxxxxxxxx`, unique), `UserRole` (`CUSTOMER`, `VENUE_OWNER`, `ADMIN`), unusable password by default.
- [x] **T-006 — OTP Request, Verification & SMS Adapter Interface (TD-006)**
  - `core/exceptions.py`: Added `OtpRateLimitedError` (`OTP_RATE_LIMITED`, 429), `OtpInvalidError` (`OTP_INVALID`, 400), `OtpExpiredError` (`OTP_EXPIRED`, 400).
  - `apps/accounts/sms.py`: `SmsSender` protocol, `ConsoleSmsSender` (`DEBUG=True` stdout only, never logs), `FakeSmsSender`, and `get_sms_sender()` factory (`settings.SMS_SENDER`: `"console"` in dev, `"fake"` in pytest). Provider SMS.ir deferred post-MVP (Decision 4).
  - `apps/accounts/services.py`: `request_otp(phone, *, ip)` and `verify_otp(phone, code)` backed by Redis (`otp:{phone}` SHA-256 hash + attempts with 120s TTL; `otp:rate:phone:{phone}` & `otp:rate:ip:{ip}` 3 req/10m). Single-use, 5-attempt burn, `hmac.compare_digest`, role preservation, zero sensitive logging.
  - `apps/accounts/schemas.py` & `apps/accounts/api.py`: `POST /api/v1/auth/otp/request/` and `POST /api/v1/auth/otp/verify/` (no session cookie yet; `MinimalAuth` untouched).
  - `apps/accounts/tests/test_otp.py`: Comprehensive tests against real PostgreSQL and Redis.
  - Zero DB migrations created.
- [x] **T-007 — Session Issuance, Logout/Me & Replace MinimalAuth Bridge**
  - `config/settings/base.py` & `development.py`: Explicit `SESSION_COOKIE_HTTPONLY = True`, `SESSION_COOKIE_SAMESITE = "Lax"`, `SESSION_COOKIE_SECURE = True` (`False` in `development.py` only).
  - `apps/accounts/auth.py`: Deleted `MinimalAuth` (`X-User-Phone` and `Bearer <phone>` paths completely removed); replaced with `ActiveSessionAuth(SessionAuth)` (`csrf=True`, active-user check).
  - `apps/accounts/services.py` & `api.py` & `schemas.py`: `verify_otp` establishes Django session (`login_session`); added `GET /api/v1/auth/csrf/`, `POST /api/v1/auth/logout/`, and `GET /api/v1/auth/me/` (+ trailing-slash aliases).
  - `core/testing.py`: Added shared session test helper (`authenticate_client`, `login_via_otp`) and migrated all API test suites (`venues`, `panoramas`, `bookings`) off the deleted bridge.
  - `apps/accounts/tests/test_session_auth.py`: Replaced `test_auth_bridge.py` with full session, cookie, role, CSRF, logout, and backdoor-deletion tests.
  - Refreshed `api/openapi.snapshot.json` (cookie security scheme + new endpoints). Zero migrations created.
