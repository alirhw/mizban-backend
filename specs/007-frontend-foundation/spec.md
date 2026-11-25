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
- **Interaction:** Space switcher tabs (`listPublicVenueSpaces`), single-WebP panorama loading (`getPublicSpacePanorama`), >=44px tappable table hotspots (`mapPinsToHotspots`), and Persian selected-table card (`انتخاب این میز` local state only).
