# Miz Ban — Backend & Full-Stack Platform

A two-sided 360-degree visual table-reservation platform for cafes and restaurants:
customers explore 360-degree panoramas, pick a table directly from interactive pins, and reserve a slot;
venue owners manage spaces, table pins, blocked slots, and subscriptions.

- **Backend:** Django 5.2 + Django Ninja (modular monolith), PostgreSQL 16, Redis, Celery
- **Frontend:** Next.js 16 (App Router, TypeScript, Tailwind CSS) under `frontend/`

## Project Structure

```text
config/          Settings (base / development / production), central Ninja API, Celery, URLs
core/            Domain-independent helpers: exceptions & error envelope, Jalali, pagination, observability
apps/
  accounts/      Custom phone-based User + OTP auth (roles: CUSTOMER / VENUE_OWNER / ADMIN)
  venues/        Venues, operating hours, design add-ons, subscriptions
  panoramas/     Spaces, 360-degree panoramas, table pins (+ Celery WebP/thumbnail pipeline)
  scheduling/    90-minute slot + 30-minute buffer engine & owner blocked slots (BR-001 / BR-002)
  bookings/      Reservations, 10-minute DB booking lock, cancellation & split receipts
  billing/       Payment gateway adapter, payment transactions, idempotent callbacks
  wallets/       Internal non-withdrawable wallet & append-only refund ledger
  reviews/       Post-completion ratings and reviews
frontend/        Next.js web application (customer booking flow, my-bookings/wallet, owner panel)
specs/           Feature specifications, designs, and task checklists
api/             OpenAPI contract snapshot (verified against live schema via check-contract.sh)
```

## Quick Start

### Option A: Local with Virtual Environment

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt  # also re-run after pulling new commits
cp .env.example .env
python manage.py migrate
python manage.py runserver
```

### Option B: Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

### Useful Endpoints & Commands

- **API Docs:** `http://127.0.0.1:8000/api/v1/docs`
- **Health Check:** `http://127.0.0.1:8000/api/v1/healthz`
- **Run Backend Tests:** `pytest -q` (with coverage: `pytest --cov --cov-report=term-missing -q`)
- **Verify OpenAPI Contract:** `./check-contract.sh`
- **Run Frontend Tests:** `cd frontend && npm test`

> **Development note:** When `DATABASE_URL` is unset, `config.settings.development` falls back to SQLite so `manage.py check` and unit tests can run without external services. However, **booking concurrency / row-lock tests require PostgreSQL** (SQLite does not support `select_for_update()` row locking).

## Architecture & Business Rules

Key architectural guardrails (`ARCH-001`–`ARCH-006`) and business rules (`BR-001`–`BR-006`, including 90-minute slots + 30-minute cleaning buffers, 24h booking lead time, 36h cancellation window with wallet-only refunds, integer Toman currency, and UTC storage) are documented in [AGENTS.md](AGENTS.md).
