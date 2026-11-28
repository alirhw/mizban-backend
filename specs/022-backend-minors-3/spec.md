# Feature Spec: T-046 Backend Minors Batch 3 & Admin Venue List

**Task:** T-046  
**Status:** Implemented  
**Database Migrations:** None  
**OpenAPI Contract Changes:** Yes (`api/openapi.snapshot.json` updated for `m11`, `m15`, `m35` only)

---

## Requirements

- **REQ-T046-001 (`m2` — Public Slots Visibility & Date Validation):**
  `GET /api/v1/scheduling/venues/{venue_id}/slots` (`apps/scheduling/api.py:get_slots`) shall look up the venue via `Venue.objects.public()` and return `404` when the venue is unapproved or lacks an active subscription. Invalid `date` query parameter values (non-ISO/non-Jalali strings or out-of-range dates) shall return HTTP `422` (`ValidationError`) rather than an unhandled `ValueError` (`500`).

- **REQ-T046-002 (`m3` — Atomic OTP Rate Limiting & Verify Attempts):**
  `request_otp` and `verify_otp` (`apps/accounts/services.py`) shall execute rate-limit checks/increments and verification attempt increments/burns atomically in Redis via Lua scripts (`_OTP_RATE_LIMIT_LUA`, `_OTP_VERIFY_LUA`) so concurrent requests cannot bypass the 3-requests/10-minute cap or the 5-attempt burn threshold. IP extraction logic remains unchanged.

- **REQ-T046-003 (`m5` — Subscription `starts_at` Enforcement):**
  Subscription activity checks across `Venue.has_active_subscription` (`apps/venues/models.py`), `VenueQuerySet.public` (`apps/venues/managers.py`), `list_owner_venues`, and `get_owner_venue_subscription` (`apps/venues/services.py`) shall require both `starts_at <= now` and `expires_at > now`.

- **REQ-T046-004 (`m7` — Bulk Admin Approve/Reject Notifications):**
  `VenueAdmin.approve_selected_venues` and `VenueAdmin.reject_selected_venues` (`apps/venues/admin.py`) shall create `VENUE_APPROVED` and `VENUE_REJECTED` owner notifications using `apps.notifications.services.create_notification` inside `transaction.atomic()`, matching single-venue `approve_venue` / `reject_venue`.

- **REQ-T046-005 (`m8` — Venue Detail Cache Invalidation & Subscription Liveness):**
  `OperatingHoursAdmin` and `DesignAddonAdmin` (`apps/venues/admin.py`) shall invalidate the parent venue's cache on `save_model` and `delete_model` via `transaction.on_commit()`. `get_public_venue_by_slug` (`apps/venues/services.py`) shall re-verify `Venue.objects.public().filter(slug=slug).exists()` on cached reads and evict + raise `Http404` immediately if the venue is no longer public.

- **REQ-T046-006 (`m10` — Venue Slug Creation Race):**
  `create_venue_for_owner` (`apps/venues/services.py`) shall perform slug allocation inside `transaction.atomic()` and retry with an incremented numeric suffix inside savepoints on slug `IntegrityError` (bounded attempts) rather than failing with `500` or `422`.

- **REQ-T046-007 (`m11` — Masked Customer Phone Only for CONFIRMED Bookings):**
  `list_owner_venue_bookings` (`apps/venues/services.py`) and `OwnerBookingOut` (`apps/venues/schemas.py`) shall return `customer_phone_masked` only when `booking.status == BookingStatus.CONFIRMED`, and `None` (`str | None`) for all other booking statuses.

- **REQ-T046-008 (`m14` — `callback_url` Validation at Payment Initiation):**
  `initiate_payment` (`apps/billing/api.py`) shall validate `payload.callback_url` against the same `validate_callback_url` allowlist used by `_resolve_safe_dev_redirect_url` (relative paths excluding `//`, request origin, `http://127.0.0.1:3000`, `http://localhost:3000`, and `settings.FRONTEND_ORIGIN`), rejecting disallowed URLs with HTTP `422`.

- **REQ-T046-009 (`m15` — Public Venue List Pagination):**
  `GET /api/v1/venues/` (`apps/venues/api.py:list_public`, `apps/venues/services.py:list_public_venues`) shall accept `limit` (default `50`, clamped `[1, 100]`) and `offset` (default `0`, clamped `>= 0`).

- **REQ-T046-010 (`m35` — Admin Venue List Endpoint):**
  `GET /api/v1/venues/admin/venues` (`apps/venues/api.py:list_admin_venues_endpoint`, `apps/venues/services.py:list_admin_venues`, `apps/venues/schemas.py:VenueAdminItemOut`) shall require `ADMIN` role or `is_staff=True` and return all venues regardless of status ordered by `name, id`, paginated by `limit` (default `50`, max `100`) and `offset` (default `0`), with fields `id`, `name`, `slug`, `is_approved`, and `review_status`.
