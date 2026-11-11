# Design 002 — Venue Catalogue & Owner Operations (Task T-009)

## 1. Summary
Implements Venue Owner Operations, Admin Approval Workflow, Public Listing, and Cache Invalidation for the venues domain.
Builds on T-008 persistence models (`Venue`, `OperatingHours`, `DesignAddon`, `Subscription`) without altering database schema.

## 2. UX & Flows
- **Owner Flow:** Venue owner creates venue profile (`is_approved=False`). Owner can list and edit their own venues.
- **Admin Flow:** Admin reviews unapproved venues and approves/rejects them.
- **Public Flow:** Customers browse only approved venues with active subscriptions (BR-005).

## 3. API Changes
### Public Endpoints (no auth required)
- `GET /api/v1/venues/`: List public venues (`Venue.objects.public()`), filterable by `city` and `venue_type`.
- `GET /api/v1/venues/{slug}`: Public detail of an approved, active venue.

### Owner Endpoints (authenticated, VENUE_OWNER or ADMIN)
- `GET /api/v1/venues/owner/venues`: List venues owned by caller.
- `POST /api/v1/venues/owner/venues`: Create a new venue (`is_approved=False` always).
- `GET /api/v1/venues/owner/venues/{venue_id}`: Retrieve owner's venue.
- `PUT /api/v1/venues/owner/venues/{venue_id}`: Update owner's venue (cannot change `is_approved`).

### Admin Endpoints (authenticated, ADMIN or is_staff)
- `POST /api/v1/venues/admin/venues/{venue_id}/approve`: Mark `is_approved=True`.
- `POST /api/v1/venues/admin/venues/{venue_id}/reject`: Mark `is_approved=False`.

## 4. Data Model Changes
None. Uses existing models from T-008 (`apps/venues/models.py`).

## 5. Schemas
- `VenuePublicItemOut`: `id`, `name`, `slug`, `city`, `venue_type`, `address`, `description`. (NO phone, NO owner details).
- `VenuePublicDetailOut`: inherits `VenuePublicItemOut` + `operating_hours`, `design_addons`.
- `VenueOwnerOut`: includes all fields + `is_approved`, `subscription_status`, `is_publicly_visible`, `created_at`, `updated_at`.
- `VenueCreateIn`: `name`, `city`, `venue_type`, `address`, `description`, optional `slug`.
- `VenueUpdateIn`: optional updates for `name`, `city`, `venue_type`, `address`, `description`.

## 6. Auth & Permissions
- Minimal authenticated identity bridge in `apps/accounts/auth.py`: supports session auth (`django_auth`) and Bearer token / `X-User-Phone` fallback for dev/testing. Gap recorded for T-007.
- `ROLE_VENUE_OWNER` or `ADMIN` required for owner endpoints.
- IDOR check: caller must own venue (`venue.owner_id == user.id`) unless admin.
- `ROLE_ADMIN` or `is_staff` required for approval endpoints.

## 7. Caching & Invalidation (ARCH-004)
- Key format: `venue:metadata:{id}` and `venue:metadata:slug:{slug}`.
- TTL: 3600 seconds.
- Invalidation trigger: on update, approval, or rejection.
- Timing: executed in `django.db.transaction.on_commit` hook so cache is cleared only after DB commit.

## 8. Privacy & Threat Model
- Threat: Public endpoint leaks owner phone numbers (NFR-005 violation). Mitigated by strict Pydantic schemas omitting phone.
- Threat: IDOR — owner A updates owner B's venue. Mitigated by service-layer ownership verification raising `PermissionDenied`.
- Threat: Owner self-approves venue. Mitigated by ignoring/stripping `is_approved` on create/update.
