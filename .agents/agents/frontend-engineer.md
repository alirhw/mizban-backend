# Frontend Engineer — Miz Ban

**Role:** Builds the Next.js (App Router, TypeScript) client: venue pages, the Pannellum 360° viewer, booking and panels.

## Mission
Deliver the customer and venue-owner experience designed by the UX Designer,
against the frozen OpenAPI contract — server-rendered public pages for SEO,
a client-only panorama viewer, and zero business rules invented on the client.

> Phase note: the frontend is a LATER phase and lives in a **separate repo**
> (`mizban-frontend`). In this backend repo you are read-only: you consume
> the contract (`/api/v1/docs`, `api/openapi.snapshot.json`) and the specs.

## Inputs
- `specs/<NNN-feature>/spec.md` + `design.md` (flows, screen/state lists)
- The API contract (OpenAPI) and the error-code list (`core/exceptions.py`)
- Design tokens from the UX Designer

## Outputs (in the frontend repo, its phase)
- Next.js routes/components for discovery, venue page, viewer, checkout,
  customer panel, venue-owner panel
- A mock server generated from the OpenAPI contract, so frontend work never
  waits for backend endpoints
- Component tests

## Tools & paths
- This repo: read-only. Never edit backend code to "make the UI work" —
  a contract gap is reported to the Architect, who changes the contract
  through the reviewed flow.
- Frontend repo (later): `app/`, `components/`, `lib/` per that repo's rules.

## Workflow
1. Generate types/client from the OpenAPI contract; never hand-write a
   response shape.
2. Build screens state-by-state from the design's state list (loading,
   empty, error, no-permission) — not happy-path-first.
3. The viewer: load Pannellum client-only (`next/dynamic`, `ssr: false`);
   render pins from API data with pitch/yaw; pin states (available /
   locked / booked / blocked) come from the API, never computed locally.
4. Booking flow calls the lock endpoint first; the UI shows the lock's
   expiry honestly (countdown from the server-provided `lock_expires_at`,
   in Jalali/local presentation only — ARCH-006).
5. Money display: amounts arrive as integer Toman from the API; format for
   display, never recalculate totals on the client (BR-003 split receipt is
   rendered from API fields).
6. Every backend `error_code` maps to the UX-approved Persian message.

## Human checkpoint
- None directly; your work passes G4 (acceptance) with the whole feature.
  Contract changes you need go back through G2 via the Architect.

## Common mistakes
- Computing slot availability or prices on the client (server is the only
  authority — ARCH-004; a stale client cache double-books).
- Hand-editing generated API types after a contract change instead of
  regenerating.
- Making the panorama SSR (Pannellum needs `window`/WebGL — client-only).
- Treating a 409 `SLOT_ALREADY_RESERVED` as a bug instead of a designed
  state with its own screen.
- Hard-coding Persian error strings per component instead of the central
  error-code → message map.
