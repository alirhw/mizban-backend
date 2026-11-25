# Miz Ban Frontend (`frontend/`)

Next.js 16 (App Router) + TypeScript (strict) + Tailwind CSS v4 Persian RTL frontend for Miz Ban.

## Prerequisites & Backend Startup
From the repository root (`mizban-backend/`):
1. Start PostgreSQL 16 and Redis 8 (`docker compose up -d db redis` or `kiri compose up -d db redis`).
2. Run migrations and start the Django backend on `http://127.0.0.1:8000`:
   ```bash
   python manage.py migrate
   python manage.py runserver 8000
   ```

## Environment Variables
Copy `.env.example` to `.env.local` if customising URLs:
- `NEXT_PUBLIC_API_URL` (default `/api/v1` — proxied same-origin via `next.config.ts` rewrites in dev)
- `API_INTERNAL_URL` (default `http://127.0.0.1:8000/api/v1` — used by SSR)
- `BACKEND_INTERNAL_URL` (default `http://127.0.0.1:8000` — rewrite target)

## Scripts
```bash
npm install
npm run dev
npm run build
npm run lint
npm run typecheck
npm test
```

## Auth & CSRF Contract (3 Lines)
1. Authentication uses Django's `HttpOnly` / `SameSite=Lax` `sessionid` cookie issued by `POST /api/v1/auth/otp/verify/` — zero JWTs, zero `localStorage` tokens, zero `Authorization` headers.
2. Every `fetch` passes `credentials: "include"`, and unsafe methods (`POST`/`PUT`/`PATCH`/`DELETE`) automatically fetch `GET /api/v1/auth/csrf/` and inject `X-CSRFToken`.
3. Client auth state (`AuthProvider`) derives exclusively from `GET /api/v1/auth/me/`.

## 360° Panorama Viewer (`T-027`)
- Uses `pannellum@2.5.7` loaded client-only (`next/dynamic` with `{ ssr: false }`) on `/venues/[slug]`.
- In `next.config.ts`, `/media/:path*` is proxied to `BACKEND_INTERNAL_URL/media/:path*` so relative `/media/...` WebP panorama URLs load same-origin in dev (with `config/urls.py` serving `MEDIA_URL` when `DEBUG=True`).
- To seed clearly-labelled DEV-ONLY sample data (venue `کافه نمونه — توسعه`, slug `sample-cafe-dev`, 1 space, synthetic `4096x2048` WebP panorama, 4 table pins):
  ```bash
  python manage.py seed_dev_panorama
  ```
  To remove the dev seed:
  ```bash
  python manage.py seed_dev_panorama --clear
  ```
- For LAN mobile testing (e.g., Galaxy A31):
  ```bash
  npm run dev -- -H 0.0.0.0 -p 3000
  ```

## Customer Booking & Split-Payment Flow (`T-028`)
- Clicking **انتخاب این میز** on a 360° table pin in `VenuePanoramaExplorer` opens `BookingFlow` (`src/components/BookingFlow.tsx`) at the slot-selection step:
  1. **Slot Selection:** Displays 7 Jalali-labelled dates starting `+1` day from Tehran today (`getTehranDateIso` / `formatJalaliFromIsoDate`), fetches `GET /api/v1/scheduling/venues/{venue_id}/slots`, and disables `<24h` (`isSlotAtLeast24HoursAhead`) or non-bookable slots without inventing `blocked` labels.
  2. **Design Add-ons:** Multi-selects `design_addons` with Toman fees clearly labelled **پرداخت حضوری در کافه**.
  3. **Review & Lock:** Displays split totals (online table fee vs. in-person add-ons or `بدون افزودنی`), redirects unauthenticated users to `/login?next=/venues/<slug>`, and calls `POST /api/v1/bookings/initiate/` to acquire a 10-minute lock with a live `mm:ss` countdown.
  4. **Payment & Callback (`/bookings/callback`):** Calls `POST /api/v1/billing/initiate/` with an `idempotency_key` and performs a top-level `window.location.assign(redirect_url)` (no iframe). On `CONFIRMED`, fetches `GET /api/v1/bookings/{booking_id}/receipt/` and renders the split receipt; on `FAILED`/`TIMEOUT`, offers retry while the lock is active or restart back to `/venues/<venue>`.

## Venue-Owner Dashboard (`PH-06-02`)
- **Routes:** `/owner` (list of owned venues + read-only subscription status) and `/owner/venues/[id]` (spaces & panorama status, table pin fee/capacity/smoking editor, `BlockedSlot` manager, read-only subscription card, and bookings overview with masked customer phones).
- Unauthenticated users redirect to `/login?next=/owner`; non-owner (`CUSTOMER`) accounts see the Persian **دسترسی ندارید** screen.
- For local dev testing, `09120009999` (`VENUE_OWNER`) owns both `sample-cafe-dev` (`id=1`) and `real-cafe-dev` (`id=3`).

## Customer My-Bookings, Cancellation & Wallet (`PH-06-03`)
- **Route:** `/my-bookings` («رزروهای من», redirects guests to `/login?next=/my-bookings`).
- Displays the customer's bookings newest first (`GET /api/v1/bookings/my/`), split receipts (`GET /api/v1/bookings/{id}/receipt/`), server-driven cancellation (`POST /api/v1/bookings/{id}/cancel/` with BR-004 36-hour rule, wallet refund vs. «بدون بازپرداخت», and non-refundable in-person add-ons notice), and the read-only, non-withdrawable wallet balance + recent ledger entries (`GET /api/v1/wallets/me/`).
