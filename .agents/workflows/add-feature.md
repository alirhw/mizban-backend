# Workflow: Add a Brand-New Feature (the 8-stage flow)

Use this when the human brings a feature that has no spec folder yet.
Each stage produces files the next stage consumes; gates are full stops.
Miz Ban mapping included — the same flow the 32-task plan followed, now extended by T-033+ for the remaining SRS requirements.

## Stage 1 — Requirements → Gate G1
- **Owner:** Requirements Analyst (human answers business questions).
- **Produces:** `specs/<NNN-feature>/spec.md` — user stories, numbered
  EARS requirements, Gherkin acceptance criteria with real numbers,
  NFR targets, explicit out-of-scope.
- **Miz Ban checks:** which actors (customer / venue owner / admin);
  which BR-01..BR-17 are touched; money movement split (BR-04).
- **G1:** human approves the spec. No design before this.

## Stage 2 — UX Design → part of Gate G2
- **Owner:** UX Designer (Styling/Accessibility reviews).
- **Produces:** flows (Mermaid), screen + full state lists, Persian UI
  copy mapped to backend error codes, panorama/pin interaction design
  where relevant.
- **G2 (joint with Stage 3):** human clicks the flow on a phone.

## Stage 3 — Architecture → part of Gate G2
- **Owner:** Web Architect (Security Engineer gets the threat-model entry).
- **Produces:** `design.md` (API contract first, data model + DB
  invariants, schemas, auth policies, Celery jobs, failure modes),
  ADRs for significant decisions, OpenAPI contract update via the
  reviewed contract flow.
- **Miz Ban checks:** ARCH-001..006 impact stated explicitly; what runs
  in Celery; what must never be cached (ARCH-004).
- **G2:** human approves design + contract.

## Stage 4 — Planning → Gate G3
- **Owner:** Planner.
- **Produces:** `tasks.md` — ≤~400-line tasks, one owner each, named
  fail-first tests, parallel groups with no shared files, protected-path
  tasks flagged.
- **G3:** human approves breakdown + estimates.

## Stage 5 — Build (via run-task loop, per task)
- **Owners:** the engineers (Database → API/Auth/Integrations → Frontend
  in its phase), each task executed through
  `.agents/workflows/run-task.md` steps 4–6.
- Test Engineer's fail-first tests land before or with the build tasks
  they verify (booking race, slot rules, wallet boundaries, OTP limits).

## Stage 6 — Review & Security → Gates G4 + G5
- **Owners:** Code Reviewer (every diff), Test Engineer (acceptance
  evidence), Security Engineer (threat model, high-risk reviews,
  findings triage), Performance Engineer (budget status).
- **G4:** human accepts on a preview/staging build + the evidence packet.
- **G5:** human signs the security packet (accepted risks are signed, or
  they block).

## Stage 7 — Release → Gate G6
- **Owner:** DevOps/Release Engineer (Monitoring/SRE on watch).
- **Produces:** CI-green build, reviewed migrations applied in order,
  release behind a flag/percentage where the design requires, rollback
  ready and stated in the packet, release notes.
- **G6:** human approves timing + migration list + rollback readiness.

## Stage 8 — Operate & Document
- **Owners:** Monitoring/SRE (alerts, health report), Documentation
  Engineer (README/docs/changelog in the same cycle).
- Incidents become follow-up tasks in the plan — the loop feeds Stage 4
  of the next round.

## Miz Ban example (how "manual slot blocking" (FR-011) would flow)
1. Analyst: spec — owner blocks a table or slot; effect on existing
   bookings stated; criteria include "blocked slot cannot be locked".
2. UX: owner panel flow + customer-side "unavailable" state.
3. Architect: `BlockedSlot` model + service check inside the lock flow;
   threat entry: owner can only block own venue's tables.
4. Planner: model task (Database), service+API task (Backend API),
   fail-first test task (Test Engineer), docs task.
5–8. Build → review/security → G4/G5 → release → changelog.
