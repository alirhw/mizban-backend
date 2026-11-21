# Spec 004 — 360-Degree Panorama Floor Plan and Visual Table Pins

**Feature:** 004 — Panoramas & Table Pins  
**Status:** Completed (Phase PH-04 Done)  
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
- **REQ-PANO-007 (Celery Asynchronous Image Conversion Pipeline - T-017):**
  - **Single Dispatch Seam Wiring:** `dispatch_panorama_processing` calls `tasks.process_panorama_image.delay(str(panorama_image_id))`.
  - **Idempotency & Lifecycle:** Only process records in `UPLOADED`, `PROCESSING`, or `FAILED`. If `status == READY`, the task is an immediate no-op (`ALREADY_READY`) avoiding duplicate files and redundant processing.
  - **Pillow Conversion Standards:**
    - Decompression-bomb limits (`Image.MAX_IMAGE_PIXELS`) enforced.
    - EXIF orientation transposed (`ImageOps.exif_transpose`).
    - Color mode normalized to RGB.
    - Strict 2:1 equirectangular aspect ratio check ($1.75 \le \text{aspect} \le 2.25$). Non-2:1 files fail immediately.
    - **No-upscale rule:** Images smaller than 4096x2048 retain their native dimensions. Images exceeding 4096x2048 are downscaled preserving the 2:1 ratio using Lanczos resampling.
    - Main WebP encoded at quality 82 (`method=4`).
    - LQIP thumbnail (512x256 max) encoded at quality 60 (`method=4`).
  - **Atomic Output Writes:** Writes to storage use temporary filenames followed by atomic rename (`os.replace` / storage replacement) to prevent partial files on worker crashes.
  - **Strict Output Verification:** Before updating the DB or deleting the original, outputs are reopened and validated for existence, format (`WEBP`), readability (`im.verify()`), and dimensions.
  - **Safe DB Commit & Clean Deletion:** Database fields (`webp_file`, `thumb_file`, `width`, `height`, `file_size_bytes`, `processed_at`) and status transition to `READY` commit first; the raw heavy original is unlinked from storage only after DB success.
  - **Error Handling & Bounded Retries:** On failure, status transitions to `FAILED` with a sanitized user-facing error message (metadata only in logs; no stack traces or raw bytes leaked), keeping the original file for re-upload/retry. Bounded retries (max 3) apply only to transient exceptions, never deterministic validation failures.
  - **Roadmap Target Reporting:** The 1.5 MB output size is an operational target. If a rich panorama exceeds 1.5 MB, it is logged for tracking without silently reducing quality below 82.
- **REQ-PANO-008 (TablePin Editor and Public Panorama Read - T-018):**
  - **Coordinate Conventions & Bounds:**
    - Pitch: vertical angle in $[-90.0, 90.0]$ degrees (elevation).
    - Yaw: horizontal angle in $[-180.0, 180.0]$ degrees (azimuth).
    - Coordinates strictly reject `NaN` and `Infinity` in Pydantic v2 schemas and are enforced at DB level via `CheckConstraint`.
    - Capacity must be strictly positive ($> 0$). Table number cannot be empty or whitespace.
  - **Owner Authorization & IDOR Protection:**
    - All pin mutations (`POST`, `PUT`, `PATCH`, `DELETE`, `POST .../deactivate`) require an authenticated caller with `VENUE_OWNER` or `ADMIN` role.
    - Scoped strictly to the owner's venue: Owner B attempting to mutate pins in Owner A's venue returns HTTP 403 `FORBIDDEN`.
    - Customer role callers receive HTTP 403 `FORBIDDEN`. Unauthenticated callers receive HTTP 401.
    - Non-existent space or pin returns HTTP 404 `NOT_FOUND`.
    - Venue is derived server-side from `space.venue`, never trusting client-supplied venue id.
    - Table numbers must be unique per venue (`unique_table_number_per_venue`); duplicate within the venue returns HTTP 409 `TABLE_NUMBER_ALREADY_EXISTS`.
  - **TablePin Deletion Protection (ADR-005):**
    - Hard deletion of a pin with existing bookings raises `ProtectedError` and surfaces through the central error envelope as HTTP 409 `TABLE_PIN_PROTECTED` with instructions to deactivate instead.
    - Pins without bookings are hard-deleted cleanly with HTTP 204 No Content.
    - Soft-deactivation is available via `POST /api/v1/panoramas/pins/{pin_id}/deactivate` (or `is_active=False` in PUT/PATCH).
  - **Public Panorama Read Endpoint (`GET /api/v1/spaces/{space_id}/panorama` & `/api/v1/panoramas/spaces/{space_id}/panorama`):**
    - Single bounded query using `select_related` and `prefetch_related` (guarantees zero N+1 queries).
    - Visibility rules (BR-005): Only accessible when venue is approved (`is_approved=True`), subscription is active (`subscription_status=ACTIVE`), space is active (`is_active=True`), and an active `READY` panorama image with a valid `webp_file` exists.
    - Zero Information Leak: If ANY visibility or ready condition fails, returns HTTP 404 `NOT_FOUND` (never revealing whether the space exists, whether processing is pending, or whether the venue is unapproved).
    - Never exposes `original_file` or internal storage keys.
    - Returns WebP image URL, thumbnail URL, and active table pins (`is_active=True`). Deactivated pins are excluded.
  - **Explicit Out-of-Scope Rule:** Space CRUD was excluded from T-018 and implemented in dedicated task T-018b.
- **REQ-PANO-009 (Venue Owner Space CRUD and Public Space Read APIs - T-018b):**
  - **Ownership & IDOR Protection:**
    - All space mutations (`POST`, `PATCH`, `PUT`, `DELETE`, `POST .../deactivate`) require authenticated `VENUE_OWNER` or `ADMIN` role.
    - Owner B attempting to mutate spaces under Owner A's venue returns HTTP 403 `FORBIDDEN`.
    - Customer role callers receive HTTP 403 `FORBIDDEN`. Unauthenticated callers receive HTTP 401.
    - Venue is derived server-side from `venue_id`, rejecting client spoofing.
  - **Validation & Strict Schemas:**
    - `name`: required, non-empty, stripped, max 100 characters. Blank or whitespace-only strings rejected with HTTP 422 `VALIDATION_ERROR`.
    - `display_order`: integer $\ge 0$. Negative values rejected with HTTP 422.
    - Extra fields strictly forbidden in schemas via `model_config = ConfigDict(extra="forbid")`.
  - **Dual-Purpose Space Detail Endpoint (`GET /api/v1/spaces/{space_id}/`):**
    - When accessed by authenticated venue owner (or Admin), returns space detail (`SpaceOut`) regardless of `is_active` or BR-005 visibility.
    - When accessed publicly (unauthenticated, customer, foreign owner), returns space detail ONLY IF venue satisfies BR-005 (approved + active subscription) AND space is active (`is_active=True`).
    - If ANY condition fails, returns HTTP 404 `NOT_FOUND` with zero information leak.
  - **Public Space Listing by Venue Slug (`GET /api/v1/venues/{slug}/spaces/`):**
    - Public listing gated by BR-005: returns active spaces only for approved venues with active subscription.
    - Inactive spaces are excluded.
    - Returns HTTP 404 with zero info leak if venue is unapproved, has inactive subscription, or does not exist.
  - **Three-Tier Space Deletion & Deactivation Policy (T-015 / ADR-005):**
    - **Tier 1 (Bookings Exist):** If any table pin in the space has booking history, `DELETE` fails safely returning HTTP 409 `TABLE_PIN_PROTECTED` (or `ProtectedError`), and space remains in DB.
    - **Tier 2 (Pins or Panoramas Exist, No Bookings):** If space contains pins or panorama images without bookings, `DELETE` soft-deactivates the space (`space.deactivate()`, `is_active=False`), returns HTTP 200 with `SpaceOut`, and space remains in DB.
    - **Tier 3 (No Pins and No Panoramas):** If space has zero pins and zero panoramas, `DELETE` hard-deletes the space (`space.delete()`), returning HTTP 204 No Content.
    - Explicit soft-deactivation is available via `POST /api/v1/spaces/{space_id}/deactivate/`.
  - **Model Method Additions:** Added `Space.delete()` and `Space.deactivate()` to `apps/panoramas/models.py` following the `TablePin` pattern.

---

## 3. Worker Operations & Startup

### Supported Image Formats:
- Equirectangular 2:1 photographs in **JPEG**, **PNG**, or **WebP** formats up to 20 MB.

### Worker Startup Commands:
- **Local Development CLI:**
  ```powershell
  # Ensure Redis and Postgres are running, then launch Celery worker:
  celery -A config worker --loglevel=info
  ```
- **Docker Compose:**
  ```powershell
  # Launch the dedicated Celery worker service:
  docker compose --profile worker up -d worker
  # Or run both web and worker together:
  docker compose --profile web --profile worker up -d
  ```

---

## 4. Scope & Endpoints

- **POST /api/v1/panoramas/spaces/{space_id}/upload** (Alias: `/spaces/{space_id}/images`)
  - **Role:** Venue owner (restricted to venues they own; IDOR protected) or Admin.
  - **Payload:** `multipart/form-data` with `file: UploadedFile`.
  - **Success Response:** HTTP 202 Accepted (`PanoramaUploadOut`).
- **Task T-015:** Domain models, constraints, state machine, and TablePin deletion protection (Done).
- **Task T-016:** Panorama upload API (magic bytes validation, UUID storage, 202 Accepted) (Done).
- **Task T-017:** Celery image processing worker (Pillow, 4096x2048 WebP, 512x256 thumbnail, original deletion) (Done).
- **Task T-018:** TablePin owner APIs (create, update, delete, deactivate) and Public Panorama read endpoint (Done).
- **Task T-018b:** Venue Owner Space CRUD API & Public Space Read Endpoint (Done).
- **Task T-019:** Customer panorama viewer & WebGL/Pannellum performance spike (Done).
- **TablePin Fields Task (FR-004 Gap Fix):** Added `reservation_fee_toman` (integer Toman $\ge 0$) and `is_smoking` (BooleanField, default False) to `TablePin` model, schemas, owner APIs, public read, and booking lock service; migration `0003_add_tablepin_fee_and_smoking.py` applied with 50,000 migration default for existing pins only.

---

## 5. TablePin Fields Specification (FR-004)

- **REQ-PANO-010 (TablePin Fields: Reservation Fee & Smoking Status):**
  - **`reservation_fee_toman`:** Integer Toman ($\ge 0$), set per table by venue owner. Enforced by model validator `MinValueValidator(0)` and database CheckConstraint `table_pin_reservation_fee_non_negative`. Required on creation (`TablePinCreateIn`), optional on update (`TablePinUpdateIn`).
  - **`is_smoking`:** Boolean field (`default=False`), indicating whether smoking is permitted at this table (`True` = allowed, `False` = prohibited). Exposed on creation, partial update, owner reads, and public panorama reads (`TablePinOut`, `PublicTablePinOut`).
  - **Migration Default for Existing Rows Only:** Forward migration `0003_add_tablepin_fee_and_smoking.py` sets existing rows to `reservation_fee_toman = 50_000` (preserving live behavior until owner updates) and `is_smoking = False`. This default exists strictly in the migration; application code contains zero hard-coded fee fallbacks.
  - **Booking Lock Integration:** `create_booking_lock` reads `amount_online_toman = pin.reservation_fee_toman` directly; the prior `getattr(pin, "reservation_fee_toman", 50_000) or 50_000` fallback is removed entirely.
