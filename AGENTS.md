# AGENTS.md - read this first, every task

Project: **Miz Ban** - a two-sided marketplace where customers reserve a specific
cafe/restaurant table by exploring 360-degree panorama photos (Pannellum pins),
and venue owners manage spaces, tables and subscriptions. Backend: Django 5.2 +
Django Ninja modular monolith. Frontend (Next.js) is a separate later phase.

## Commands
- Run everything (Docker): `docker compose up --build`
- Run locally: `python manage.py runserver` (dev settings are the default)
- Migrate: `python manage.py migrate` - generate: `python manage.py makemigrations`
- Sanity: `python manage.py check`
- Test: `pytest` - Lint: `ruff check .` - Types: `mypy .`
- Contract: `./check-contract.sh` (live OpenAPI must match `api/openapi.snapshot.json`)
- API docs: http://127.0.0.1:8000/api/v1/docs - Health: http://127.0.0.1:8000/api/v1/healthz

## Architecture in three lines
- Modular monolith: 8 domain apps under `apps/` (accounts, venues, panoramas,
  scheduling, bookings, billing, wallets, reviews); imports flow one way, toward
  the foundations - `accounts` imports nothing from other apps, `core/` imports nothing.
- Business logic lives in each app's `services.py`; Ninja views only authenticate,
  validate schemas and call services (never raw ORM writes, never the gateway).
- Cross-cutting helpers live in `core/` (exceptions + error envelope, Jalali, pagination).

## Rules that never bend (Architecture Spec section 29 guardrails)
1. ARCH-001: No Ninja view may create bookings or call the payment gateway directly;
   every booking/payment flow goes through `services.py`.
2. ARCH-002: No raw SQL and no capacity-affecting write outside `transaction.atomic()`
   with `select_for_update()`. The booking lock is a DB-level, 10-minute, time-bounded lock.
3. ARCH-003: No heavy image processing in the request/response cycle; 360-degree
   conversion is a Celery task (Pillow -> WebP <= 4096x2048 + 512x256 thumbnail).
4. ARCH-004: Slot availability and lock state are NEVER cached. PostgreSQL is the
   only authority on what is free or occupied.
5. ARCH-005: The online gateway is charged ONLY the table reservation fee (platform
   share). Design add-on costs are printed on the receipt as "payable in person".
6. ARCH-006: No Jalali or localised time is ever stored. All timestamps are UTC
   (`timezone.now()`); Jalali exists only at presentation, via `core/jalali.py`.

## Business rules (Product Definition section 6)
- BR-001: A slot is exactly 90 minutes, followed by exactly 30 minutes of cleaning
  buffer before the next slot on the same table.
- BR-002: A slot can only be booked if it starts at least 24 hours from now.
- BR-003: Online payment = table fee only (100% platform). Design items are listed
  on the receipt and paid to the cafe in person.
- BR-004: Cancellation only up to 36 hours before the slot; the refund goes ONLY to
  the in-app wallet and can never be withdrawn as cash.
- BR-005: A venue is publicly visible/bookable only when admin-approved AND its
  subscription is active. (BR-006: existing bookings survive subscription expiry.)
- Money is always integer Toman. Never floats for money, anywhere.
- Wallets: one-sided audited ledger; balance can never go negative
  (DB CheckConstraint + `select_for_update()`, TD-005).

## Safety and honesty rules
- Never log OTP codes, phone numbers in bulk, tokens or any secret. Never read `.env`.
- Tests are written fail-first and must be able to fail; never weaken, skip or delete
  a test to make CI green. Concurrency tests only count against PostgreSQL.
- A migration touching `apps/bookings` or `apps/wallets` needs human review before
  it is applied anywhere shared.
- One task = at most ~400 changed lines. If the work is bigger, split it.
- Domain errors are raised as `core.exceptions` DomainError subclasses and surface
  only through the standard envelope: {"error_code", "message", "details"}.
