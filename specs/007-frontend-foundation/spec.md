# Spec 007 — Frontend Foundation (PH-06-01)

**Feature:** 007 — Next.js Frontend Foundation (PH-06)  
**Status:** Implemented (PH-06-01)  
**Governing Rules:** TD-006 (Session Cookies + CSRF, zero JWT/localStorage), ARCH-006 (Jalali presentation only), `api/openapi.snapshot.json`

## 1. Scope & Stack
- **Location:** `frontend/` inside the Miz Ban repository (self-contained `package.json`, `tsconfig.json`, `eslint.config.mjs`, `.prettierrc`, `vitest.config.ts`, `.gitignore`, `.env.example`, `README.md`).
- **Stack:** Next.js 16 (App Router), React 19, TypeScript (`strict: true`), Tailwind CSS v4 (`@tailwindcss/postcss`), bundled `@fontsource/vazirmatn` (zero Google Fonts CDN at runtime), ESLint + Prettier + Vitest.
- **RTL & Language:** `<html lang="fa" dir="rtl">` with Persian copy and `Intl.DateTimeFormat("fa-IR-u-ca-persian")` Jalali presentation helper (`src/lib/jalali.ts`).

## 2. Auth & API Contract
- Single typed fetch client (`src/lib/api.ts`) using `credentials: "include"`, `error_code` error mapping (`ApiError`), and automatic `X-CSRFToken` injection via `GET /api/v1/auth/csrf/` on unsafe methods.
- Same-origin dev proxy rewrite in `next.config.ts` (`/api/v1/:path*` $\to$ `BACKEND_INTERNAL_URL/api/v1/:path*`) so cookies and CSRF work with zero backend CORS edits.
- Auth context (`src/lib/auth.tsx`) backed by `getMe()`, `otpVerify()`, and `logout()`.
- Pages: `/` (live SSR public venue list with loading/error/empty states), `/venues/[slug]` (minimal placeholder), `/login` (OTP request + 120s countdown + verify).

## 3. 360° Panorama Viewer (T-027 — Done)
- **Viewer:** `pannellum@2.5.7` dynamically loaded client-only (`ssr: false`) via `VenuePanoramaExplorer` and `PanoramaViewer` on `/venues/[slug]`.
- **Media Proxy:** `next.config.ts` rewrites `/media/:path*` $\to$ `BACKEND_INTERNAL_URL/media/:path*`; `config/urls.py` serves `MEDIA_URL` in `DEBUG=True` only.
- **Interaction:** Space switcher tabs (`listPublicVenueSpaces`), single-WebP panorama loading (`getPublicSpacePanorama`), >=44px tappable table hotspots (`mapPinsToHotspots`), and Persian selected-table card (`انتخاب این میز` opens `BookingFlow` at step `slot`).

## 4. Customer Booking & Split-Payment Flow (T-028 — Done)
- **State Machine & Helpers (`src/lib/booking.ts`, `src/lib/jalali.ts`):** Pure reducer (`bookingReducer`), split-payment summary (`computeBookingSummary`), 24h lead-time check (`isSlotAtLeast24HoursAhead`), Tehran Jalali date helpers (`getTehranDateIso`, `formatJalaliFromIsoDate`), `mm:ss` lock countdown (`computeLockRemainingSeconds`, `formatCountdownMmSs`), and safe Persian error mapping (`mapBookingErrorToPersian` — never exposes raw `error_code` or stack traces).
- **Booking UI (`src/components/BookingFlow.tsx`):**
  - **Slot Step:** 7 Jalali-labelled dates starting `+1` day from Tehran today, `listVenueSlots(venueId, { date, table_pin_id })`, `<24h` & `is_bookable` gating, only returned slots rendered.
  - **Add-ons Step:** Multi-select `design_addons` labelled `پرداخت حضوری در کافه`.
  - **Review & Lock Step:** Split summary (`بدون افزودنی` when 0 add-ons), auth gate redirecting guests to `/login?next=/venues/<slug>` (validated inside `Suspense` in `src/app/login/page.tsx`), `initiateBooking` lock with live `mm:ss` countdown and expiry restart, and `SLOT_ALREADY_RESERVED` conflict refresh.
  - **Payment & Callback (`src/app/bookings/callback/page.tsx`):** `initiatePayment` with `idempotency_key` and top-level `window.location.assign(redirect_url)` (no iframe). Callback page (wrapped in `Suspense`) renders `getBookingReceipt(booking_id)` split receipt on `CONFIRMED` or Persian retry/restart UI on `FAILED`/`TIMEOUT`.

## 5. Owner Dashboard Pre-Task Contracts (PH-06-02-PRE)
- **Owner Bookings List (`GET /api/v1/venues/owner/venues/{venue_id}/bookings/`):**
  - `ActiveSessionAuth` (`VENUE_OWNER` / `ADMIN` only; `401` unauthenticated, `403` `CUSTOMER` or foreign owner, `404` unknown venue).
  - Bounded pagination via `limit=50` (`1..200`), `offset=0`, ordered by `start_at ASC, id ASC` (nearest slot first).
  - Returns `OwnerBookingOut`: `booking_id`, `status`, `table_number`, `slot_date` (ISO), `jalali_date`, `slot_start_time`, `start_at`, `end_at`, `start_jalali`, `end_jalali`, `amount_online_toman`, `amount_in_person_toman`, `customer_phone_masked` (server-masked `0912***789`; full phone never returned), `created_at`.
- **Derived `SpaceOut.panorama_status`:**
  - Read-only field (`READY` / `PROCESSING` / `UPLOADED` / `FAILED` or `null` when `active_panorama_id` is null), populated via `.select_related("active_panorama")` with zero N+1 queries and zero migrations.

## 6. Customer My-Bookings & Wallet Pre-Task Contracts (PH-06-03-PRE)
- **Customer Bookings List (`GET /api/v1/bookings/my/`):**
  - `ActiveSessionAuth`, `CUSTOMER` role only (`401` unauthenticated, `403` `VENUE_OWNER`).
  - Ordered newest first (`created_at DESC, id DESC`), bounded via `limit=50` (`1..200`), `offset=0`.
  - Returns `CustomerBookingOut`: `booking_id`, `venue_name`, `venue_slug`, `table_number`, `status`, `slot_date` (ISO), `jalali_date`, `slot_start_time`, `start_at`, `end_at`, `start_jalali`, `end_jalali`, `amount_online_toman`, `amount_in_person_toman`, `is_cancellable` (server-derived from T-023 decision tree), `cancel_refund_toman`, `created_at`.
- **Customer Wallet Read (`GET /api/v1/wallets/me/`):**
  - `ActiveSessionAuth`, `CUSTOMER` role only (`401` unauthenticated, `403` `VENUE_OWNER`).
  - Returns `WalletMeOut`: `balance_toman` (via `get_wallet_balance`, matching `BookingCancelOut.wallet_balance_toman`) and `entries` (newest 20 `WalletLedgerEntryOut`: `id`, `direction`, `amount_toman`, `reason`, `jalali_date`, `created_at`). Customers without a wallet receive `balance_toman=0, entries=[]` (`200`, no wallet created on read).
