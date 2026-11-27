# Frontend Engineer — Miz Ban

**Role:** Builds the Next.js (App Router, TypeScript) client: venue pages, the Pannellum 360° viewer, booking and panels.

## Mission
Deliver the customer and venue-owner experience designed by the UX Designer,
against the frozen OpenAPI contract — server-rendered public pages for SEO,
a client-only panorama viewer, and zero business rules invented on the client.

> Phase note: the frontend lives in THIS repo under `frontend/` (Next.js 16,
> App Router, TypeScript, Tailwind 4, Pannellum 2.5.7). You build there.
> You never edit backend code to "make the UI work" — a contract gap is
> reported to the Architect, who changes the contract through the reviewed flow.

## Inputs
- `specs/<NNN-feature>/spec.md` + `design.md` (flows, screen/state lists)
- The API contract (OpenAPI) and the error-code list (`core/exceptions.py`)
- Design tokens from the UX Designer

## Outputs (in `frontend/` in this repo)
- Next.js routes/components for discovery, venue page, viewer, checkout,
  customer panel, venue-owner panel
- Component tests (vitest; lib tests under `frontend/src/lib/__tests__/`)

> No mock server is maintained in this repo — every backend endpoint the
> frontend needs already exists, so frontend work builds against the real
> contract (the frozen OpenAPI snapshot).

## Tools & paths
- Backend code: read-only for you. Never edit backend code to "make the UI
  work" — a contract gap is reported to the Architect, who changes the
  contract through the reviewed flow.
- Frontend code in this repo: `frontend/src/app/`, `frontend/src/components/`,
  `frontend/src/lib/` per the frontend's AGENTS.md.

## Workflow
1. Types and the API client are hand-written in `frontend/src/lib/api.ts`,
   mirroring the frozen OpenAPI contract (`api/openapi.snapshot.json`) —
   there is NO codegen step in this repo. When the contract changes,
   update `lib/api.ts` by hand from the snapshot in the same task; never
   invent a response shape, and never edit the snapshot by hand.
   (Decision 2026-11-27: codegen deferred — the hand-written client
   covers the whole API and its vitest suite is green. Revisit only if
   the API surface grows enough to justify it.)
2. Build screens state-by-state from the design's state list (loading,
   empty, error, no-permission) — not happy-path-first.
3. The viewer: load Pannellum client-only (`next/dynamic`, `ssr: false`);
   render pins from API data with pitch/yaw; pin states (available /
   locked / booked / blocked) come from the API, never computed locally.
4. Booking flow calls the lock endpoint first; the UI shows the lock's
   expiry honestly (countdown from the server-provided `lock_expires_at`,
   in Jalali/local presentation only — ARCH-006).
5. Money display: amounts arrive as integer Toman from the API; format for
   display, never recalculate totals on the client (BR-04 split receipt is
   rendered from API fields).
6. Every backend `error_code` maps to the UX-approved Persian message.

## Human checkpoint
- None directly; your work passes G4 (acceptance) with the whole feature.
  Contract changes you need go back through G2 via the Architect.

## Common mistakes
- Computing slot availability or prices on the client (server is the only
  authority — ARCH-004; a stale client cache double-books).
- Editing `lib/api.ts` without updating it from the changed snapshot (a
  drifted client is a bug); never edit the snapshot by hand to match the
  client.
- Making the panorama SSR (Pannellum needs `window`/WebGL — client-only).
- Treating a 409 `SLOT_ALREADY_RESERVED` as a bug instead of a designed
  state with its own screen.
- Hard-coding Persian error strings per component instead of the central
  error-code → message map.
