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

---

## 9. Subscription Plans & Manual Admin Activation (Task T-025 / Decision 5)

**Governing Rules:** BR-005 (Public visibility & bookability require `is_approved=True` AND active subscription), Decision 5 (2026-11-20), FR-008/FR-012, ARCH-006 (UTC storage, Jalali presentation only).

### 9.1 Design Forced by Repository (One Write Path, One Read Path)
Preconditions confirmed `Venue` had only a static enum `subscription_status` (`INACTIVE | ACTIVE | EXPIRED`) and no expiry timestamp field. Therefore:
- **One Read Path:** Subscription activity is derived from `VenueSubscription` records (`expires_at > now`) through `Venue.has_active_subscription(now=None)` and `VenueQuerySet.public(now=None)`. Every BR-005 check (`Venue.is_publicly_visible`, `list_public_venues`, `get_public_venue_by_slug`, `apps/panoramas/services.py`, `apps/bookings/services.py:initiate_booking`) routes through this single read path.
- **One Write Path:** `activate_subscription(venue, *, plan, activated_by, note="", now=None)` inside `transaction.atomic()` with `Venue.objects.select_for_update()` is the sole write path creating `VenueSubscription` records and invalidating venue metadata cache on commit.

### 9.2 Data Models (`apps/venues/models.py`, Migration `0002_subscriptionplan_venuesubscription.py`)
- **`SubscriptionPlan`:** `name` (unique), `duration_days` (`> 0` CheckConstraint), `price_toman` (`BigIntegerField >= 0` CheckConstraint), `is_active` (default `True`), `created_at`, `updated_at`. No seed plans or hard-coded prices. Inactive plans cannot be used for new activations (`InactiveSubscriptionPlanError`, 400 `INACTIVE_SUBSCRIPTION_PLAN`), while existing subscriptions survive until expiry.
- **`VenueSubscription`:** `venue` (`CASCADE`, `related_name="venue_subscriptions"`), `plan` (`PROTECT`), `starts_at` (UTC), `expires_at` (UTC, indexed), `created_by` (`PROTECT`), `created_at`, `note` (optional offline-coordination reference). CheckConstraint `expires_at > starts_at`.

### 9.3 Stacking Activation Rule
- If the venue currently has an active subscription (`latest.expires_at > now`): `starts_at = latest.expires_at`, `expires_at = starts_at + timedelta(days=plan.duration_days)`.
- Otherwise (never subscribed or expired): `starts_at = now`, `expires_at = now + timedelta(days=plan.duration_days)`.

### 9.4 Django Admin & Owner Read Endpoint
- **Django Admin (`apps/venues/admin.py`):** `SubscriptionPlanAdmin` supports full CRUD. `VenueSubscriptionAdmin` is **add-only** (`has_change_permission=False`, `has_delete_permission=False`); its add form accepts only `venue`, `plan`, `note` (`starts_at`/`expires_at` uneditable) and delegates all date computation to `activate_subscription`.
- **Owner Read Endpoint (`apps/venues/api.py`):** `GET /api/v1/venues/owner/venues/{venue_id}/subscription/` (and `/subscription`), `ActiveSessionAuth`, owner-only (401/403/404 via `get_owner_venue`), returning `VenueSubscriptionOut(is_active, plan_name, starts_at, expires_at, jalali_expires_at, days_remaining, has_ever_subscribed)`. No purchase, renewal, or public plan-catalogue endpoint exists in this task (post-MVP per Decision 1).

### 9.5 Legacy Cleanup & Derived `VenueOwnerOut.subscription_status` (Task T-025-FIX)
- **Removed:** Static `Venue.subscription_status` database column and the unused T-008 `Subscription` stub model (plus `SubscriptionAdmin` and `SubscriptionFactory`) via forward migration `apps/venues/migrations/0003_remove_venue_subscription_status_delete_subscription.py`.
- **Truthful Derived Output:** `Venue.subscription_status` is now a read-only `@property` deriving `"ACTIVE"` or `"INACTIVE"` from `VenueSubscription` records (`list_owner_venues` annotates `_has_active_subscription=Exists(...)` to guarantee constant query count with zero N+1). BR-005 read/write paths (`has_active_subscription()`, `VenueQuerySet.public()`, `activate_subscription()`) remain unchanged.
