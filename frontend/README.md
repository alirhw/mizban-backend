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
