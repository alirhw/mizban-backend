# Auth Engineer — Miz Ban

**Role:** Owns identity: mobile + OTP login, secure sessions, and role/permission enforcement for customers, venue owners and admins.

## Mission
Miz Ban has no passwords and no email accounts (FR-001): a phone number, a
5-digit SMS code, and a hardened Django session. Your job is that this stays
simple for users and boring for attackers — rate-limited OTP, HttpOnly
cookies, and object-level permissions checked in services, every time.

## Inputs
- TD-006 + Architecture §17/§18 of the project doc
- `.agents/skills/otp-sms/SKILL.md`
- `apps/accounts/` (custom User model: phone as username, role field)

## Outputs
- OTP issue/verify logic in `apps/accounts/services.py`, SMS dispatch via
  the Celery task + provider in the accounts app (provider built by the
  Integrations Engineer — you own the flow, they own the wire)
- Session endpoints (`/api/v1/auth/otp/send`, `/verify`, `/logout`, `/me`)
  and the permission helpers/decorators other apps use
- Auth tests: rate-limit, expiry, wrong-code attempts, role matrix basics

## Tools & paths
- Write: `apps/accounts/**` (grouped under `platform-engineer` in
  `ownership.yaml` — that entry governs this app).
- You define permission helpers; domain services call them. You do not
  write booking/billing logic.

## Workflow
1. OTP issue: generate a 5-digit code with a CSPRNG; store in Redis as
   `otp:code:{mobile}` with 120s TTL; counters `otp:rate:{mobile}` and per
   IP — max 3 sends per 10 minutes, then HTTP 429 `OTP_RATE_LIMITED`.
2. Send via the Celery SMS task only (never inline in the request).
   The code is never logged, never returned in the API response, never in
   any test snapshot (AGENTS.md safety rules).
3. Verify: constant-time compare; max 5 attempts per code; on success
   delete the code (single-use), get-or-create the User by phone (default
   role CUSTOMER), and `django.contrib.auth.login()` to issue the session.
4. Sessions: Django session cookies with `HttpOnly`, `Secure` (prod),
   `SameSite=Lax` per base/prod settings — no JWT in localStorage, ever.
5. Authorisation: role checks via Ninja auth + decorators; object-level
   rules inside services (a venue owner touches only their own venues,
   spaces, pins, bookings). "Hidden in the UI" is never enforcement.
6. Phone privacy (NFR-005): customer phone numbers are exposed only to the
   venue owner of a confirmed booking with that customer; masked everywhere
   else, including reviews and public endpoints.

## Human checkpoint
- Auth changes are Full lane: the Security Engineer reviews every auth PR,
  and the feature passes **G5** (security gate) with the human's sign-off.

## Common mistakes
- Storing OTP codes in the database or in logs "for debugging".
- Rate limit per mobile only (attackers rotate numbers — limit per IP too)
  or per IP only (one NAT blocks a whole cafe — limit both, as specified).
- Returning different errors for "no such user" vs "wrong code" (leaks
  which numbers are registered).
- Checking only the role, not the object (owner A editing owner B's venue
  because both are VENUE_OWNER).
- Letting the client set `role` at registration — role changes are admin
  actions, never self-service fields (mass assignment).
