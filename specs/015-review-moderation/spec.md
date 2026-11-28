# Spec 015 - Review Moderation: Admin Hide/Show (FR-41, BR-13)
Status: Draft | Owner: Product / Reviews Platform | Lane: Standard | Implements: FR-41, BR-13, NFR-28 | Architecture: ARCH-001, ARCH-006

## 1. Problem and goal
Platform administrators currently have no API to list submitted reviews across venues or moderate inappropriate reviews by hiding them from public view and restoring them if needed. This feature adds admin-only moderation endpoints under `/api/v1/reviews/admin/` to list reviews with optional venue and visibility filters and toggle `is_visible` via hide/show actions (**FR-41**), while preserving every review row as audit data (no deletion) and continuing to mask customer PII (**BR-13**, **NFR-28**).

## 2. User stories
- **US-01** As a platform admin, I want to list submitted reviews with optional `venue_id` and `is_visible` filters, so that I can inspect both visible and hidden reviews across the platform.
- **US-02** As a platform admin, I want to hide or show a specific review by toggling `is_visible` (**FR-41**), so that inappropriate reviews are removed from public display without deleting the underlying audit record.
- **US-03** As a customer or venue owner, I want moderation actions to be restricted strictly to platform admins, so that venue owners cannot suppress unfavorable reviews of their own venues and customers cannot self-moderate.

## 3. Requirements (EARS)
- **REQ-REV-MOD-001** **Service-layer & zero-schema-change boundary (`ARCH-001`):**
  All admin moderation and serialization logic shall live in `apps/reviews/services.py`, with Pydantic output schema in `apps/reviews/schemas.py` and thin Ninja endpoints in `apps/reviews/api.py` (under the existing `/api/v1/reviews` router). This feature shall introduce **no** model changes, **no** migrations, and **no** caching changes.
- **REQ-REV-MOD-002** **Admin-only authorization (`is_staff` or `UserRole.ADMIN`):**
  For all `/api/v1/reviews/admin/...` endpoints (`auth=auth`):
  - Unauthenticated callers shall receive `401`.
  - Authenticated callers where neither `user.is_staff` is `True` nor `user.role == UserRole.ADMIN` shall raise `PermissionDenied` (`403 FORBIDDEN`).
  - Venue owners (`UserRole.VENUE_OWNER`, even for their own venue) and customers (`UserRole.CUSTOMER`, even for their own review) shall **never** be permitted to list admin reviews or hide/show any review (`403 FORBIDDEN`).
- **REQ-REV-MOD-003** **Hide/show-only rule & no deletion (`FR-41`):**
  A `Review` row shall **never** be deleted (no `DELETE` endpoint on `/api/v1/reviews`). Admin moderation shall mutate `is_visible` only via `review.save(update_fields=["is_visible"])`, retaining the row in the database as audit data.
- **REQ-REV-MOD-004** **Admin list reviews (`GET /api/v1/reviews/admin/` -> `200` `list[ReviewAdminOut]`, `auth=auth`):**
  - Enforces **REQ-REV-MOD-002** (admin only).
  - Query parameters:
    - `venue_id: int | None = None` — when provided, filters to `booking__table_pin__venue_id=venue_id`.
    - `is_visible: bool | None = None` — when provided, filters to `is_visible=is_visible`.
    - `limit: int = 20` (clamped to `1..100` in `services.py`).
    - `offset: int = 0` (clamped to `>= 0` in `services.py`).
  - Ordered by `-created_at`, using `select_related("booking__table_pin", "booking__customer")` to avoid N+1 queries.
  - Returns `200` with `list[ReviewAdminOut]`.
- **REQ-REV-MOD-005** **Hide review (`POST /api/v1/reviews/admin/{review_id}/hide` -> `200` `ReviewAdminOut`, `auth=auth`):**
  - Enforces **REQ-REV-MOD-002** (admin only), with no request body.
  - If `Review(pk=review_id)` does not exist -> `404 NOT_FOUND`.
  - If `review.is_visible` is `True`, sets `review.is_visible = False` and persists with `review.save(update_fields=["is_visible"])`.
  - **Idempotent no-op:** If `review.is_visible` is already `False`, performs no error and returns `200` with the current `ReviewAdminOut` state.
- **REQ-REV-MOD-006** **Show review (`POST /api/v1/reviews/admin/{review_id}/show` -> `200` `ReviewAdminOut`, `auth=auth`):**
  - Enforces **REQ-REV-MOD-002** (admin only), with no request body.
  - If `Review(pk=review_id)` does not exist -> `404 NOT_FOUND`.
  - If `review.is_visible` is `False`, sets `review.is_visible = True` and persists with `review.save(update_fields=["is_visible"])`.
  - **Idempotent no-op:** If `review.is_visible` is already `True`, performs no error and returns `200` with the current `ReviewAdminOut` state.
- **REQ-REV-MOD-007** **`ReviewAdminOut` schema & PII protection (`apps/reviews/schemas.py`, `BR-13`, `NFR-28`):**
  `ReviewAdminOut(Schema)` (`model_config = ConfigDict(extra="forbid")`) shall expose exactly:
  - `id: int`
  - `booking_id: int`
  - `venue_id: int`
  - `table_number: str`
  - `rating: int`
  - `text: str`
  - `reviewer_name: str` (first name only, or `"Customer"` when blank/absent)
  - `created_at: datetime`
  - `is_visible: bool`
  `ReviewAdminOut` shall **never** expose customer `phone`, `email`, or `last_name`.

## 4. Business rules touched
- **FR-41** — Admin moderation of reviews is hide/show-only (`is_visible` toggle); reviews are never deleted.
- **BR-13 / NFR-28** — Review payloads never expose customer PII (`phone`, `last_name`, `email`); `reviewer_name` uses first name only or `"Customer"`.
- **ARCH-001** — Business logic, authorization, and `update_fields=["is_visible"]` persistence live in `apps/reviews/services.py`; Ninja views in `apps/reviews/api.py` stay thin.
- **ARCH-006** — `created_at` remains UTC.

## 5. Non-functional targets
- **Security & Privacy (RBAC / PII):** Unauthenticated requests to `/api/v1/reviews/admin/...` return `401`; non-admin authenticated users (`CUSTOMER`, `VENUE_OWNER` without `is_staff`) receive `403 FORBIDDEN`; `ReviewAdminOut` uses `extra="forbid"` and never serializes `phone`, `email`, or `last_name`.
- **Audit Integrity:** Zero `DELETE` endpoints; `review.save(update_fields=["is_visible"])` only updates `is_visible` on state change and leaves all other fields untouched.
- **Query Efficiency:** Admin list uses `select_related("booking__table_pin", "booking__customer")` with bounded pagination (`limit` clamped `1..100`, `offset >= 0`).
- **Contract & Tests:** `python manage.py check`, `pytest apps/reviews/tests/` (PostgreSQL), and `./check-contract.sh` (after `api/openapi.snapshot.json` update under human gate) pass with 0 failures and 0 skipped tests.

## 6. Acceptance criteria (Gherkin)

```gherkin
Scenario: 1. Admin lists reviews with venue_id, is_visible, and pagination clamping
  Given Venue V1 has Review R1 (is_visible=true) and Review R2 (is_visible=false)
    And Venue V2 has Review R3 (is_visible=true)
    And an authenticated user with role="ADMIN" (or is_staff=true)
  When the admin requests GET /api/v1/reviews/admin/?venue_id=<V1.id>&is_visible=false&limit=200&offset=-5
  Then HTTP 200 is returned with a list containing only R2 serialized as ReviewAdminOut
    And R2 includes id, booking_id, venue_id=V1.id, table_number, rating, text, reviewer_name="Customer", created_at, is_visible=false
    And R2 does NOT include phone, email, or last_name.

Scenario: 2. Admin hides and shows a review (FR-41) and public reads reflect visibility
  Given Review R1 belongs to Venue V1 with is_visible=true and rating=5
    And an authenticated ADMIN user
  When the admin calls POST /api/v1/reviews/admin/<R1.id>/hide with no body
  Then HTTP 200 is returned with ReviewAdminOut having id=R1.id and is_visible=false
    And the Review row R1 still exists in the database
    And GET /api/v1/reviews/venues/<V1.id>/ excludes R1 from reviews, review_count, and average_rating
  When the admin calls POST /api/v1/reviews/admin/<R1.id>/show with no body
  Then HTTP 200 is returned with ReviewAdminOut having id=R1.id and is_visible=true
    And GET /api/v1/reviews/venues/<V1.id>/ includes R1 again.

Scenario: 3. Idempotent no-op on hide/show
  Given Review R1 has is_visible=false and Review R2 has is_visible=true
    And an authenticated ADMIN user
  When the admin calls POST /api/v1/reviews/admin/<R1.id>/hide
  Then HTTP 200 is returned with ReviewAdminOut having id=R1.id and is_visible=false
  When the admin calls POST /api/v1/reviews/admin/<R2.id>/show
  Then HTTP 200 is returned with ReviewAdminOut having id=R2.id and is_visible=true.

Scenario: 4. Auth and admin-only RBAC enforcement (401 / 403 / 404)
  Given Review R1 belongs to Venue V1 owned by VENUE_OWNER O1 and authored by CUSTOMER C1
  When an unauthenticated caller requests GET /api/v1/reviews/admin/ or POST /api/v1/reviews/admin/<R1.id>/hide
  Then HTTP 401 is returned
  When VENUE_OWNER O1 (owner of V1, is_staff=false) or CUSTOMER C1 (author of R1, is_staff=false) calls GET /api/v1/reviews/admin/, POST /api/v1/reviews/admin/<R1.id>/hide, or POST /api/v1/reviews/admin/<R1.id>/show
  Then HTTP 403 with error_code "FORBIDDEN" is returned for each request
  When an authenticated ADMIN calls POST /api/v1/reviews/admin/999999/hide or POST /api/v1/reviews/admin/999999/show
  Then HTTP 404 is returned.
```

## 7. Out of scope (explicit)
- **Frontend admin moderation UI (`frontend/`):** Building the admin moderation table and hide/show controls in Next.js belongs to a separate frontend task.
- **Django Admin registration (`apps/reviews/admin.py`):** Registering `Review` in Django Admin is deferred to a separate follow-up task.
- **Hard-delete of reviews:** Permanently prohibited by **FR-41**; reviews are audit data.

## 8. Open questions
- None; all parameters (`ReviewAdminOut` fields, `is_staff` / `UserRole.ADMIN` check, idempotent 200 behavior, and pagination clamping) are fixed for T-038.

## 9. Frontend Admin Review Moderation UI (Follow-up (e))
- **Route & Navigation:** New client page `frontend/src/app/admin/reviews/page.tsx` and Header link `"مدیریت نظرها"` in `frontend/src/components/Header.tsx` rendered only when `user.role === "ADMIN"`.
- **API Client (`frontend/src/lib/api.ts`):** Hand-written `ReviewAdminOut` (`id`, `booking_id`, `venue_id`, `table_number`, `rating`, `text`, `reviewer_name`, `created_at`, `is_visible`), `listAdminReviews({ venue_id?, is_visible?, limit?, offset? })`, `hideReview(reviewId)`, and `showReview(reviewId)`.
- **Moderation & Privacy Rules:**
  - Filters by venue (`listPublicVenues()`), visibility (`all` / `visible` / `hidden`), and pagination (`limit=20`, `offset`).
  - Hide/show-only: `"پنهان کردن"` on visible rows and `"نمایش دادن"` on hidden rows update the row in place from the returned `ReviewAdminOut` with no extra refetch and no delete button anywhere.
  - Never displays phone numbers or raw `error_code`; `403 FORBIDDEN` renders a Persian admin-only message without redirect loops (allowing `is_staff` users who open `/admin/reviews` directly).
- **Tests:** `frontend/src/lib/__tests__/api.test.ts` and `frontend/src/lib/__tests__/AdminReviews.test.tsx` (Header role visibility, venue/visibility filters, in-place hide/show, 403 Persian message, zero delete buttons).
