# Tasks — Feature 004 Panoramas & Table Pins

| Task ID | Description | Owner | Status | Dependencies |
| :--- | :--- | :--- | :--- | :--- |
| **T-015** | Resolve Space Ownership and Define Panorama Domain Models | `web-architect` / `database-engineer` | Done (Gate G4 Approved) | T-014 |
| **T-016** | 360 Panorama Upload Endpoint & Validation (Magic bytes, UUID, 202) | `backend-api-engineer` | Next | T-015 |
| **T-017** | Celery Asynchronous Image Conversion Pipeline (WebP, thumb, cleanup) | `media-engineer` | Pending | T-016 |
| **T-018** | Venue Owner Panorama & Table Pin Editor API (Space CRUD, Pin drops) | `backend-api-engineer` | Pending | T-017 |
| **T-019** | Customer Panorama Viewer & Visual Table Selection API | `backend-api-engineer` | Pending | T-018 |

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
