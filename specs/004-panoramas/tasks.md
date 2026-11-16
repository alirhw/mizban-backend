# Tasks — Feature 004 Panoramas & Table Pins

| Task ID | Description | Owner | Status | Dependencies |
| :--- | :--- | :--- | :--- | :--- |
| **T-015** | Resolve Space Ownership and Define Panorama Domain Models | `web-architect` / `database-engineer` | Done (Gate G4 Approved) | T-014 |
| **T-016** | 360 Panorama Upload Endpoint & Validation (Magic bytes, UUID, 202) | `backend-api-engineer` | Done (Gate G4 Approved) | T-015 |
| **T-017** | Celery Asynchronous Image Conversion Pipeline (WebP, thumb, cleanup) | `media-engineer` | Done (Gate G4 Approved) | T-016 |
| **T-018** | Venue Owner Panorama & Table Pin Editor API (Space CRUD excluded, Pin CRUD, Public Read) | `backend-api-engineer` | Done (Gate G4 Approved) | T-017 |
| **T-018b** | Venue Owner Space CRUD API & Public Space Read Endpoint | `backend-api-engineer` | Done (Pending Gate Approval) | T-018 |
| **T-019** | Customer Panorama Viewer & WebGL/Pannellum Performance Spike | `media-engineer` / `frontend-engineer` | Done (Gate G4 Approved) | T-018 |

---

### Gate T-018b Decisions & Implementation Notes:
1. **Space Model Methods Added (Zero Schema Migration):**
   - Added `Space.delete()` and `Space.deactivate()` in `apps/panoramas/models.py` following the `TablePin` pattern (ADR-005).
   - `Space.delete()` checks if any `Booking` exists for table pins in the space (`Booking.objects.filter(table_pin__space=self).exists()`); raises `models.ProtectedError` if bookings exist.
   - `Space.deactivate()` sets `is_active = False` and saves with `update_fields=["is_active", "updated_at"]`.
   - Verified `makemigrations --check` detects zero schema changes (Python domain methods only).
2. **Owner Space CRUD Endpoints:**
   - Implemented `POST /api/v1/venues/{venue_id}/spaces/` (201 Created with `SpaceOut`, IDOR protected).
   - Implemented `GET /api/v1/venues/{venue_id}/spaces/` (200 OK with `list[SpaceOut]`, owner receives active and inactive spaces ordered by display_order).
   - Implemented `GET /api/v1/spaces/{space_id}/` (200 OK, dual-purpose: owner/admin sees space regardless of status; public sees space only if BR-005 holds and is_active=True, otherwise 404 with zero leak).
   - Implemented `PATCH /api/v1/spaces/{space_id}/` and `PUT` (200 OK with `SpaceOut`, partial/full updates).
   - Implemented `POST /api/v1/spaces/{space_id}/deactivate/` (200 OK with `SpaceOut`, explicit soft-deactivation).
   - Implemented `DELETE /api/v1/spaces/{space_id}/` (204 No Content if 0 pins and 0 panoramas; 200 OK if pins or panoramas exist without bookings; 409 Conflict with `TABLE_PIN_PROTECTED` if pins have booking history).
3. **Public Space Read Endpoint:**
   - Implemented `GET /api/v1/venues/{slug}/spaces/` (200 OK with `list[SpaceOut]`, gated by BR-005: returns active spaces only for approved venues with active subscription; otherwise 404 with zero info leak).
4. **Validation & Strict Schemas:**
   - `SpaceCreateIn`: `name` (required, non-empty, stripped, max 100), `description: str = ""`, `display_order: int = 0` ($\ge 0$), `is_active: bool = True`, `model_config = ConfigDict(extra="forbid")`.
   - `SpaceUpdateIn`: optional fields with identical bounds and `extra="forbid"`.
   - `SpacePublicOut` and `SpaceOut` response schemas.
5. **Ownership & IDOR Protection:**
   - All mutations require authenticated `VENUE_OWNER` or `ADMIN`.
   - Scoped strictly to the owner's venue: Owner B attempting to mutate spaces in Owner A's venue returns HTTP 403 `FORBIDDEN`.
   - Customer role callers receive HTTP 403 `FORBIDDEN`. Unauthenticated callers receive HTTP 401.
   - Venue is derived server-side from `venue_id`, preventing client spoofing.
6. **Query Optimization & Zero N+1 Queries:**
   - Verified bounded queries with `django_assert_num_queries(1)` for space detail and `django_assert_num_queries(2)` for public venue spaces list.
7. **Test Evidence:**
   - 42 new unit & integration tests in `apps/panoramas/tests/test_spaces_api.py`.
   - Panoramas test suite: 119/119 passed.
   - Full test suite: 194/194 passed, 0 failed, 0 skipped, on Django 5.2.19 and PostgreSQL 16.15.

---

### Gate T-019 Decisions & Spike Findings:
1. **Pannellum 2.5.7 Performance Validated:**
   - 36 repeated automated runs across Desktop (1x), Mid-tier (4x CPU slowdown, DPR 2.625), and Low-end (6x CPU slowdown, DPR 2.0).
   - Sustains 58–60 FPS on low-end emulated profile (average 59.1 FPS, 1% low 30.0 FPS, <1% dropped frames).
   - Confirms single equirectangular 4K WebP asset is sufficient; multi-resolution pyramid tile engine is NOT needed.
2. **Quality Setting 82 Confirmed:**
   - Quality 82 produces ~1.39 MB (well below the 1.5 MB operational ceiling) with 37.90 dB PSNR.
   - Retained `PANORAMA_QUALITY = 82` in Celery pipeline.
3. **Memory Footprint Safe:**
   - JS Heap: 0.92 MB – 3.02 MB.
   - WebGL GPU Texture VRAM: deterministic 32.0 MB uncompressed.
4. **Honest Recording & Open Risks:**
   - All measurements were Chrome DevTools emulation; physical-device verification (e.g. Galaxy A31) remains an open QA field trial item.
   - Mid-tier high-DPR 1% low dips just below 30 FPS; DPR clamping (<= 2.0) in T-027 is the documented mitigation.
5. **Documented Fallbacks for T-027:**
   - `MAX_TEXTURE_SIZE` guard (<4096 fallback to 2K).
   - Two-stage progressive loading with LQIP thumbnail (`thumbnail_url`, <50ms first paint).
   - DPR clamping on high-density displays.
   - WebGL context-loss recovery.

---

### Gate T-018 Decisions & Implementation Notes:
1. **Scope Boundary (Space CRUD Excluded):**
   - Strictly followed the project doc and Orchestrator instructions: Space CRUD is excluded from T-018 (deferred to dedicated space management task if required).
2. **Owner TablePin CRUD Endpoints:**
   - Implemented `POST /api/v1/panoramas/spaces/{space_id}/pins` (201 Created).
   - Implemented `GET /api/v1/panoramas/spaces/{space_id}/pins` (200 OK).
   - Implemented `GET /api/v1/panoramas/pins/{pin_id}` (200 OK).
   - Implemented `PUT /api/v1/panoramas/pins/{pin_id}` and `PATCH /api/v1/panoramas/pins/{pin_id}` (200 OK).
   - Implemented `POST /api/v1/panoramas/pins/{pin_id}/deactivate` (200 OK).
   - Implemented `DELETE /api/v1/panoramas/pins/{pin_id}` (204 No Content or 409 Conflict).
3. **Coordinate Conventions & Bounds Validation:**
   - Pitch: $[-90.0, 90.0]$ degrees (vertical angle / elevation).
   - Yaw: $[-180.0, 180.0]$ degrees (horizontal angle / azimuth).
   - Capacity: strictly positive integer ($> 0$).
   - Rejection of `NaN` and `Infinity` enforced in Pydantic v2 schemas (`TablePinCreateIn`, `TablePinUpdateIn`) and database constraints (`CheckConstraint`).
4. **Ownership & IDOR Protection:**
   - All pin mutations require authenticated `VENUE_OWNER` or `ADMIN`.
   - Caller must own the pin's venue. Foreign owner mutations return HTTP 403 `FORBIDDEN`.
   - Customer role callers return HTTP 403 `FORBIDDEN`. Unauthenticated callers return HTTP 401.
   - Venue is derived server-side from `space.venue`, preventing client spoofing.
   - Table number uniqueness is enforced per venue (`unique_table_number_per_venue`); duplicate returns HTTP 409 `TABLE_NUMBER_ALREADY_EXISTS`.
5. **TablePin Deletion Protection (ADR-005):**
   - Deleting a pin with existing bookings raises `ProtectedError`, surfaced as HTTP 409 `TABLE_PIN_PROTECTED` with instructions to deactivate instead.
   - Pins without bookings are hard-deleted cleanly (HTTP 204 No Content).
   - Soft-deactivation is available via `POST /api/v1/panoramas/pins/{pin_id}/deactivate` (sets `is_active=False`).
6. **Public Panorama Read Endpoint (`GET /api/v1/spaces/{space_id}/panorama` & alias `/panoramas/spaces/{space_id}/panorama`):**
   - Implemented with a single bounded query using `select_related` and `prefetch_related` (zero N+1 queries).
   - Enforces BR-005: venue must be approved (`is_approved=True`), subscription must be active (`subscription_status=ACTIVE`), space must be active (`is_active=True`), and an active `READY` panorama image with a valid `webp_file` must exist.
   - Zero Information Leak: If ANY visibility check fails, returns HTTP 404 `NOT_FOUND` (identical response, never revealing internal existence or processing status).
   - Returns WebP image URL, thumbnail URL, and active table pins (`is_active=True`). Deactivated pins are excluded.
   - Never exposes `original_file` or internal storage keys.

---
1. **Celery Worker Configuration & Compose Service:**
   - Added `worker` service to `docker-compose.yml` (`celery -A config worker --loglevel=info`).
   - Configured `CELERY_ACCEPT_CONTENT`, `CELERY_TASK_SERIALIZER`, `CELERY_RESULT_SERIALIZER`, `CELERY_TASK_TRACK_STARTED`, and `CELERY_TASK_TIME_LIMIT = 300` in `config/settings/base.py`.
   - Documented worker operations, CLI commands, and supported image formats in `specs/004-panoramas/spec.md`.
2. **Task Implementation & Dispatch Seam Wiring:**
   - Implemented `@shared_task(name="panoramas.process_panorama_image")` in `apps/panoramas/tasks.py`.
   - Connected `dispatch_panorama_processing` seam in `apps/panoramas/services.py` directly to `process_panorama_image.delay`.
3. **Idempotency & Lifecycle Flow:**
   - Tasks checks status on arrival: if `status == READY`, returns `ALREADY_READY` immediately without creating duplicate files or re-deleting files.
   - Transitions `UPLOADED -> PROCESSING -> READY / FAILED`.
4. **Pillow Equirectangular Conversion Standards:**
   - Safe opening with `Image.MAX_IMAGE_PIXELS = 89478485` decompression-bomb protection.
   - EXIF orientation transposed (`ImageOps.exif_transpose`).
   - Color mode normalized to RGB.
   - Equirectangular 2:1 aspect ratio strictly enforced.
   - **No-upscale rule:** Images smaller than 4096x2048 retain native dimensions (e.g. 2048x1024 stays 2048x1024). Oversized images downscale preserving 2:1 ratio using Lanczos resampling.
   - Main WebP encoded at quality 82 (`method=4` for balanced high performance and optimal size).
   - LQIP thumbnail (512x256 max) encoded at quality 60 (`method=4`).
5. **Atomic Output Writes & Output Verification:**
   - `atomic_storage_save` writes to temporary files first before atomic rename (`os.replace`).
   - Output verification checks format, readability (`im.verify()`), and dimensions BEFORE updating database and BEFORE deleting the raw original.
6. **Deletion & Failure Safety:**
   - Raw heavy original file is deleted ONLY AFTER verified outputs and successful DB commit.
   - On error: status transitions to `FAILED` with sanitized error message (metadata only in logs, no raw content leaked), preserving the original file for re-upload/retry. Bounded retries (max 3) apply only to transient exceptions.
7. **Roadmap Target Reporting:**
   - Files $>1.5$ MB are logged as info metadata without silently reducing quality below 82.

---

### Gate T-016 Decisions & Implementation Notes:
1. **Endpoint & Contract:**
   - Implemented `POST /api/v1/panoramas/spaces/{space_id}/upload` with alias `/spaces/{space_id}/images`.
   - Returns HTTP 202 Accepted with schema `PanoramaUploadOut` (`id`, `space_id`, `venue_id`, `status: "UPLOADED"`, `original_file`, `file_size_bytes`, `width`, `height`, `created_at`, `message`).
2. **Access Control & IDOR Guard:**
   - Restricted to `VENUE_OWNER` (only for venues they own) and `ADMIN` / staff users.
   - Non-owners receive HTTP 403 `FORBIDDEN`. Unauthenticated callers receive HTTP 401. Non-existent space returns HTTP 404 `NOT_FOUND`.
3. **Application & Reverse-Proxy Limits:**
   - Application hard limit: 20 MB (`MAX_PANORAMA_FILE_SIZE = 20 * 1024 * 1024` bytes). Oversized uploads fail with HTTP 400 `FILE_TOO_LARGE`.
   - Documented reverse-proxy deployment rule: `client_max_body_size 25M;` in Nginx / ingress to support multipart envelope overhead.
4. **Content Validation & Decompression Safety:**
   - Content verification via magic bytes fallback chain (JPEG, PNG, WebP) and Pillow `im.verify()`. Spoofed extensions, corrupt streams, and unpermitted formats (GIF, PDF) return HTTP 400 `INVALID_IMAGE`.
   - Decompression-bomb limits (`Image.MAX_IMAGE_PIXELS`) prevent DOS attacks, returning HTTP 400 `IMAGE_DECOMPRESSION_BOMB`.
5. **Storage & Path Traversal Prevention:**
   - Stored with UUIDv4 filename under `panoramas/{venue_id}/{uuid}.<ext>` via `default_storage`. Client-provided filenames are completely discarded.
6. **Single Dispatch Seam & Broker Resilience:**
   - `dispatch_panorama_processing` dispatched via `transaction.on_commit()`.
   - Broker outages log a warning and return False; upload succeeds (202 Accepted) with record remaining `UPLOADED`.
7. **Failure Cleanup:**
   - If database transaction fails, any newly created file in `default_storage` is automatically cleaned up, guaranteeing zero orphan files.

---

### Gate T-015 Decisions & Notes:
1. **ADR-005 Accepted:** `Space` remains canonically owned by `apps/panoramas` (Option B).
   - Documented in `docs/adr/0005-space-ownership.md` (renumbered from ADR-002 to avoid collision with the project doc's Pannellum decision).
2. **Migration Continuity:**
   - Extended `apps/panoramas` via forward migration `0002_add_panorama_models_and_constraints.py`.
   - Initial migrations `panoramas.0001_initial` and `bookings.0001_initial` remained 100% untouched.
3. **Domain Models & Constraints Implemented:**
   - `Space`: full fields added (`description`, `display_order`, `is_active`, `active_panorama`, timestamps).
   - `PanoramaImage`: full fields, UUID primary key, and status state machine (`UPLOADED -> PROCESSING -> READY / FAILED`) with invalid transitions rejected by `InvalidStatusTransitionError`.
   - `TablePin`: `pitch` $[-90.0, 90.0]$, `yaw` $[-180.0, 180.0]$, `capacity > 0` CheckConstraints, and `panorama_image` FK.
4. **TablePin Deletion Protection (PROTECT):**
   - Updated `Booking.table_pin` to `on_delete=models.PROTECT` via forward migration `bookings.0002_protect_table_pin_deletion.py`.
   - Added `TablePin.delete()` guard and `TablePin.deactivate()` soft-delete helper. Pins with existing bookings cannot be deleted via CASCADE.
