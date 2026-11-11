# Spec 002 - Venue catalogue models (task T-008)
Status: Done (models layer) | Owner: Ali | Lane: Standard
<!-- No bookings/payments/wallet touched. Source: doc Chat-05 task T-008,
     Architecture Spec section 4 (apps.venues) and section 6 entity list. -->

## 1. Problem and goal (3-5 lines, no solution)
Venues, their weekly operating hours, their design add-on catalogues and
their subscription state must exist as constrained database schema before
any owner workflow (T-009), slot generation (T-010) or panorama work
(T-015) can be built. This task is persistence only: models, constraints,
migration, admin registration and model tests.

## 2. User stories
US-01  As a venue owner, I want my venue profile, hours and add-ons stored,
       so that later tasks can expose them in my panel and the public site.
US-02  As an admin, I want venue approval and subscription state as explicit
       fields, so that public visibility (BR-005) is a database fact, not a
       display decision.

## 3. Requirements (numbered, EARS style)
REQ-VEN-001  The system shall persist Venue with owner FK, unique slug, city,
             venue_type (CAFE | RESTAURANT), address and description.
REQ-VEN-002  The system shall record approval as `is_approved` (default
             False) and subscription state as `subscription_status`
             (INACTIVE | ACTIVE | EXPIRED, default INACTIVE).
REQ-VEN-003  When code asks for publicly listed venues, the system shall
             return only venues with is_approved=True AND
             subscription_status=ACTIVE (`Venue.objects.public()`,
             `Venue.is_publicly_visible`).
REQ-VEN-004  The system shall persist at most one OperatingHours row per
             (venue, weekday); weekday uses the Python convention
             0=Monday..6=Sunday (Jalali mapping is T-010's job).
REQ-VEN-005  If close_time is earlier than open_time, the system shall accept
             the row (the venue closes after midnight).
REQ-VEN-006  If a DesignAddon fee is negative, then the database shall reject
             the write (CheckConstraint, fee >= 0, integer Toman).
REQ-VEN-007  The system shall persist Subscription records (plan_name,
             status, started_at, expires_at) without any purchase flow.

## 4. Business rules touched
BR-005 - a venue is publicly visible/bookable only when admin-approved AND
         its subscription is active (implemented as QuerySet + property).
Money  - DesignAddon.fee is integer Toman; it is paid to the venue in person
         (BR-003), never charged by the platform.

## 5. Non-functional targets
- Invariants enforced by the database (unique/check constraints), not only
  by model clean() - asserted by tests against real constraint violations.
- No new indexes beyond unique constraints in this task; catalogue filters
  (city/type) get indexes only when the listing query lands (T-009/T-026).

## 6. Acceptance criteria (Gherkin)
Scenario: duplicate slug rejected
  Given a venue with slug "cafe-diba" exists
  When a second venue is saved with slug "cafe-diba"
  Then the database raises IntegrityError

Scenario: public listing rule
  Given venues in every combination of is_approved x subscription_status
  When Venue.objects.public() is evaluated
  Then only the approved + ACTIVE venue is returned

Scenario: overnight hours
  Given operating hours open 18:00 and close 02:00 for one weekday
  When the row is saved
  Then it persists and reports crosses_midnight = True

## 7. Out of scope (explicit)
- All API endpoints and owner/admin workflows, approval actions and cache
  invalidation -> T-009.
- Subscription purchase, payment and lifecycle transitions -> PH-05 billing.
- Spaces, panorama images and table pins -> panoramas app (T-015).
- Slot generation from operating hours -> T-010.

## 8. Open questions (each gets a business answer, or "not in v1")
- Weekday convention: resolved - Python 0=Monday..6=Sunday stored; the
  Jalali-to-weekday mapping is implemented in T-010, not in the schema.
