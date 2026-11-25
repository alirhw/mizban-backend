# Tasks — Phase PH-06 Frontend Foundation

| Task ID | Description | Owner | Status |
| :--- | :--- | :--- | :--- |
| **PH-06-01** | Next.js 16 + TypeScript + Tailwind v4 RTL scaffold, typed session/CSRF API client, `AuthProvider`, Jalali helper, `/` live venue list, `/venues/[slug]` placeholder, `/login` OTP UI, Vitest unit tests, and live backend smoke test | `frontend-engineer` | Done |
| **T-027** | Pannellum `2.5.7` 360° viewer on `/venues/[slug]`, space switcher, >=44px tappable table pins, Persian selected-table card (`انتخاب این میز` local state), `/media/*` dev proxy, Vitest tests, and DEV-ONLY `seed_dev_panorama` command | `frontend-engineer` | Done |
| **T-027-FIX** | Add DEV-ONLY `real-cafe-dev` (`کافه واقعی — توسعه`) via normal upload/processing pipeline (`dev_assets/cafe-panorama-360-real.jpg`) + 4 visible-table pins without touching `sample-cafe-dev` or viewer code | `orchestrator` | Done |
| **T-028** | End-to-end customer booking & split-payment flow (`BookingFlow.tsx`, `VenuePanoramaExplorer` integration, `/login?next=` `Suspense` redirect, `/bookings/callback` split receipt & retry/restart, `booking.ts`/`jalali.ts`/`api.ts` unit tests) | `booking-ui` | Done |
| **T-028-FIX** | Fix review bugs B1–B5 and B7 (`seed_dev_panorama --clear` shared plan guard, receipt-derived confirmed heading, booking return URL state restore, stable retry idempotency key, DEBUG callback open-redirect guard, BR-002 comment) | `orchestrator` | Done |
| **PH-06-02-PRE** | Add `GET /api/v1/venues/owner/venues/{venue_id}/bookings/` (masked phone, nearest slot first, `limit=50`/`offset=0`) and derived `SpaceOut.panorama_status` (`select_related`), refresh `api/openapi.snapshot.json` | `orchestrator` | Done |
| **PH-06-02** | Venue-owner dashboard (`/owner`, `/owner/venues/[id]`, spaces & panorama status, pin fee/capacity/smoking editor, `BlockedSlot` manager, read-only subscription card, bookings overview with masked phones, Vitest tests) | `orchestrator` | Done |
| **PH-06-03-PRE** | Add `GET /api/v1/bookings/my/` (T-023 server-derived `is_cancellable`/`cancel_refund_toman`, newest first, `limit=50`/`offset=0`) and `GET /api/v1/wallets/me/` (read-only balance + latest 20 ledger entries), refresh `api/openapi.snapshot.json` | `orchestrator` | Done |
| **PH-06-03** | Customer `/my-bookings`, split receipt detail, BR-004 cancel confirmation & wallet refund refresh, read-only non-withdrawable wallet UI, Vitest tests | `orchestrator` | Done |
