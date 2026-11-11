# Skill: OTP over SMS (TD-006)

## What it teaches
Passwordless login the Miz Ban way: a 5-digit code in Redis with a
120-second life, strict rate limits against SMS bombing, delivery through
SMS.ir's Verify (pattern) API via Celery — and codes that never appear in
logs, responses or tests.

## Steps
1. Issue (`apps/accounts/services.py`): normalise + validate the mobile
   (`^09\d{9}$`), then check rate counters in Redis:
   `otp:rate:{mobile}` and `otp:rate:ip:{ip}` — max **3 sends per 10
   minutes** each. Exceeding either → HTTP 429, error_code
   `OTP_RATE_LIMITED` (standard envelope).
2. Generate the code with a CSPRNG (`secrets`), 5 digits. Store as
   `otp:code:{mobile}` in Redis with **120s TTL**, plus an attempt counter
   `otp:attempts:{mobile}` (max 5 verifies per code).
3. Dispatch `send_sms_task` (Celery) — never send inline in the request.
   Provider call (SMS.ir Verify API):
   `POST https://api.sms.ir/v1/send/verify` with header
   `X-API-KEY: <SMSIR_API_KEY>` and JSON body
   `{"mobile": ..., "templateId": <SMSIR_OTP_TEMPLATE_ID>,
     "parameters": [{"name": "CODE", "value": "<code>"}]}`
   (parameter name configurable via `SMSIR_OTP_PARAM_NAME`, default CODE).
   Success = HTTP 200 and response `status == 1`; anything else → provider
   error → envelope `SMS_SEND_FAILED` (502). Timeout 5s; Celery retries ×3
   with exponential backoff.
4. All provider config comes from environment variables on the human's
   machine (`.env`): `SMS_PROVIDER`, `SMSIR_API_KEY`,
   `SMSIR_OTP_TEMPLATE_ID`. A console provider exists for local dev only
   (`SMS_PROVIDER=console`) and is never the production default.
5. Verify: fetch `otp:code:{mobile}`; missing/expired → 400 `OTP_INVALID`
   (same error for wrong code — no oracle about which numbers exist).
   Compare in constant time (`secrets.compare_digest`); count attempts;
   on success DELETE the code (single-use), get-or-create the user by
   phone (role defaults to CUSTOMER — never from client input), and log in
   with Django's session (`auth.login`).
6. Sessions ride on Django's session cookies (HttpOnly / Secure in prod /
   SameSite=Lax). No tokens in localStorage, no JWT side-channel.

## Example
```python
# issue — shape only; real code lives in apps/accounts/services.py
def issue_otp(mobile: str, ip: str) -> None:
    if cache.get(f"otp:rate:{mobile}", 0) >= 3 or cache.get(f"otp:rate:ip:{ip}", 0) >= 3:
        raise OtpRateLimitedError(...)
    code = f"{secrets.randbelow(100000):05d}"
    cache.set(f"otp:code:{mobile}", code, timeout=120)
    cache.incr(...)  # rate counters with 600s windows
    send_sms_task.delay(mobile, code)   # code travels only to the provider
    # NEVER: logger.info("otp %s for %s", code, mobile)
```

## Common mistakes
- Logging the code "temporarily for debugging" — this is the classic
  Miz Ban never-bend violation; the dev console provider is the debug path.
- Rate limit only per mobile (attackers rotate numbers and burn the SMS
  budget) or only per IP (one shared NAT locks out a whole office).
- Storing codes in the database (slower, persists secrets at rest) —
  Redis with TTL is the design (TD-006).
- Different error messages for "unknown number" vs "wrong code".
- Sending synchronously in the request (a slow SMS panel then hangs
  logins; Celery exists for this).
- Letting the verify endpoint create users with a client-supplied role.
