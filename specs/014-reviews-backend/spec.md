# Spec 014 - Reviews Backend: Submit & Public/Customer Reads (FR-24 / FR-25)
Status: Draft (G1 Pending) | Owner: Product / Reviews Platform | Lane: Standard | Implements: FR-24, FR-25, BR-09, BR-13, NFR-28 | Architecture: ARCH-001, ARCH-002, ARCH-006

## 1. Problem and goal
Customers who have completed a reservation at a venue currently have no way to submit a rating and review for their booking, and prospective visitors browsing a venue or specific table pin have no way to read past customer reviews or see a table/venue's average rating. This feature implements the `Review` domain model in `apps/reviews/` (`0001_initial.py`), booking-eligibility enforcement (**BR-09**), customer review submission and personal history endpoints, and public venue/table review list endpoints with privacy-safe display names (**BR-13**, **NFR-28**) and read-time visible-only average rating calculation.

## 2. User stories
- **US-01** As a customer with a completed booking whose slot has ended, I want to submit one rating and review text for that booking (**FR-24**, **BR-09**), so that I can share my experience with other diners.
- **US-02** As a customer, I want to view all reviews I have submitted—including any hidden by moderation—so that I have a complete record of my feedback.
- **US-03** As a public visitor, I want to read paginated visible reviews and the average rating for a venue or a specific table pin (**FR-25**), so that I can make an informed reservation choice.
- **US-04** As a customer, I want only my first name (or `"Customer"` when blank/absent) shown on public reviews (**BR-13**, **NFR-28**), so that my phone number, last name, and email are never exposed.

## 3. G1 Decided Values (**PROJECT decisions, NOT SRS facts**)
> [!IMPORTANT]
> The SRS specifies *"one rating and a text"* without fixing the numeric scale, text length bounds, or public reviewer display-name rule. The following three parameters are explicit **PROJECT decisions (G1), NOT SRS facts**:
> 1. **Rating scale:** Integer `1–5` (`StrictInt`, `ge=1`, `le=5`) — booleans, floats, and strings are rejected.
> 2. **Review text:** Required, stripped of leading/trailing whitespace, non-blank (`len >= 1` after stripping), maximum `1000` characters.
> 3. **Public display name (`reviewer_name`):** Customer's **FIRST NAME only** (stripped, via `getattr(customer, "first_name", "")`), falling back to `"Customer"` when blank or absent on the `User` model; **never** expose `phone`, `last_name`, or `email` (**BR-13** / **NFR-28**).

## 4. Requirements (EARS)
- **REQ-REV-001** **`Review` model & initial migration (`apps/reviews/models.py`, `apps/reviews/migrations/0001_initial.py`):**
  The `Review` model shall be defined with:
  - `booking`: `ForeignKey("bookings.Booking", on_delete=models.CASCADE, related_name="reviews")` — **no** duplicate `venue` or `table_pin` foreign keys (both are derived via `booking.venue` and `booking.table_pin`).
  - `rating`: `IntegerField()`
  - `text`: `TextField()` (max 1000 characters enforced in schema and service validation)
  - `is_visible`: `BooleanField(default=True, db_index=True)`
  - `created_at`: `DateTimeField(auto_now_add=True)` (**ARCH-006** UTC)
  - `Meta.ordering = ["-created_at"]`
  - `Meta.constraints`:
    - `UniqueConstraint(fields=["booking"], name="unique_review_per_booking")`
    - `CheckConstraint(condition=Q(rating__gte=1, rating__lte=5), name="review_rating_between_1_and_5")`
- **REQ-REV-002** **Service-layer & transaction boundaries (`ARCH-001`, `ARCH-002`, `ARCH-006`):**
  All review creation and query logic shall live in `apps/reviews/services.py`. Ninja views in `apps/reviews/api.py` (already mounted at `/api/v1/reviews` in `config/api.py`) shall only authenticate, validate schemas, delegate to `services.py`, and return typed responses.
- **REQ-REV-003** **Submit review (`POST /api/v1/reviews/` -> `201` `ReviewMineOut`, `auth=auth`):**
  - Unauthenticated callers shall receive `401`.
  - Authenticated callers whose `role != UserRole.CUSTOMER` shall raise `PermissionDenied` (`403 FORBIDDEN`).
  - Request payload `ReviewCreateIn(Schema)` (`ConfigDict(extra="forbid")`) shall require:
    - `booking_id: int`
    - `rating: StrictInt = Field(..., ge=1, le=5)`
    - `text: str` (stripped, non-blank `len >= 1`, `len <= 1000`).
    Invalid types (e.g., `bool`/`float`/`str` for `rating`), out-of-range ratings, blank/whitespace-only `text`, `text` > 1000 chars, or unknown extra fields shall return `422 VALIDATION_ERROR`.
  - **Eligibility & concurrency check (`BR-09`, `ARCH-002`):** Inside `transaction.atomic()`, the service shall lock the target `Booking` row with `Booking.objects.select_for_update()`:
    1. If the booking does not exist -> `404 NOT_FOUND`.
    2. If `booking.customer_id != user.id` -> raise `ReviewNotAllowedError` (`403 REVIEW_NOT_ALLOWED`).
    3. If `booking.status != BookingStatus.COMPLETED` OR `booking.end_at > timezone.now()` -> raise `ReviewNotEligibleError` (`409 REVIEW_NOT_ELIGIBLE`).
    4. If a `Review` already exists for `booking` -> raise `ReviewAlreadyExistsError` (`409 REVIEW_ALREADY_EXISTS`).
  - On success, the system shall create the `Review` with `is_visible=True` and return HTTP `201` with `ReviewMineOut`.
- **REQ-REV-004** **Visible-only read-time `average_rating` rule:**
  For public review reads, `average_rating` shall be computed at read time over `is_visible=True` reviews only, rounded to 1 decimal place (`round(avg, 1)`), and shall be `null` (`None`) when there are `0` visible reviews. `average_rating` shall **never** be denormalized or stored on `Venue` or `TablePin`.
- **REQ-REV-005** **Public venue reviews (`GET /api/v1/reviews/venues/{venue_id}/` -> `200` `ReviewListOut`):**
  - Public endpoint (no authentication required).
  - If `Venue(id=venue_id)` does not exist -> `404 NOT_FOUND`.
  - Query params: `limit: int = 20` (clamped to `1..100` in `services.py`), `offset: int = 0` (clamped to `>= 0` in `services.py`).
  - Returns `ReviewListOut`:
    - `average_rating: float | None` (read-time average over visible reviews for this venue)
    - `review_count: int` (total count of visible reviews for this venue)
    - `reviews: list[ReviewPublicOut]` (visible reviews only, `is_visible=True`, ordered by `-created_at`, sliced by `[offset : offset + limit]`)
- **REQ-REV-006** **Public table pin reviews (`GET /api/v1/reviews/tables/{table_pin_id}/` -> `200` `ReviewListOut`):**
  - Public endpoint (no authentication required).
  - If `TablePin(id=table_pin_id)` does not exist -> `404 NOT_FOUND`.
  - Query params: `limit: int = 20` (clamped to `1..100` in `services.py`), `offset: int = 0` (clamped to `>= 0` in `services.py`).
  - Returns `ReviewListOut` (`average_rating`, `review_count`, `reviews`) scoped to visible reviews (`is_visible=True`) on bookings for `table_pin_id`, ordered by `-created_at`.
- **REQ-REV-007** **Customer's own reviews (`GET /api/v1/reviews/my/` -> `200` `list[ReviewMineOut]`, `auth=auth`):**
  - Unauthenticated callers shall receive `401`.
  - Callers whose `role != UserRole.CUSTOMER` shall raise `PermissionDenied` (`403 FORBIDDEN`).
  - Returns `list[ReviewMineOut]` for `booking__customer_id=user.id`, ordered by `-created_at`, **including** hidden reviews (`is_visible=False`) with `is_visible` exposed so the customer can see their full submission history.
- **REQ-REV-008** **Response schemas & PII protection (`apps/reviews/schemas.py`, `BR-13`, `NFR-28`):**
  - `ReviewPublicOut`: `id: int`, `rating: int`, `text: str`, `reviewer_name: str`, `table_number: str`, `created_at: datetime`. Explicitly **NO** `booking_id`, `phone`, `email`, `last_name`, or `is_visible`.
  - `ReviewMineOut(ReviewPublicOut)`: extends `ReviewPublicOut` with `booking_id: int` and `is_visible: bool`.
  - `ReviewListOut`: `average_rating: float | None`, `review_count: int`, `reviews: list[ReviewPublicOut]`.

## 5. Business rules touched
- **FR-24** — Customer submits one rating and review text after a completed booking.
- **FR-25** — Public visitors read venue and table reviews and average ratings.
- **BR-09** — Only the customer who owns a `COMPLETED` booking with `end_at <= now` may submit at most one review for that booking.
- **BR-13 / NFR-28** — Public review responses never expose customer PII (`phone`, `last_name`, `email`) or `booking_id`/`is_visible`; `reviewer_name` uses first name only or `"Customer"`.
- **ARCH-001 / ARCH-002** — Business logic in `apps/reviews/services.py`; booking eligibility checked inside `transaction.atomic()` with `Booking.objects.select_for_update()`.
- **ARCH-006** — `created_at` stored in UTC (`auto_now_add=True`).

## 6. Non-functional targets
- **Security & Privacy (IDOR / PII):** Unauthenticated `POST /` or `GET /my/` returns `401`; non-`CUSTOMER` role raises `PermissionDenied` (`403 FORBIDDEN`); wrong customer on `booking` raises `ReviewNotAllowedError` (`403 REVIEW_NOT_ALLOWED`); `ReviewCreateIn` uses `extra="forbid"`; `ReviewPublicOut` never serializes `booking_id`, `phone`, `last_name`, `email`, `is_visible`, or hidden (`is_visible=False`) reviews.
- **Concurrency & Integrity:** `select_for_update()` on `Booking` + DB `unique_review_per_booking` prevents duplicate reviews under concurrent `POST /` requests; DB `review_rating_between_1_and_5` enforces `1 <= rating <= 5`.
- **Query Efficiency:** Public list endpoints use `select_related("booking__customer", "booking__table_pin")` to avoid N+1 queries; `average_rating` and `review_count` are computed via a single SQL aggregate (`Avg`, `Count`) over `is_visible=True`.
- **Contract & Tests:** `python manage.py check`, `pytest apps/reviews/tests/` (PostgreSQL), and `./check-contract.sh` (with `api/openapi.snapshot.json` updated under protected-path review) pass with 0 failures and 0 skipped tests.

## 7. Acceptance criteria (Gherkin)

```gherkin
Scenario: 1. Customer submits a review for a COMPLETED booking after end_at
  Given an authenticated CUSTOMER owns Booking B with status="COMPLETED" and end_at in the past
  When the customer calls POST /api/v1/reviews/ with {"booking_id": B.id, "rating": 5, "text": "  Great window seat!  "}
  Then HTTP 201 is returned with ReviewMineOut having:
    | booking_id | B.id                |
    | rating     | 5                   |
    | text       | Great window seat!  |
    | is_visible | true                |

Scenario: 2. Rejects non-COMPLETED booking or booking whose slot has not ended (409 REVIEW_NOT_ELIGIBLE)
  Given an authenticated CUSTOMER owns Booking B1 with status="CONFIRMED" and Booking B2 with status="COMPLETED" and end_at in the future
  When the customer calls POST /api/v1/reviews/ for B1 and for B2
  Then HTTP 409 with error_code "REVIEW_NOT_ELIGIBLE" is returned for both.

Scenario: 3. Rejects duplicate review for the same booking (409 REVIEW_ALREADY_EXISTS)
  Given Booking B already has a Review
  When the customer calls POST /api/v1/reviews/ for Booking B again
  Then HTTP 409 with error_code "REVIEW_ALREADY_EXISTS" is returned.

Scenario: 4. Auth, role, and ownership isolation (401 / 403 / 404)
  Given Booking B is owned by Customer A
  When an unauthenticated caller calls POST /api/v1/reviews/ or GET /api/v1/reviews/my/
  Then HTTP 401 is returned
  When a VENUE_OWNER calls POST /api/v1/reviews/ for Booking B or GET /api/v1/reviews/my/
  Then HTTP 403 with error_code "FORBIDDEN" (PermissionDenied) is returned
  When Customer B calls POST /api/v1/reviews/ for Booking B
  Then HTTP 403 with error_code "REVIEW_NOT_ALLOWED" is returned
  When Customer A calls POST /api/v1/reviews/ for non-existent booking_id=999999
  Then HTTP 404 is returned.

Scenario: 5. G1 input validation (StrictInt 1-5, stripped non-blank text <= 1000, extra="forbid")
  Given an authenticated CUSTOMER with a completed Booking B
  When the customer calls POST /api/v1/reviews/ with:
    - rating=0 or rating=6 or rating=true or rating=4.5 or rating="5"
    - text="   " or text=<1001 chars>
    - {"booking_id": B.id, "rating": 4, "text": "Nice", "extra": 1}
  Then HTTP 422 with error_code "VALIDATION_ERROR" is returned for each request.

Scenario: 6. Public venue & table reviews exclude hidden reviews, compute read-time average, and mask PII
  Given Venue V has TablePin T1 with visible reviews (ratings 5, 4) and one hidden review (is_visible=false, rating 1)
    And Customer A has no first_name (or blank first_name) and phone "09123456789"
  When an anonymous caller requests GET /api/v1/reviews/venues/<V.id>/?limit=20&offset=0
  Then HTTP 200 is returned with ReviewListOut having:
    | review_count   | 2    |
    | average_rating | 4.5  |
    And reviews contains 2 items with reviewer_name="Customer" and no "booking_id", "phone", "last_name", "email", or "is_visible"
  When an anonymous caller requests GET /api/v1/reviews/tables/<T1.id>/
  Then HTTP 200 is returned with the same 2 visible reviews, review_count=2, and average_rating=4.5
  When an anonymous caller requests GET /api/v1/reviews/venues/<V_with_zero_visible>/ or GET /api/v1/reviews/tables/<T_with_zero_visible>/
  Then HTTP 200 is returned with review_count=0, average_rating=null, reviews=[]
  When an anonymous caller requests GET /api/v1/reviews/venues/999999/ or GET /api/v1/reviews/tables/999999/
  Then HTTP 404 is returned.

Scenario: 7. Customer /my/ endpoint includes hidden reviews with is_visible flag
  Given Customer A submitted Review R1 (is_visible=true) and Review R2 (is_visible=false)
  When Customer A requests GET /api/v1/reviews/my/
  Then HTTP 200 is returned with both R1 (is_visible=true) and R2 (is_visible=false) ordered newest-first.
```

## 8. Out of scope (explicit)
- **Review moderation hide/show (T-038 / FR-41):** Admin endpoints to hide/show reviews (`is_visible` toggle) are deferred to **T-038**.
- **Enriching `VenuePublicDetailOut` / `VenuePublicItemOut`:** Adding `average_rating` or `review_count` fields to `apps/venues/schemas.py` public venue payloads is deferred to a follow-up task.
- **Customer edit or delete of reviews:** Customers cannot edit or delete a submitted review in v1.
- **Frontend review UI (`frontend/`):** Submitting and displaying reviews in Next.js belongs to a separate frontend task.

## 9. Open questions
- **First-name profile editing:** `accounts.User` currently stores `phone` and `role` without a `first_name` column; the `"Customer"` fallback handles this cleanly until profile fields are added. *Closed for T-037.*

## 10. Frontend Review Form & Public Displays (Follow-up (d))
- **API Client (`frontend/src/lib/api.ts`):** Hand-written `ReviewCreateIn`, `ReviewPublicOut`, `ReviewMineOut`, `ReviewListOut`, plus `createReview`, `listVenueReviews`, `listTableReviews`, and `listMyReviews`.
- **My Bookings Review Form (`frontend/src/app/my-bookings/page.tsx`):**
  - Displays `"ثبت نظر"` only on `COMPLETED` bookings without an existing review.
  - Inline accessible 1–5 star `radiogroup` + required text (1..1000 chars with counter); validates client-side before sending.
  - On `201`: displays the created `ReviewMineOut` on the booking row.
  - On `409 REVIEW_ALREADY_EXISTS`: calls `listMyReviews()` and displays the existing review on that row instead of a bare error.
  - On `403 REVIEW_NOT_ALLOWED` / `409 REVIEW_NOT_ELIGIBLE`: maps to Persian messages without exposing raw `error_code`.
- **Venue Public Reviews (`frontend/src/app/venues/[slug]/page.tsx`):** Async server component fetches `listVenueReviews(venue.id, { limit, offset: 0 })`, displaying 1-decimal `average_rating` (or `"هنوز نظری ثبت نشده است."` when 0), `review_count`, visible reviews (`reviewer_name`, rating, `table_number`, `text`, `formatJalaliDate`), and `"نمایش نظرات بیشتر"` pagination via `reviews_limit`.
- **Table Pin Public Reviews (`frontend/src/components/VenuePanoramaExplorer.tsx`):** Fetches `listTableReviews(selectedPin.id)` when a pin is selected and displays that table's average rating and visible reviews inside the selected pin detail card.
- **Tests:** `frontend/src/lib/__tests__/api.test.ts` and `frontend/src/lib/__tests__/ReviewsFrontend.test.tsx` (jsdom component tests for venue section, table pin reviews, and my-bookings review form/validation/409 handling).
