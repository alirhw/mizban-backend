# Spec 012 - Venue Review Workflow, Submission & Rejection Reason (FR-33 / FR-37 / FR-39)
Status: Draft (G1 Pending) | Owner: Product / Venue Platform | Lane: Standard | Implements: FR-33, FR-37, FR-39, BR-005 (BR-05) | Architecture: ARCH-001, ARCH-002, ARCH-004, ARCH-006

## 1. Problem and goal
Currently, `Venue` only has a boolean `is_approved` flag (`apps/venues/models.py`), so venue owners have no explicit way to submit a completed venue for review, cannot tell whether an unapproved venue is still a draft, awaiting admin review, or rejected, and receive no rejection reason explaining what to fix. This feature introduces a four-state `VenueReviewStatus` machine (`DRAFT`, `PENDING_REVIEW`, `APPROVED`, `REJECTED`), an owner submit endpoint, and a mandatory admin rejection reason while keeping `is_approved` synchronized as the single source of truth for **BR-005** public visibility.

## 2. User stories
- **US-01** As a venue owner, I want to submit my `DRAFT` or `REJECTED` venue for admin review, so that a platform administrator knows my venue is ready to be inspected and approved.
- **US-02** As a venue owner, I want to see my venue's current `review_status`, `submitted_for_review_at` timestamp, and any `rejection_reason` in my owner venue responses, so that I can fix reported issues on a `REJECTED` venue and resubmit it (**FR-37**).
- **US-03** As a platform admin, I want to provide a mandatory, non-blank `reason` (up to 1000 characters) when rejecting a venue, so that the owner receives actionable feedback (**FR-39**).
- **US-04** As a platform admin, I want to approve a `DRAFT`, `PENDING_REVIEW`, or `REJECTED` venue, clearing any prior `rejection_reason` and setting `is_approved=True` (**BR-005**), so that the venue becomes publicly visible once its subscription is active.
- **US-05** As a customer or public visitor, I want `rejection_reason`, `review_status`, and `submitted_for_review_at` to remain strictly private to owners and admins, never exposed in public catalogue endpoints.

## 3. Requirements (EARS)
- **REQ-REV-001** **Four-state review machine & model fields (`apps/venues/models.py`):**
  The `Venue` model shall define `VenueReviewStatus(models.TextChoices)` with states `DRAFT`, `PENDING_REVIEW`, `APPROVED`, and `REJECTED`, and shall add (via one forward migration `0004_*` in `apps/venues/migrations/`):
  - `review_status`: `CharField` with `choices=VenueReviewStatus.choices`, `default=VenueReviewStatus.DRAFT`
  - `rejection_reason`: `TextField(blank=True, default="")`
  - `submitted_for_review_at`: `DateTimeField(null=True, blank=True)`
- **REQ-REV-002** **`is_approved` synchronization (`BR-005`):**
  `Venue.is_approved` shall remain the source of truth for public visibility (`VenueQuerySet.public()` in `apps/venues/managers.py` and `Venue.is_publicly_visible` in `apps/venues/models.py`) and shall be kept synchronized with `review_status` in `apps/venues/services.py` (and `apps/venues/admin.py` bulk actions):
  - `review_status == APPROVED` <=> `is_approved=True`
  - `review_status in (DRAFT, PENDING_REVIEW, REJECTED)` <=> `is_approved=False`
- **REQ-REV-003** **Service-layer & transaction boundaries (`ARCH-001`, `ARCH-002`, `ARCH-006`):**
  All review state transitions (owner submit, admin approve, admin reject) shall live in `apps/venues/services.py`, execute inside `transaction.atomic()` with `select_for_update()` on the target `Venue` row, and store UTC timestamps via `django.utils.timezone.now()`. Ninja views in `apps/venues/api.py` shall only authenticate, validate schemas, delegate to `services.py`, and return typed responses.
- **REQ-REV-004** **Owner submit endpoint (`POST /api/v1/venues/owner/venues/{venue_id}/submit` -> `200` `VenueOwnerOut`, no request body):**
  When an authenticated `VENUE_OWNER` (who owns the venue) or `ADMIN` submits a venue:
  - Unauthenticated callers shall receive `401`.
  - Non-owners or `CUSTOMER` users shall receive `403 FORBIDDEN`.
  - Non-existent `venue_id` shall receive `404 NOT_FOUND`.
  - If `venue.review_status` is `DRAFT` or `REJECTED`, the system shall set `review_status = VenueReviewStatus.PENDING_REVIEW`, `is_approved = False`, `rejection_reason = ""`, and `submitted_for_review_at = timezone.now()`, save the changes, schedule `invalidate_venue_cache(venue.id, venue.slug)` via `transaction.on_commit(...)` (**ARCH-004**), and return HTTP `200` with `VenueOwnerOut`.
  - If `venue.review_status` is `PENDING_REVIEW` or `APPROVED`, the system shall raise `VenueNotSubmittableError` (`core/exceptions.py`: `error_code="VENUE_NOT_SUBMITTABLE"`, HTTP `409`) without mutating the venue.
- **REQ-REV-005** **No cross-app preconditions on submit:**
  Submitting a venue for review shall NOT enforce cross-app preconditions (such as active subscription payment, uploaded 360 panoramas, or placed table pins); those readiness checks are performed by the platform admin during **FR-39** review.
- **REQ-REV-006** **Owner edit behavior unchanged (`update_venue_for_owner`):**
  `update_venue_for_owner` in `apps/venues/services.py` shall remain unchanged so owners can edit `REJECTED` (and `DRAFT`) venues to fix issues per **FR-37**, and `VenueUpdateIn` (`apps/venues/schemas.py`) shall continue to forbid modifying `is_approved`, `review_status`, `rejection_reason`, or `submitted_for_review_at`.
- **REQ-REV-007** **Admin reject endpoint (`POST /api/v1/venues/admin/venues/{venue_id}/reject` -> `200` `VenueApprovalOut`):**
  - The endpoint shall require a JSON body matching `VenueRejectIn(Schema)` with `ConfigDict(extra="forbid")` and `reason: str`.
  - `reason` shall be stripped of leading/trailing whitespace, must be non-empty after stripping (`len >= 1`), and must not exceed `1000` characters; missing body, blank/whitespace-only `reason`, `reason` > 1000 chars, or unknown extra fields shall be rejected with `422 VALIDATION_ERROR`.
  - Non-admin callers (`not (is_staff or role == ADMIN)`) shall receive `403 FORBIDDEN`; unauthenticated callers shall receive `401`; non-existent `venue_id` shall receive `404 NOT_FOUND`.
  - On valid input, the system shall set `review_status = VenueReviewStatus.REJECTED`, `is_approved = False`, and `rejection_reason = stripped_reason`, invalidate the venue public cache via `transaction.on_commit(...)` (**ARCH-004**), and return HTTP `200` with `VenueApprovalOut`.
- **REQ-REV-008** **Admin approve endpoint (`POST /api/v1/venues/admin/venues/{venue_id}/approve` -> `200` `VenueApprovalOut`, no request body):**
  - Non-admin callers shall receive `403 FORBIDDEN`; unauthenticated callers shall receive `401`; non-existent `venue_id` shall receive `404 NOT_FOUND`.
  - Allowed from `DRAFT`, `PENDING_REVIEW`, or `REJECTED` (and remains `APPROVED` if already `APPROVED`), the system shall set `review_status = VenueReviewStatus.APPROVED`, `is_approved = True`, and `rejection_reason = ""`, invalidate the venue public cache via `transaction.on_commit(...)` (**ARCH-004**), and return HTTP `200` with `VenueApprovalOut`.
- **REQ-REV-009** **Response schemas & public privacy (`apps/venues/schemas.py`):**
  - `VenueOwnerOut` shall include `review_status: str`, `rejection_reason: str`, and `submitted_for_review_at: datetime | None`.
  - `VenueApprovalOut` shall include `review_status: str` and `rejection_reason: str = ""` (alongside `id`, `slug`, `is_approved`, `message`).
  - `VenuePublicItemOut` and `VenuePublicDetailOut` shall **NEVER** include `rejection_reason`, `review_status`, or `submitted_for_review_at`.

## 4. Business rules touched
- **FR-33** — Venue owner submits a completed venue for platform admin review.
- **FR-37** — Venue owner views rejection reason and edits a rejected venue to resubmit.
- **FR-39** — Platform admin reviews, approves, or rejects a venue with a mandatory rejection reason.
- **BR-005 (BR-05)** — A venue is publicly visible/bookable only when `is_approved=True` (`review_status == APPROVED`) AND its `VenueSubscription` is active.
- **ARCH-001 / ARCH-002** — State transitions live in `apps/venues/services.py` inside `transaction.atomic()` with `select_for_update()`.
- **ARCH-004** — Public venue metadata cache (`venue:metadata:{venue_id}` and `venue:metadata:slug:{slug}`) is invalidated via `transaction.on_commit()`.
- **ARCH-006** — `submitted_for_review_at` is stored in UTC via `timezone.now()`.

## 5. Non-functional targets
- **Security / IDOR / Mass assignment:** Unauthenticated requests return `401`; `CUSTOMER` and non-owner `VENUE_OWNER` callers on `/submit` return `403`; non-admin callers on `/approve` and `/reject` return `403`; `VenueRejectIn` uses `extra="forbid"`; public endpoints never leak `rejection_reason` or `review_status`.
- **Data integrity:** Forward-only migration `apps/venues/migrations/0004_*.py` adds `review_status` (default `DRAFT`), `rejection_reason` (default `""`), and `submitted_for_review_at` (`null=True, blank=True`) cleanly on PostgreSQL without breaking existing rows.
- **Contract & tests:** `python manage.py check`, `pytest apps/venues/tests/` (PostgreSQL), and `./check-contract.sh` (with `api/openapi.snapshot.json` updated under protected-path review) pass with 0 failures and 0 skipped tests.

## 6. Acceptance criteria (Gherkin)

```gherkin
Scenario: 1. Newly created venue starts in DRAFT with empty rejection_reason
  Given an authenticated VENUE_OWNER
  When the owner creates a venue via POST /api/v1/venues/owner/venues
  Then HTTP 201 is returned with VenueOwnerOut having:
    | review_status           | DRAFT |
    | is_approved             | false |
    | rejection_reason        | ""    |
    | submitted_for_review_at | null  |

Scenario: 2. Owner submits a DRAFT venue for review (no cross-app preconditions)
  Given a VENUE_OWNER owns Venue A in review_status="DRAFT" with no subscription, no panoramas, and no tables
  When the owner calls POST /api/v1/venues/owner/venues/<venue_a_id>/submit with no body
  Then HTTP 200 is returned with VenueOwnerOut having:
    | review_status    | PENDING_REVIEW |
    | is_approved      | false          |
    | rejection_reason | ""             |
    And submitted_for_review_at is a non-null UTC timestamp
    And Venue A's public metadata cache is invalidated on commit.

Scenario: 3. Owner cannot submit a PENDING_REVIEW or APPROVED venue (409 VENUE_NOT_SUBMITTABLE)
  Given a VENUE_OWNER owns Venue A in review_status="PENDING_REVIEW" and Venue B in review_status="APPROVED"
  When the owner calls POST /api/v1/venues/owner/venues/<venue_a_id>/submit
  Then HTTP 409 is returned with error_code "VENUE_NOT_SUBMITTABLE"
  When the owner calls POST /api/v1/venues/owner/venues/<venue_b_id>/submit
  Then HTTP 409 is returned with error_code "VENUE_NOT_SUBMITTABLE".

Scenario: 4. Admin rejects a venue with a mandatory reason and owner sees it
  Given Venue A is in review_status="PENDING_REVIEW"
  When an ADMIN calls POST /api/v1/venues/admin/venues/<venue_a_id>/reject with {"reason": "  Missing 360 panorama for main hall.  "}
  Then HTTP 200 is returned with VenueApprovalOut having:
    | review_status    | REJECTED                                |
    | is_approved      | false                                   |
    | rejection_reason | Missing 360 panorama for main hall.     |
    And GET /api/v1/venues/owner/venues/<venue_a_id> returns the same review_status and rejection_reason
    And GET /api/v1/venues/<venue_a_slug> returns 404 (not publicly visible per BR-005).

Scenario: 5. Admin reject validation enforces non-blank reason <= 1000 chars and extra="forbid"
  Given an authenticated ADMIN and Venue A
  When the admin calls POST /api/v1/venues/admin/venues/<venue_a_id>/reject with:
    - no body
    - {"reason": "   "}
    - {"reason": "<1001 chars>"}
    - {"reason": "Valid reason", "extra_field": true}
  Then HTTP 422 with error_code "VALIDATION_ERROR" is returned for each request.

Scenario: 6. Owner edits a REJECTED venue and resubmits it, clearing rejection_reason
  Given Venue A is in review_status="REJECTED" with rejection_reason="Bad address"
  When the owner calls PUT /api/v1/venues/owner/venues/<venue_a_id> with {"address": "123 Valiasr St"}
  Then HTTP 200 is returned with updated address and review_status still "REJECTED"
  When the owner calls POST /api/v1/venues/owner/venues/<venue_a_id>/submit
  Then HTTP 200 is returned with review_status="PENDING_REVIEW", rejection_reason="", and updated submitted_for_review_at.

Scenario: 7. Admin approves a DRAFT, PENDING_REVIEW, or REJECTED venue and clears rejection_reason
  Given Venue A is in review_status="REJECTED" with rejection_reason="Old reason" and has an active VenueSubscription
    And Venue A's public detail is not visible (404)
  When an ADMIN calls POST /api/v1/venues/admin/venues/<venue_a_id>/approve with no body
  Then HTTP 200 is returned with VenueApprovalOut having:
    | review_status    | APPROVED |
    | is_approved      | true     |
    | rejection_reason | ""       |
    And GET /api/v1/venues/<venue_a_slug> returns HTTP 200
    And the public response payload does NOT contain "rejection_reason", "review_status", or "submitted_for_review_at".

Scenario: 8. Authorization & IDOR isolation
  Given Venue A is owned by Owner A
  When Owner B or a CUSTOMER calls POST /api/v1/venues/owner/venues/<venue_a_id>/submit
  Then HTTP 403 is returned
  When an unauthenticated caller calls POST /api/v1/venues/owner/venues/<venue_a_id>/submit
  Then HTTP 401 is returned
  When Owner A or a CUSTOMER calls POST /api/v1/venues/admin/venues/<venue_a_id>/approve or /reject
  Then HTTP 403 is returned
  When an ADMIN calls /submit, /approve, or /reject for non-existent venue_id=999999
  Then HTTP 404 is returned.
```

## 7. Out of scope (explicit)
- **Owner/admin notifications (T-039 / FR-36):** Sending SMS/email/in-app notifications to admins on submit or to owners on approve/reject is deferred to **T-039**.
- **Frontend owner review-status & rejection-reason panel (`frontend/`):** UI changes to display `review_status`, `rejection_reason`, and a "Submit for Review" action belong to a separate frontend task.
- **Auto-resetting `APPROVED` on owner edit:** Changing `update_venue_for_owner` to demote an already `APPROVED` venue back to `DRAFT` or `PENDING_REVIEW` upon edit is explicitly out of scope for **T-036**.

## 8. Open questions
- **Auto-demotion of `APPROVED` venues on owner edit:** Should future edits to core profile fields on an `APPROVED` venue require re-review? *Closed for T-036 (not in T-036; follow-up product decision).*
