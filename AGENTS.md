# AGENTS.md - read this first, every task

Project: **Miz Ban** - a two-sided marketplace where customers reserve a specific
cafe/restaurant table by exploring 360-degree panorama photos (Pannellum pins),
and venue owners manage spaces, tables and subscriptions. Backend: Django 5.2 +
Django Ninja modular monolith. Frontend (Next.js 16, App Router, TypeScript,
Tailwind 4, Pannellum 2.5.7) lives in this repo under `frontend/`.

## Commands
- Run everything (Docker): `docker compose up --build`
- Run locally: `python manage.py runserver` (dev settings are the default)
- Migrate: `python manage.py migrate` - generate: `python manage.py makemigrations`
- Sanity: `python manage.py check`
- Test: `pytest` - Lint: `ruff check .` - Types: `mypy .`
- Contract: `./check-contract.sh` (live OpenAPI must match `api/openapi.snapshot.json`)
- API docs: http://127.0.0.1:8000/api/v1/docs - Health: http://127.0.0.1:8000/api/v1/healthz

## Architecture in three lines
- Modular monolith: 9 domain apps under `apps/` (accounts, venues, panoramas,
  scheduling, bookings, billing, wallets, reviews, notifications); imports flow one way, toward
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

## Business rules (Phase 1 SRS, Chapter 4 — canonical numbering BR-01..BR-17)
- BR-01: A slot is exactly 90 minutes.
- BR-02: Exactly 30 minutes of cleaning buffer follow every slot before the
  next slot on the same table (full cycle 120 minutes).
- BR-03: A slot can only be booked if it starts at least 24 hours from now.
- BR-04: Online payment = table fee only (100% platform). Design items are listed
  on the receipt and paid to the cafe in person.
- BR-05: Cancellation only up to 36 hours before the slot; the refund is 100%
  of the table fee.
- BR-06: The refund goes ONLY to the in-app wallet; it can never be withdrawn
  as cash, and is spendable on later bookings.
- BR-07: A venue is publicly visible/bookable only when admin-approved AND its
  subscription is active.
- BR-08: When a subscription ends, the profile is hidden from search, but
  existing confirmed bookings stay valid and visible in the panels.
> Numbering note: early specs and agent files used a legacy scheme
> (BR-001..BR-006) that combined rules the SRS splits apart. Mapping:
> legacy BR-001 = SRS BR-01 + BR-02; BR-002 = BR-03; BR-003 = BR-04;
> BR-004 = BR-05 + BR-06; BR-005 = BR-07; BR-006 = BR-08. The SRS
> numbering (BR-01..BR-17) is canonical — use it in all new writing.
> Old spec files keep their legacy numbers; do not rewrite them.
- Money is always integer Toman. Never floats for money, anywhere.
- Wallets: one-sided audited ledger; balance can never go negative
  (DB CheckConstraint + `select_for_update()`, TD-005).

## Safety and honesty rules
- Never log OTP codes, phone numbers in bulk, tokens or any secret. Never read `.env`.
- Tests are written fail-first and must be able to fail; never weaken, skip or delete
  a test to make CI green. Concurrency tests only count against PostgreSQL.
- A migration touching `apps/bookings`, `apps/wallets`, or `apps/billing` needs human review before
  it is applied anywhere shared.
- One task = at most ~400 changed lines. If the work is bigger, split it.
- Domain errors are raised as `core.exceptions` DomainError subclasses and surface
  only through the standard envelope: {"error_code", "message", "details"}

## Multi-agent operation (the book's team model, run in Antigravity)
This project is built by a team of specialist agents led by an Orchestrator,
defined under `.agents/`:
- `.agents/agents/` - the 18 role definitions (Orchestrator, Analyst, UX,
  Architect, Planner, the engineers, Reviewer, Security, DevOps, SRE, Docs).
  Each states its mission, inputs/outputs, owned paths and workflow.
- `.agents/skills/` - the standing procedures (booking-lock, slot-generation,
  wallet-ledger, otp-sms, panorama-pipeline, payment-gateway-ir, gate-packet,
  task-execution, reviews, notifications, admin-reporting). Load the relevant skill before doing that kind of work.
- `.agents/workflows/` - `run-task.md` (the Orchestrator's loop for one Task ID)
  and `add-feature.md` (the 8-stage flow for a new feature).
- `.agents/kickoff-prompts.md` - ready-to-paste conversation starters.
Operating rules for the team:
- The human talks to the Orchestrator only; the Orchestrator dispatches
  specialists and brings back one gate packet per decision.
- No agent approves its own work: engineers are checked by the Code Reviewer
  and Test Engineer; the team is checked by the human at gates G1-G6.
- `ownership.yaml` is binding for every agent. Where several specialists share
  one ownership entry (e.g. `platform-engineer` covers accounts/venues/reviews;
  `finance-engineer` covers billing/wallets), that entry governs all of them.
  Protected paths always need a human gate.
- Gates G1-G6 are full stops: on reaching a gate, work pauses and resumes only
  on the human's explicit approval. Silence is not approval.
- Every success claim carries real command output (see the gate-packet skill)..
