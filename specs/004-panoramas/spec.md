# Spec 004 — 360-Degree Panorama Floor Plan and Visual Table Pins

**Feature:** 004 — Panoramas & Table Pins  
**Status:** In Progress (Task T-016 Implemented)  
**Governing ADR:** ADR-005 (Space Domain Ownership & TablePin Protection)  
**Architecture Rules:** ARCH-003 (Asynchronous Image Processing), ARCH-001 (Thin Views), ARCH-006 (UTC Instants), TR-002 / TD-003 (Strict Ingress Limits & Content Validation)  
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
- **REQ-PANO-006 (Strict Upload Validation & Limits - T-016):**
  - **Application Limit:** 20 MB maximum (`MAX_PANORAMA_FILE_SIZE = 20 * 1024 * 1024` bytes). Oversized bodies are rejected with HTTP 400 `FILE_TOO_LARGE`.
  - **Reverse-Proxy Deployment Limit:** Production reverse proxy (e.g., Nginx, Caddy, Traefik) must configure `client_max_body_size 25M;` (to accommodate HTTP multipart overhead above the 20 MB application payload).
  - **Content Validation:** Never trust client MIME types or file extensions. Real magic bytes (JPEG `\xff\xd8\xff`, PNG `\x89PNG\r\n\x1a\n`, WebP `RIFF....WEBP`) and Pillow `im.verify()` validation are strictly required. Corrupt files, spoofed extensions, and non-equirectangular formats (e.g. GIF, PDF) return HTTP 400 `INVALID_IMAGE`.
  - **Decompression-Bomb Protection:** Pillow's `Image.MAX_IMAGE_PIXELS` (~89.5 megapixels) enforces protection against DOS attacks; malicious bombs return HTTP 400 `IMAGE_DECOMPRESSION_BOMB`.
  - **Path Traversal Prevention:** Client-supplied filenames are never used in storage keys. Files are stored at `panoramas/{venue_id}/{uuid}.<ext>` using cryptographically random UUIDv4.
  - **Single Dispatch Seam & Broker Resilience:** Processing is dispatched via `transaction.on_commit(lambda: dispatch_panorama_processing(panorama.id))`. If the message broker is unreachable, the upload succeeds with HTTP 202 and the record remains safely in `UPLOADED` status.
  - **Zero Orphan Cleanup:** If database record creation or transaction fails after storage write, any uploaded file in `default_storage` is automatically removed.

---

## 3. Scope & Endpoints

- **POST /api/v1/panoramas/spaces/{space_id}/upload** (Alias: `/spaces/{space_id}/images`)
  - **Role:** Venue owner (restricted to venues they own; IDOR protected) or Admin.
  - **Payload:** `multipart/form-data` with `file: UploadedFile`.
  - **Success Response:** HTTP 202 Accepted (`PanoramaUploadOut`).
- **Task T-015:** Domain models, constraints, state machine, and TablePin deletion protection (Done).
- **Task T-016:** Panorama upload API (magic bytes validation, UUID storage, 202 Accepted) (Implemented).
- **Task T-017:** Celery image processing worker (Pillow, 4096x2048 WebP, 512x256 thumbnail, original deletion) (Next).
- **Task T-018:** Owner editor APIs (Space CRUD, Pin placement, pitch/yaw coordinates).
- **Task T-019:** Customer viewer API (Pannellum scene JSON, pins with real-time booking availability).
