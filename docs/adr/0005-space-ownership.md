# ADR-005: Domain Ownership of the Space Entity and TablePin Deletion Semantics

- **Status:** Accepted (Approved at Gate T-015)
- **Date:** 2026-11-14
- **Author:** Web Architect & Database Engineer
- **Approved by:** Project Lead (Gate T-015 Decision)
- **Task:** T-015 — Resolve Space Ownership and Define Panorama Domain Models

> **Note on ADR Numbering Inconsistency:** In the project architecture document, ADR-002 is assigned to *Pannellum Client-Side Panorama Viewer Architecture* (TD-003). To avoid ID collision and maintain an unambiguous audit record, this decision is canonically recorded as **ADR-005: Space Domain Ownership and TablePin Deletion Semantics**.

---

## 1. Context and Problem Statement

In the Miz Ban visual table-reservation platform, a cafe or restaurant consists of one or more physical/visual areas (e.g., "Main Indoor Hall", "Balcony", "Rooftop Garden"). In the database, this concept is called `Space`.

During Task T-011, minimal `Space` and `TablePin` models were created in `apps/panoramas/models.py` with migration `panoramas.0001_initial` to serve as the foreign-key foundation for the `Booking` model (`apps/bookings/models.py:70-74`).

As Task T-015 begins the formal Panoramas domain implementation (Tasks T-015 through T-019), two architecture decisions were resolved:
1. **Ownership of `Space`:** Does `Space` belong in `apps/venues` (Option A) or `apps/panoramas` (Option B)?
2. **Deletion Semantics of `TablePin`:** How should deletion of a `TablePin` behave when associated `Booking` records exist?

---

## 2. Decision on Space Ownership: Option B (`apps/panoramas`)

The project lead formally approved **Option B**: `Space` remains canonically owned by `apps/panoramas`.

### Rationale:
1. **Migration Continuity:** Adheres to the binding Gate T-011 directive: *"EXTEND these existing models and migrations rather than rebuilding or replacing them"* (`specs/001-booking-lock/tasks.md:25`). Existing committed migrations `panoramas.0001_initial` and `bookings.0001_initial` remain 100% untouched.
2. **Clean Dependency Flow (`AGENTS.md:18-20`):** `apps/panoramas` depends on `apps/venues` (unidirectional, toward foundations). `apps/venues` has zero dependencies on `apps/panoramas`.
3. **Avoidance of Circular Dependencies:** Keeping `Space`, `PanoramaImage`, and `TablePin` in `apps/panoramas` allows `Space.active_panorama` to reference `PanoramaImage` and `PanoramaImage.space` to reference `Space` without cross-app circular imports.
4. **Documentation Alignment:** Aligns with `README.md:17`, `STEP-T008-README.md:42`, and `specs/002-venue-catalogue/spec.md:72`.

---

## 3. Decision on TablePin Deletion Behavior: `PROTECT`

### Rationale:
In the initial scaffolding (`apps/bookings/models.py:72`), `Booking.table_pin` was configured with `on_delete=models.CASCADE`. Under this behavior, deleting a `TablePin` would silently delete all past and present customer reservations for that table, destroying financial records, audit logs, and customer booking history.

### Adopted Policy:
1. **ORM & DB Protection (`models.PROTECT`):**
   `Booking.table_pin` is updated to `on_delete=models.PROTECT`. If an administrator or service attempts to delete a `TablePin` that has referenced `Booking` records, Django and PostgreSQL raise `ProtectedError`, preventing deletion.
2. **Deactivation / Soft Delete (`is_active = False`):**
   When a table is retired, reconfigured, or temporarily closed, owners and managers must set `table_pin.is_active = False` (or use `table_pin.deactivate()`). Inactive pins are excluded from visual booking availability while preserving complete booking history.

---

## 4. Panorama Geometry & Status Lifecycle Invariants

### 1. Pitch and Yaw Spherical Coordinate Bounds:
- **Pitch (Elevation):** Vertical angle constrained to $[-90.0, 90.0]$ degrees.
  - `-90.0°`: Nadir (floor).
  - `+90.0°`: Zenith (ceiling).
  - Enforced by DB `CheckConstraint(condition=Q(pitch__gte=-90.0, pitch__lte=90.0) | Q(pitch__isnull=True), name="table_pin_pitch_bounds")`.
- **Yaw (Azimuth):** Horizontal rotation constrained to $[-180.0, 180.0]$ degrees.
  - Enforced by DB `CheckConstraint(condition=Q(yaw__gte=-180.0, yaw__lte=180.0) | Q(yaw__isnull=True), name="table_pin_yaw_bounds")`.
- **Table Capacity:** Positive integer $> 0$.
  - Enforced by DB `CheckConstraint(condition=Q(capacity__gt=0), name="table_pin_capacity_positive")`.

### 2. Panorama Status Lifecycle (TD-003 / ARCH-003 / SKILL.md):
```text
  [ Upload API: 202 Accepted ]
               │
               ▼
         ┌───────────┐
         │  UPLOADED │ ── (Magic bytes verified, temporary UUID storage)
         └───────────┘
               │
               ▼ (Celery task: process_panorama_image)
        ┌─────────────┐
        │  PROCESSING │
        └─────────────┘
          │         │
(Success) │         │ (Aspect ratio != 2:1, corrupt, or Pillow error)
          ▼         ▼
      ┌───────┐ ┌────────┐
      │ READY │ │ FAILED │ ── (Safe error summary stored, ready for re-upload)
      └───────┘ └────────┘
```
- Valid transitions:
  - `UPLOADED -> PROCESSING`
  - `PROCESSING -> READY`
  - `PROCESSING -> FAILED`
  - `FAILED -> PROCESSING` (on retry/re-upload)
- Invalid transitions are rejected with `InvalidStatusTransitionError`.
