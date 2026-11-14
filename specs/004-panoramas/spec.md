# Spec 004 — 360-Degree Panorama Floor Plan and Visual Table Pins

**Feature:** 004 — Panoramas & Table Pins  
**Status:** In Progress (Task T-015 Implemented)  
**Governing ADR:** ADR-005 (Space Domain Ownership & TablePin Protection)  
**Architecture Rules:** ARCH-003 (Asynchronous Image Processing), ARCH-001 (Thin Views), ARCH-006 (UTC Instants)  
**Technical Decisions:** TD-003 (Pannellum 360 Viewer, Celery WebP Pipeline)  

---

## 1. Goal

Provide the core visual reservation domain for Miz Ban:
1. Divide venues into distinct visual/physical **Spaces** (e.g. "Main Hall", "Terrace").
2. Allow venue owners to upload heavy equirectangular 360-degree photos that are asynchronously converted into high-performance 4K WebP assets + LQIP blur thumbnails.
3. Allow venue owners to drop reservable **TablePins** onto panorama scenes with spherical coordinates (pitch $[-90, 90]$, yaw $[-180, 180]$).
4. Expose clean visual scenes to customers so they can rotate inside the panorama and select free tables for booking.
5. Guarantee audit integrity by preventing CASCADE deletion of table pins that have customer booking history.

---

## 2. Invariants & Rules

- **REQ-PANO-001 (Space Ownership):** `Space` is owned by `apps/panoramas` and associated to `venues.Venue`. A space groups one or more historical panorama images and active table pins (ADR-005).
- **REQ-PANO-002 (Geometry Bounds):** Table pin spherical coordinates are strictly bounded:
  - Pitch: $[-90.0, 90.0]$ degrees (elevation).
  - Yaw: $[-180.0, 180.0]$ degrees (azimuth).
  - Capacity: strictly positive integer ($> 0$).
- **REQ-PANO-003 (Image Lifecycle):** Panorama images follow a deterministic 4-state lifecycle:
  `UPLOADED -> PROCESSING -> READY / FAILED`.
- **REQ-PANO-004 (TablePin Deletion Protection):** A `TablePin` that has referenced `Booking` records is protected from deletion (`models.PROTECT`). It cannot be deleted via CASCADE; owners must deactivate it instead (`is_active = False`).
- **REQ-PANO-005 (Async Conversion):** Raw image processing never occurs within the request/response cycle. The upload view returns HTTP 202 Accepted, and processing is handled by Celery (ARCH-003).

---

## 3. Scope

- **Task T-015 (This Task):** Domain models, constraints, state machine, and TablePin deletion protection.
- **Task T-016:** Panorama upload API (magic bytes validation, UUID storage, 202 Accepted).
- **Task T-017:** Celery image processing worker (Pillow, 4096x2048 WebP, 512x256 thumbnail, original deletion).
- **Task T-018:** Owner editor APIs (Space CRUD, Pin placement, pitch/yaw coordinates).
- **Task T-019:** Customer viewer API (Pannellum scene JSON, pins with real-time booking availability).
