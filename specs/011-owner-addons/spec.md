# Spec 011 - Venue-Owner Design Add-On Management API (FR-32)
Status: Draft (G1 Pending) | Owner: Product / Venue Platform | Lane: Standard | Implements: FR-32, BR-003 (BR-03), BR-15 | Architecture: ARCH-001, ARCH-002, ARCH-004, ARCH-005

## 1. Problem and goal
Venue owners currently rely on Django Admin to manage decorative design add-ons (flowers, candles, table setup, etc.) for their venues. They need self-service CRUD endpoints under their owner venue namespace so they can create, inspect, update (title, in-person fee, active status), and delete unreferenced add-ons, with immediate public cache invalidation and strict IDOR, delete-protection, and price-snapshot invariants.

## 2. User stories
- **US-01** As a venue owner, I want to list all design add-ons (both active and inactive) for my venue, so that I can review and manage my venue's add-on catalogue.
- **US-02** As a venue owner, I want to create, view, and update a design add-on's `title`, `fee` (in integer Toman, payable in person per **BR-003**), and `is_active` flag, so that customers see accurate, up-to-date offerings on my public venue page.
- **US-03** As a venue owner, I want to delete an unused design add-on, while being prevented from deleting one referenced by existing bookings (receiving a clear `409 ADDON_IN_USE` error so I can deactivate it instead), so that historical booking receipts remain intact.
- **US-04** As the platform system, I want fee edits to never mutate historical `BookingAddon.price_snapshot_toman` or `Booking.amount_in_person_toman` (**BR-15**), and I want every mutation to invalidate the venue's public metadata cache on commit (**ARCH-004**).

## 3. Requirements (EARS)
- **REQ-ADDON-001** **Service-layer ownership (ARCH-001 / ARCH-002):** All design add-on read and write operations shall live in `apps/venues/services.py`; Ninja views in `apps/venues/api.py` shall only authenticate, validate schemas, delegate to `services.py`, and return typed responses. All create, update, and delete mutations shall execute inside `transaction.atomic()`.
- **REQ-ADDON-002** **Owner & IDOR enforcement:** Every add-on endpoint shall require authentication (`auth=auth`, `401` when unauthenticated) and shall resolve the parent venue via `get_owner_venue(user, venue_id)`:
  - If the caller is neither `VENUE_OWNER` nor `ADMIN` (`is_staff` / `UserRole.ADMIN`), or does not own the venue, the system shall return `403 FORBIDDEN`.
  - If `venue_id` does not exist, the system shall return `404 NOT_FOUND`.
- **REQ-ADDON-003** **Venue-scoped add-on lookup (IDOR on `addon_id`):** When accessing a specific `addon_id` (`GET`, `PUT`, `DELETE`), the system shall query exclusively within `venue.design_addons` (i.e. `DesignAddon.objects.filter(venue=venue, id=addon_id)`). If `addon_id` does not exist or belongs to a different venue, the system shall return `404 NOT_FOUND` (never `403`).
- **REQ-ADDON-004** **List owner add-ons (`GET /api/v1/venues/owner/venues/{venue_id}/addons/`):** When an authorized owner requests the add-on list, the system shall return HTTP `200` with `list[DesignAddonOut]` containing all `DesignAddon` rows for that venue (both `is_active=True` and `is_active=False`), ordered by `title` ascending (`Meta.ordering = ["title"]`).
- **REQ-ADDON-005** **Create add-on (`POST /api/v1/venues/owner/venues/{venue_id}/addons/`):** When an authorized owner submits a valid `DesignAddonCreateIn` payload (`ConfigDict(extra="forbid")`: `title: str` max 200 chars and non-empty after `.strip()`, `fee: int >= 0`, `is_active: bool = True`), the system shall create the `DesignAddon` under `venue`, commit the transaction, and return HTTP `201` with `DesignAddonOut`. Unknown fields, blank/whitespace-only `title`, `title` exceeding 200 chars, or negative `fee` shall be rejected with `422 VALIDATION_ERROR`.
- **REQ-ADDON-006** **Retrieve single add-on (`GET /api/v1/venues/owner/venues/{venue_id}/addons/{addon_id}/`):** When an authorized owner requests a single add-on belonging to their venue (whether active or inactive), the system shall return HTTP `200` with `DesignAddonOut`.
- **REQ-ADDON-007** **Update add-on (`PUT /api/v1/venues/owner/venues/{venue_id}/addons/{addon_id}/`):** When an authorized owner submits a valid `DesignAddonUpdateIn` payload (`ConfigDict(extra="forbid")`: `title`, `fee`, and `is_active` all required, with `title` max 200 chars and non-empty after `.strip()`, `fee: int >= 0`), the system shall update the `DesignAddon` row and return HTTP `200` with `DesignAddonOut`.
- **REQ-ADDON-008** **Price snapshot immutability (BR-15):** When an add-on's `fee` is updated via `PUT`, the system shall NOT mutate `BookingAddon.price_snapshot_toman` or `Booking.amount_in_person_toman` on any existing booking. Subsequent new bookings that select the add-on shall snapshot the updated `fee`.
- **REQ-ADDON-009** **Delete add-on & delete protection (`DELETE /api/v1/venues/owner/venues/{venue_id}/addons/{addon_id}/`):**
  - If the `DesignAddon` is not referenced by any `BookingAddon`, the system shall delete the row and return HTTP `204` with an empty body.
  - If the `DesignAddon` is referenced by one or more `BookingAddon` rows (`BookingAddon.design_addon` has `on_delete=models.PROTECT`), catching `ProtectedError` shall raise `AddonInUseError` (`core/exceptions.py`: `error_code="ADDON_IN_USE"`, HTTP `409`), leaving the `DesignAddon` row untouched in the database.
- **REQ-ADDON-010** **Cache invalidation on commit (ARCH-004):** Every successful create, update, and delete shall schedule `invalidate_venue_cache(venue_id, venue.slug)` via `transaction.on_commit(...)` so `GET /api/v1/venues/{slug}` reflects the updated active add-ons immediately after commit.
- **REQ-ADDON-011** **Public vs. owner visibility:**
  - Active add-ons (`is_active=True`) shall appear in `GET /api/v1/venues/{slug}` (`VenuePublicDetailOut.design_addons`) and be selectable during booking creation.
  - Inactive add-ons (`is_active=False`) shall be excluded from `GET /api/v1/venues/{slug}` and appear only in the owner's add-on endpoints (and owner venue detail).
- **REQ-ADDON-012** **No migrations or model changes:** This feature reuses the existing `DesignAddon` model in `apps/venues/models.py` and `DesignAddonOut` in `apps/venues/schemas.py` with zero new migrations.

## 4. Business rules touched
- **FR-32** — Venue owner management of design add-ons (create, list, retrieve, update, delete).
- **BR-003 (BR-03) / ARCH-005** — `DesignAddon.fee` is integer Toman payable in person to the venue, never charged through the online payment gateway.
- **BR-15** — Editing an add-on's `fee` never mutates existing `BookingAddon.price_snapshot_toman` or `Booking.amount_in_person_toman`; new bookings snapshot the updated fee.
- **ARCH-001 / ARCH-002** — Business logic, IDOR checks, and `transaction.atomic()` mutations live in `apps/venues/services.py`.
- **ARCH-004** — Public venue metadata cache (`venue:metadata:{venue_id}` and `venue:metadata:slug:{slug}`) is invalidated via `transaction.on_commit()`.

## 5. Non-functional targets
- **Security / IDOR:** Non-owners and `CUSTOMER` users receive `403`; unauthenticated callers receive `401`; cross-venue `addon_id` lookups return `404`; `extra="forbid"` rejects mass-assignment fields (`venue`, `id`, `image`, etc.) with `422`.
- **Data integrity:** `BookingAddon` `on_delete=models.PROTECT` is preserved; `fee >= 0` enforced at both Pydantic schema and PostgreSQL `CheckConstraint` (`design_addon_fee_non_negative`).
- **Contract & tests:** `python manage.py check`, `pytest apps/venues/tests/test_owner_addons.py` (PostgreSQL), and `./check-contract.sh` (with `api/openapi.snapshot.json` updated under protected-path review) pass with 0 failures and 0 skipped tests.

## 6. Acceptance criteria (Gherkin)

```gherkin
Scenario: 1. Owner lists all add-ons (active + inactive) ordered by title
  Given a VENUE_OWNER owns Venue A with add-ons:
    | title       | fee   | is_active |
    | Candles     | 50000 | false     |
    | Bouquet     | 120000| true      |
  When the owner calls GET /api/v1/venues/owner/venues/<venue_a_id>/addons/
  Then HTTP 200 is returned with 2 DesignAddonOut items ordered ["Bouquet", "Candles"]
    And both active and inactive add-ons are included.

Scenario: 2. Owner creates a design add-on and invalidates public venue cache
  Given a VENUE_OWNER owns an approved, active Venue A whose public detail is cached
  When the owner calls POST /api/v1/venues/owner/venues/<venue_a_id>/addons/ with {"title": "  Rose Petal Setup  ", "fee": 150000}
  Then HTTP 201 is returned with DesignAddonOut (title="Rose Petal Setup", fee=150000, is_active=true)
    And GET /api/v1/venues/<venue_a_slug> immediately includes "Rose Petal Setup".

Scenario: 3. Create validation rejects blank title, oversized title, negative fee, and extra fields
  Given an authenticated VENUE_OWNER for Venue A
  When the owner calls POST /api/v1/venues/owner/venues/<venue_a_id>/addons/ with:
    - {"title": "   ", "fee": 10000}
    - {"title": "<201 chars>", "fee": 10000}
    - {"title": "Candles", "fee": -1}
    - {"title": "Candles", "fee": 10000, "venue_id": 999}
  Then HTTP 422 with error_code "VALIDATION_ERROR" is returned for each invalid payload.

Scenario: 4. Owner retrieves a single add-on (active or inactive)
  Given a VENUE_OWNER owns Venue A with an inactive add-on id=10
  When the owner calls GET /api/v1/venues/owner/venues/<venue_a_id>/addons/10/
  Then HTTP 200 is returned with DesignAddonOut for id=10.

Scenario: 5. Owner updates add-on fee and existing booking snapshots remain immutable (BR-15)
  Given Venue A has add-on id=10 with title="Flowers", fee=100000, is_active=true
    And an existing Booking has BookingAddon(design_addon_id=10, price_snapshot_toman=100000) and amount_in_person_toman=100000
  When the owner calls PUT /api/v1/venues/owner/venues/<venue_a_id>/addons/10/ with {"title": "Premium Flowers", "fee": 200000, "is_active": true}
  Then HTTP 200 is returned with DesignAddonOut (title="Premium Flowers", fee=200000, is_active=true)
    And the existing BookingAddon.price_snapshot_toman remains 100000
    And the existing Booking.amount_in_person_toman remains 100000
    And a new booking created after the update snapshots price_snapshot_toman=200000
    And the venue public cache is invalidated.

Scenario: 6. Deactivating an add-on hides it from public detail but keeps it in owner list
  Given Venue A has an active add-on id=10
  When the owner calls PUT /api/v1/venues/owner/venues/<venue_a_id>/addons/10/ with {"title": "Flowers", "fee": 100000, "is_active": false}
  Then HTTP 200 is returned with is_active=false
    And GET /api/v1/venues/<venue_a_slug> does NOT include add-on id=10
    And GET /api/v1/venues/owner/venues/<venue_a_id>/addons/ still includes add-on id=10.

Scenario: 7. Deleting an unused add-on succeeds with 204 and invalidates cache
  Given Venue A has add-on id=11 with zero BookingAddon references
    And Venue A's public detail is cached
  When the owner calls DELETE /api/v1/venues/owner/venues/<venue_a_id>/addons/11/
  Then HTTP 204 is returned with an empty body
    And DesignAddon id=11 no longer exists in PostgreSQL
    And Venue A's public cache is invalidated.

Scenario: 8. Deleting a referenced add-on fails with 409 ADDON_IN_USE
  Given Venue A has add-on id=10 referenced by at least one BookingAddon
  When the owner calls DELETE /api/v1/venues/owner/venues/<venue_a_id>/addons/10/
  Then HTTP 409 is returned with error_code "ADDON_IN_USE"
    And DesignAddon id=10 remains untouched in PostgreSQL.

Scenario: 9. Security & IDOR isolation
  Given Venue A is owned by Owner A and has add-on id=10
    And Venue B is owned by Owner B and has add-on id=20
  When Owner B calls GET/POST/PUT/DELETE on Venue A's addons endpoints
  Then HTTP 403 is returned
  When Owner A calls GET/PUT/DELETE on /api/v1/venues/owner/venues/<venue_a_id>/addons/20/ (Venue B's addon_id)
  Then HTTP 404 is returned (not 403)
  When a CUSTOMER user calls any owner addons endpoint
  Then HTTP 403 is returned
  When an unauthenticated caller calls any owner addons endpoint
  Then HTTP 401 is returned.
```

## 7. Out of scope (explicit)
- **Add-on `image` upload:** Managing `DesignAddon.image` remains Django Admin only in this release.
- **Frontend owner add-on management UI:** Building the owner add-on management page in `frontend/` is a separate follow-up task.
- **Database migrations / model changes:** No changes to `DesignAddon` or `BookingAddon` models.

## 8. Open questions
- None. All behaviour is fully specified by FR-32, BR-003, BR-15, and existing `get_owner_venue` / `invalidate_venue_cache` patterns.
