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
- [ ] **T-007 — Session Issuance, Logout/Me & Replace MinimalAuth Bridge**
  - Deferred to next task: issue HttpOnly session cookies on verify, add `/logout/` and `/me/`, remove DEBUG `MinimalAuth` bridge.
