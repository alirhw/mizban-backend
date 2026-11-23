# Spec 006 — Accounts, OTP Authentication & Session Staging

**Feature:** 006 — Identity & Authentication (WS-IDENTITY)  
**Status:** Complete (T-005, T-006, T-007 Completed)  
**Governing Rules:** TD-006 (OTP: custom user, 5-digit codes in Redis, 120s expiry, rate limit 3/10m per IP and per phone, HttpOnly session cookies), ARCH-001 (Thin Views)  
**Provider Decision (2026-11-20, Decision 4):** OTP SMS provider is **SMS.ir**; integration is deferred post-MVP (pending domain registration). Domain logic talks strictly to `SmsSender` behind `get_sms_sender()`.

---

## 1. Goal

Provide passwordless mobile OTP authentication for Miz Ban:
1. Custom `User` keyed by canonical Iranian mobile number (`09xxxxxxxxx`, `apps/accounts/models.py`, T-005).
2. Provider-agnostic SMS adapter interface (`apps/accounts/sms.py`) with `ConsoleSmsSender` (local dev) and `FakeSmsSender` (tests).
3. Redis-backed OTP issuance and verification (`apps/accounts/services.py`, T-006) with strict rate limiting, CSPRNG code generation, SHA-256 hash-only storage, timing-safe comparison, and 5-attempt burn protection.
4. Session cookie issuance, `/auth/logout/`, `/auth/me/`, and replacement of `MinimalAuth` across all apps are staged into **Task T-007**.

---

## 2. OTP Contract (Task T-006)

### 2.1 Phone Normalization
- Single normalization boundary: `core.utils.normalize_phone` (accepts `09...`, `+98...`, `0098...`, `98...`).
- Validated against `^09\d{9}$`; malformed phone numbers return HTTP 422 (`VALIDATION_ERROR`).

### 2.2 Redis Key Scheme & TTL
| Key | Value | TTL | Purpose |
|---|---|---|---|
| `otp:{phone}` | JSON `{"code_hash": "<sha256_hex>", "attempts": <int>}` | 120s (`OTP_TTL_SECONDS`) | Active OTP record; replaced immediately on new request; deleted on success or 5th wrong attempt. |
| `otp:rate:phone:{phone}` | Integer counter | 600s (10 min, `nx=True`) | Per-phone rate limit (max 3 requests / 10 min). |
| `otp:rate:ip:{ip}` | Integer counter | 600s (10 min, `nx=True`) | Per-IP rate limit (max 3 requests / 10 min). |

### 2.3 Security & Privacy Invariants
- **CSPRNG:** 5-digit codes generated with `secrets.randbelow(100000)` (`00000`–`99999`), never `random`.
- **Hash-Only Storage:** Plaintext codes are never stored in Redis or the database; only SHA-256 digests are persisted.
- **Timing-Safe Comparison:** `hmac.compare_digest` compares SHA-256 hashes; missing/expired records still execute a dummy `hmac.compare_digest` call.
- **5-Attempt Burn:** Each wrong verify increments `attempts` (`KEEPTTL`); on the 5th failure, `otp:{phone}` is deleted immediately.
- **Single-Use:** Successful verify deletes `otp:{phone}` immediately.
- **Role Preservation:** New users default to `CUSTOMER` with an unusable password (`User.objects.create_user`); existing users (`VENUE_OWNER`, `ADMIN`, `CUSTOMER`) keep their existing role untouched.
- **Zero Sensitive Logging:** OTP codes and full phone numbers never appear in Python logs. `ConsoleSmsSender` prints to stdout only when `DEBUG=True` and never writes to `logging`.
- **Anti-Enumeration:** `POST /api/v1/auth/otp/request/` always returns `200 {"sent": true, "expires_in_seconds": 120}` regardless of whether the phone is registered.

### 2.4 Error Mapping (`core/exceptions.py`)
| Condition | Exception | HTTP Status | `error_code` |
|---|---|---|---|
| Rate limit exceeded (phone or IP $\ge 3$ in 10m) | `OtpRateLimitedError` | 429 | `OTP_RATE_LIMITED` |
| Wrong OTP code | `OtpInvalidError` | 400 | `OTP_INVALID` |
| Missing or expired OTP code | `OtpExpiredError` | 400 | `OTP_EXPIRED` |
| Malformed phone number | `ValidationError` | 422 | `VALIDATION_ERROR` |

### 2.5 API Endpoints (`apps/accounts/api.py`, mounted under `/api/v1/auth`)
- `POST /api/v1/auth/otp/request/` (and `/otp/request`): `OtpRequestIn(phone)` $\to$ `200 OtpRequestOut(sent, expires_in_seconds)`.
- `POST /api/v1/auth/otp/verify/` (and `/otp/verify`): `OtpVerifyIn(phone, code)` $\to$ `200 OtpVerifyOut(id, phone, role)`. **Does not set session cookies in T-006.**

---

## 3. SMS Adapter Interface (`apps/accounts/sms.py`)
- `SmsSender` Protocol: `send_otp(phone: str, code: str) -> None`.
- `ConsoleSmsSender`: prints masked phone + code to stdout only if `DEBUG=True`; silent when `DEBUG=False`.
- `FakeSmsSender`: stores `SentOtpMessage(phone, code)` in memory for tests.
- Factory: `get_sms_sender(sender_name=None)` reads `settings.SMS_SENDER` (`"console"` in development, `"fake"` under pytest).
- Future post-MVP task: plug in `SmsIrSmsSender` via `register_sms_sender("smsir", ...)` without altering `apps/accounts/services.py`.

---

## 4. Session Authentication & CSRF Contract (Task T-007)

### 4.1 Session Issuance & Cookie Attributes (TD-006)
- `POST /api/v1/auth/otp/verify/` calls `django.contrib.auth.login(request, user, backend="django.contrib.auth.backends.ModelBackend")` after OTP verification and returns `OtpVerifyOut(id, phone, role)`.
- Cookie settings (`config/settings/base.py`, `development.py`, `production.py`):
  - `SESSION_COOKIE_HTTPONLY = True`
  - `SESSION_COOKIE_SAMESITE = "Lax"`
  - `SESSION_COOKIE_SECURE = True` in `base.py` and `production.py`; `False` in `development.py` only.
  - Session duration defaults to Django's `SESSION_COOKIE_AGE = 1209600` (14 days, `SESSION_EXPIRE_AT_BROWSER_CLOSE = False`, `SESSION_ENGINE = django.contrib.sessions.backends.db`).
- `ActiveSessionAuth(SessionAuth)` (`apps/accounts/auth.py`) authenticates solely from `request.user` (`is_authenticated and is_active`) with Ninja CSRF enforcement (`csrf=True`). The legacy `MinimalAuth` phone-header (`X-User-Phone`) and `Bearer <phone>` paths are completely deleted.

### 4.2 CSRF Protection & Bootstrap
- All unsafe HTTP methods (`POST`, `PUT`, `PATCH`, `DELETE`) on session-authenticated endpoints enforce CSRF via Ninja `SessionAuth` (`check_csrf`, HTTP 403 on missing/invalid token).
- `GET /api/v1/auth/csrf/` (and `/csrf`) calls `django.middleware.csrf.get_token(request)` so `CsrfViewMiddleware` sets the `csrftoken` cookie and returns `CsrfOut(csrf_token)`.

### 4.3 Session Endpoints (`apps/accounts/api.py`)
- `POST /api/v1/auth/logout/` (and `/logout`, `auth=auth`): flushes the Django session (`django.contrib.auth.logout`) and expires the cookie, returning `200 {"logged_out": true}` (or `401` if unauthenticated).
- `GET /api/v1/auth/me/` (and `/me`, `auth=auth`): returns `200 OtpVerifyOut(id, phone, role)` (or `401` if unauthenticated).

### 4.4 Protected Endpoint Inventory (Migrated to `ActiveSessionAuth`)
- `apps/accounts/api.py`: `POST /api/v1/auth/logout/`, `GET /api/v1/auth/me/`
- `apps/venues/api.py`: `GET/POST /api/v1/venues/owner/venues`, `GET/PUT /api/v1/venues/owner/venues/{venue_id}`, `POST /api/v1/venues/owner/venues/{venue_id}/addons`, `POST /api/v1/venues/admin/venues/{venue_id}/approve`
- `apps/panoramas/api.py`: `POST /api/v1/panoramas/spaces/{space_id}/panoramas`, `GET /api/v1/panoramas/panoramas/{panorama_id}/status`, `GET/POST /api/v1/panoramas/spaces/{space_id}/pins`, `PATCH/DELETE /api/v1/panoramas/pins/{pin_id}`, `GET/POST /api/v1/panoramas/venues/{venue_id}/spaces`, `PATCH/DELETE /api/v1/panoramas/spaces/{space_id}` (and trailing-slash aliases)
- `apps/bookings/api.py`: `POST /api/v1/bookings/initiate/`, `POST /api/v1/bookings/{booking_id}/cancel/`, `GET /api/v1/bookings/{booking_id}/receipt/` (and trailing-slash aliases)
- Public endpoints (`auth=None`) remain unchanged: `/auth/csrf/`, `/auth/otp/request/`, `/auth/otp/verify/`, `/venues/` public catalogue, `/panoramas/` public reads, `/scheduling/`, `/billing/callback/`, `/healthz`.
