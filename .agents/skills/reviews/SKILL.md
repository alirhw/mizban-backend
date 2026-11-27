# Skill: Reviews (FR-24 / FR-25 / FR-41, BR-09, BR-13)

## What it teaches
How a customer reviews a café and the exact table they sat at — after the
visit, exactly once per booking — and how those reviews are shown publicly
without ever leaking the customer's phone number.

## Decided (T-037/T-038, 2026-11-27) — these replace the proposals below; do not re-open them
- The feature is IMPLEMENTED: `apps/reviews/` (`api.py`, `schemas.py`,
  `services.py`) exists with submit + public reads + admin moderation.
- Rating: integer 1–5 (`StrictInt`), enforced in the schema AND the
  service (CheckConstraint `review_rating_between_1_and_5`).
- Text: required, max 1000 characters.
- Public display name: first name only, fallback `"Customer"`.
- Moderation (T-038): admin hides/shows by flipping `is_visible`; never
  delete. `is_visible` has `db_index=True` (T-043).

## Steps
1. Model: `Review` in `apps/reviews/models.py` (implemented in T-037/T-038
   — see the Decided note above). Fields: `booking` (FK, the single
   source of truth for who / which venue / which table), `rating`
   (integer), `text`, `is_visible` (default True), `created_at`. Derive
   venue and table pin from `booking.venue` / `booking.table_pin` in
   queries — do NOT store duplicate venue/table FKs that can drift from
   the booking.
2. One review per booking (BR-09): `UniqueConstraint` on `booking`. A
   second submit for the same booking is a domain error, never a second
   row — the DB constraint is the last line, the service checks first.
3. Eligibility (BR-09) is checked in `apps/reviews/services.py`, never in
   a view: the booking must have `status == COMPLETED` AND `end_at <= now`
   (aware UTC), AND `booking.customer` must be the requesting user. This
   is why T-033 (auto-complete) is a prerequisite — a booking that was
   never completed can never be reviewed.
4. Rating: an integer on the decided scale 1–5 (T-037; the SRS says "one
   rating" without fixing the scale, so do NOT present 1–5 as an SRS
   fact). Validate the range in the Ninja schema AND the service. Never
   a float, never a free-text rating.
5. Text: required alongside the rating (FR-24: "one rating and a text"),
   bounded in length — max 1000 characters (decided T-037). Strip
   nothing silently; reject over-long text with a domain error.
6. Visibility (FR-41): the admin hides/shows a review by flipping
   `is_visible` only — a review row is NEVER deleted. Public reads
   (venue page FR-25, table-pin window FR-09) return `is_visible=True`
   rows only. The venue average rating (FR-07) is computed over visible
   reviews only, derived at read time — never stored as a field that can
   drift from the reviews.
7. Privacy (BR-13 / NFR-28): the public review out-schema exposes NO
   phone number. Display name: first name only (decided T-037),
   fallback `"Customer"`. The customer's phone is visible only to the
   venue owner of a confirmed booking — never in any public review
   response.
8. No edit, no delete by the customer in v1 — unless the G1 spec says
   otherwise. If the spec adds editing later, that is a new task, not a
   silent extra in this one.

## Example
```python
# apps/reviews/services.py — eligibility is the whole feature's guard
def submit_review(*, user, booking_id, rating, text):
    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking_id)
        if booking.customer_id != user.id:
            raise ReviewNotAllowedError(...)          # 403, not own booking
        if booking.status != BookingStatus.COMPLETED or booking.end_at > timezone.now():
            raise ReviewNotEligibleError(...)         # 409, BR-09 not met
        if Review.objects.filter(booking=booking).exists():
            raise ReviewAlreadyExistsError(...)       # 409, one per booking
        return Review.objects.create(booking=booking, rating=rating, text=text)
# Error-code names above are proposed — the exact codes are pinned in design.md at G2.
```

## Common mistakes
- Letting anyone review any venue (no booking, no completion check) —
  that is a fake-review hole, not a feature.
- Storing the venue/table on the review as separate FKs and letting them
  disagree with the booking.
- Computing the average rating from ALL reviews including hidden ones,
  or storing the average on the venue row.
- Returning the reviewer's phone (or full name + phone) in a public list
  response (BR-13 / NFR-28 violation).
- Deleting a moderated review instead of hiding it (FR-41 is hide/show,
  and the row is audit data).
- Inventing the rating scale or the text length limit instead of pinning
  them at G1 — the SRS does not fix either.
