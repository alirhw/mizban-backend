# Spec 016 - In-App Notifications (FR-36, BR-10, BR-16)
Status: Draft | Owner: Product / Notifications | Lane: Standard | Implements: FR-36, BR-10, BR-16 | Architecture: ARCH-001, ARCH-006

## 1. Problem and goal
Venue owners currently have no in-app notification feed to learn when a customer confirms or cancels a booking at their venue, or when a platform admin approves or rejects their venue submission. This feature introduces the `apps/notifications` domain app and `/api/v1/notifications` endpoints (**FR-36**) with synchronous same-transaction creation, strict in-app-only delivery (**BR-10**), and per-user data isolation (**BR-16**).

## 2. User stories
- **US-01** As a venue owner, I want to receive in-app notifications when a booking at my venue is confirmed or cancelled, or when my venue is approved or rejected, so that I can track operational and moderation events without polling individual resources.
- **US-02** As a venue owner, I want to view my notifications, check my unread count, mark a single notification as read, and mark all notifications as read, so that I can manage my inbox cleanly.
- **US-03** As any authenticated user, I want my notification list, unread count, and read-state mutations to be strictly isolated to my own `recipient` rows (**BR-16**), so that no other user can read or alter my notifications.

## 3. Project decisions (G1 — PROJECT decisions, NOT SRS facts)
The following six parameters were decided at G1 for v1 and are **PROJECT decisions, NOT SRS facts**:

1. **Recipient matrix:**
   - `VENUE_OWNER` receives `Notification` rows for `BOOKING_CONFIRMED`, `BOOKING_CANCELLED`, `VENUE_APPROVED`, and `VENUE_REJECTED`.
   - `CUSTOMER` receives **NO** `Notification` rows for booking events (customers view booking status directly in `GET /api/v1/bookings/my/`).
   - `ADMIN` receives **NO** `Notification` rows.
2. **Type list:**
   - Exactly four notification types: `BOOKING_CONFIRMED`, `BOOKING_CANCELLED`, `VENUE_APPROVED`, `VENUE_REJECTED`.
3. **Nullable `SET_NULL` foreign keys:**
   - `Notification.booking` (`ForeignKey("bookings.Booking", on_delete=models.SET_NULL, null=True, blank=True)`) and `Notification.venue` (`ForeignKey("venues.Venue", on_delete=models.SET_NULL, null=True, blank=True)`).
   - Booking events (`BOOKING_CONFIRMED`, `BOOKING_CANCELLED`) set `booking` (with `venue` derivable via `booking.venue` or `venue=booking.venue`).
   - Venue events (`VENUE_APPROVED`, `VENUE_REJECTED`) set `venue` with `booking=None`.
4. **List pagination:**
   - Default `limit = 50`, maximum `limit = 100` (clamped `1..100`), `offset = 0` (clamped `>= 0`).
5. **Rendered Persian copy:**
   - Notifications are stored as `type` + entity references (`booking`, `venue`), never as free-typed `title`/`body` database columns.
   - Persian `title` and `body` are rendered at read time from `type` + `booking`/`venue` (with safe fallback copy if a `SET_NULL` reference is `None`), and **never** contain `phone` or `email`.
6. **No delete & no retention/purge job in v1:**
   - There is **no** `DELETE` endpoint on `/api/v1/notifications`, and **no** automated retention or purge job in v1.

## 4. Requirements (EARS)
- **REQ-NOTIF-001** **`Notification` model & constraints (`apps/notifications/models.py`):**
  The system shall define `NotificationType(models.TextChoices)` with exactly four values: `BOOKING_CONFIRMED`, `BOOKING_CANCELLED`, `VENUE_APPROVED`, `VENUE_REJECTED`.
  `Notification` shall store:
  - `recipient`: `ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications", db_index=True)`
  - `type`: `CharField(max_length=32, choices=NotificationType.choices, db_index=True)`
  - `booking`: `ForeignKey("bookings.Booking", on_delete=models.SET_NULL, null=True, blank=True, related_name="notifications")`
  - `venue`: `ForeignKey("venues.Venue", on_delete=models.SET_NULL, null=True, blank=True, related_name="notifications")`
  - `is_read`: `BooleanField(default=False, db_index=True)`
  - `created_at`: `DateTimeField(auto_now_add=True, db_index=True)` (aware UTC, `ARCH-006`)
  `Meta` shall set `ordering = ["-created_at"]` and include a composite index on `["recipient", "is_read", "-created_at"]`.

- **REQ-NOTIF-002** **Synchronous same-transaction creation (`apps/notifications/services.py`):**
  `create_notification(*, recipient, type, booking=None, venue=None)` shall create a `Notification` row synchronously inside the caller's active `transaction.atomic()` block (so notification creation commits or rolls back atomically with the triggering state transition).
  Trigger wiring:
  - `apps/billing/services/payment.py`: inside `transaction.atomic()` in `handle_payment_callback` (on transition to `BookingStatus.CONFIRMED`) and `pay_booking_with_wallet` (on transition to `BookingStatus.CONFIRMED`), call `create_notification` for `booking.venue.owner` with `BOOKING_CONFIRMED` and `booking=booking`.
  - `apps/bookings/services.py`: inside `transaction.atomic()` in `cancel_booking` (on transition from `CONFIRMED` or `PENDING_PAYMENT` to `BookingStatus.CANCELLED`; never on idempotent replay when already `CANCELLED`), call `create_notification` for `locked_booking.venue.owner` with `BOOKING_CANCELLED` and `booking=locked_booking`.
  - `apps/venues/services.py`: inside `transaction.atomic()` in `approve_venue` (`VENUE_APPROVED`, `venue=venue`, `booking=None`) and `reject_venue` (`VENUE_REJECTED`, `venue=venue`, `booking=None`), call `create_notification` for `venue.owner`.

- **REQ-NOTIF-003** **In-app only delivery (`BR-10`):**
  The notification system shall operate strictly in-app. Creating or reading notifications shall trigger **zero** SMS calls, **zero** email calls, and store **no** email field.

- **REQ-NOTIF-004** **Read-time Persian copy rendering & PII exclusion:**
  `apps/notifications/services.py` shall render Persian `title` and `body` at read time from `notification.type` and related `booking` / `venue` (using `select_related("booking__venue", "booking__table_pin", "venue")` to avoid N+1 queries).
  - If `booking` or `venue` is `None` (e.g. after `SET_NULL`), rendering shall still succeed with safe generic Persian copy.
  - Rendered `title` and `body` shall **never** include any user `phone` or `email`.

- **REQ-NOTIF-005** **Per-user data isolation (`BR-16`):**
  All service functions (`list_my_notifications`, `unread_count`, `mark_as_read`, `mark_all_as_read`) shall scope queries and mutations strictly to `request.auth` (`auth=auth` on all `/api/v1/notifications` endpoints):
  - Unauthenticated callers shall receive `401`.
  - `list_my_notifications(user, *, limit=50, offset=0)` returns only rows where `recipient_id == user.id`, ordered by `-created_at, -id`, with `limit` clamped to `1..100` (default `50`) and `offset` clamped to `>= 0`.
  - `unread_count(user)` returns the integer count of rows where `recipient_id == user.id` and `is_read=False`.
  - `mark_as_read(user, notification_id)`:
    - If no `Notification` exists with `pk=notification_id` -> raise `Http404` (`404`).
    - If `notification.recipient_id != user.id` -> raise `PermissionDenied` (`403 FORBIDDEN`).
    - If `notification.is_read` is `False`, set `is_read = True`, saving `update_fields=["is_read"]`.
    - If `notification.is_read` is already `True`, perform an idempotent no-op and return `200` with the serialized `NotificationOut`.
  - `mark_all_as_read(user)`:
    - Atomically updates all unread rows for `recipient_id == user.id` (`is_read=False` -> `is_read=True`) and returns `200` with the updated count (`{"marked": count}`).

- **REQ-NOTIF-006** **HTTP API contract (`/api/v1/notifications`, `apps/notifications/api.py`, `apps/notifications/schemas.py`):**
  Mounted in `config/api.py` under `/notifications` (`/api/v1/notifications`), all endpoints protected with `auth=auth`, thin views (`ARCH-001`):
  - `GET /api/v1/notifications/` -> `200` `list[NotificationOut]` (query params `limit: int = 50`, `offset: int = 0`).
  - `GET /api/v1/notifications/unread-count` -> `200` `UnreadCountOut` (`{"unread_count": int}`).
  - `POST /api/v1/notifications/{notification_id}/read` -> `200` `NotificationOut`.
  - `POST /api/v1/notifications/read-all` -> `200` `MarkAllReadOut` (`{"marked": int}`).
  - `NotificationOut` (`ConfigDict(extra="forbid")`) exposes: `id: int`, `type: NotificationType`, `booking_id: int | None`, `venue_id: int | None`, `title: str`, `body: str`, `is_read: bool`, `created_at: datetime`.
  - No `DELETE` endpoint shall exist on `/api/v1/notifications`.

## 5. Business rules touched
- **FR-36** — In-app notification feed for venue owners on booking confirmation/cancellation and venue approval/rejection.
- **BR-10** — In-app notifications only; zero SMS or email delivery and no email field.
- **BR-16** — Strict per-user data isolation (`403` on accessing/mutating another user's notification, `404` when missing).
- **ARCH-001** — Business logic and rendering live in `apps/notifications/services.py`; Ninja views in `apps/notifications/api.py` stay thin.
- **ARCH-006** — `created_at` is stored in aware UTC.

## 6. Non-functional targets
- **Security & Privacy (`BR-16`, `BR-10`):** Unauthenticated calls return `401`; cross-user `mark_as_read` returns `403 FORBIDDEN`; missing `notification_id` returns `404`; `NotificationOut` uses `extra="forbid"` and rendered Persian `title`/`body` never contain `phone` or `email`.
- **Atomicity:** Notification creation runs inside the caller's `transaction.atomic()` block; if the payment confirmation, booking cancellation, or venue moderation transaction rolls back, zero `Notification` rows are persisted.
- **Query Efficiency:** `list_my_notifications` uses `select_related("booking__venue", "booking__table_pin", "venue")` with bounded pagination (`limit` default `50`, clamped `1..100`, `offset >= 0`), deterministic `-created_at, -id` ordering, and a composite DB index on `["recipient", "is_read", "-created_at"]`.
- **Contract & Tests:** `python manage.py check`, `pytest apps/notifications/tests/` (PostgreSQL), and `./check-contract.sh` (after `api/openapi.snapshot.json` update under human gate) pass with 0 failures and 0 skipped tests.

## 7. Acceptance criteria (Gherkin)

```gherkin
Scenario: 1. Booking confirmation and cancellation create owner notifications atomically (FR-36, BR-10)
  Given Venue V1 is owned by VENUE_OWNER O1 and has Customer C1 with a PENDING_PAYMENT booking B1
  When Customer C1 confirms B1 via payment callback or pay_booking_with_wallet
  Then B1 becomes CONFIRMED and exactly 1 Notification row exists for O1 with type="BOOKING_CONFIRMED" and booking_id=B1.id
    And 0 Notification rows exist for C1 or any ADMIN
    And 0 SMS or email sends are invoked
  When Customer C1 cancels B1 via cancel_booking (>= 36h before start_at)
  Then B1 becomes CANCELLED and a Notification row exists for O1 with type="BOOKING_CANCELLED" and booking_id=B1.id
    And calling cancel_booking a second time (idempotent replay) does NOT create a duplicate Notification row.

Scenario: 2. Venue approval and rejection create owner notifications with booking=None
  Given Venue V1 is owned by VENUE_OWNER O1
  When an ADMIN calls approve_venue for V1
  Then a Notification row exists for O1 with type="VENUE_APPROVED", venue_id=V1.id, and booking_id=null
  When an ADMIN calls reject_venue for V1 with reason="Incomplete photos"
  Then a Notification row exists for O1 with type="VENUE_REJECTED", venue_id=V1.id, and booking_id=null.

Scenario: 3. List, pagination clamping, Persian copy without PII, unread count, and mark-read
  Given VENUE_OWNER O1 has 3 unread notifications (newest first)
  When O1 calls GET /api/v1/notifications/unread-count
  Then HTTP 200 is returned with {"unread_count": 3}
  When O1 calls GET /api/v1/notifications/?limit=200&offset=-1
  Then HTTP 200 is returned with O1's notifications ordered by -created_at, -id (limit clamped to 100, offset clamped to 0)
    And each item has Persian title and body containing neither phone nor email
  When O1 calls POST /api/v1/notifications/<N1.id>/read
  Then HTTP 200 is returned with is_read=true
  When O1 calls POST /api/v1/notifications/<N1.id>/read again
  Then HTTP 200 is returned idempotently with is_read=true
  When O1 calls POST /api/v1/notifications/read-all
  Then HTTP 200 is returned with {"marked": 2} and GET /api/v1/notifications/unread-count returns {"unread_count": 0}.

Scenario: 4. BR-16 isolation and auth enforcement (401 / 403 / 404) and transaction rollback
  Given Notification N1 belongs to VENUE_OWNER O1 and VENUE_OWNER O2 is another authenticated user
  When an unauthenticated caller requests GET /api/v1/notifications/ or GET /api/v1/notifications/unread-count
  Then HTTP 401 is returned
  When O2 calls POST /api/v1/notifications/<N1.id>/read
  Then HTTP 403 with error_code "FORBIDDEN" is returned and N1.is_read remains false
  When O1 calls POST /api/v1/notifications/999999/read
  Then HTTP 404 is returned
  When a booking confirmation transaction rolls back due to an error inside transaction.atomic()
  Then zero Notification rows are committed for that booking.
```

## 8. Out of scope (explicit)
- **`frontend/` owner and customer notification panels:** Building the Next.js notification bell/drawer/panel UI belongs to a separate frontend follow-up task.
- **Retention / purge job:** Automated deletion or archiving of old `Notification` rows is deferred out of v1 (and there is no `DELETE` endpoint in v1).
- **SMS / Email / Push channels:** Explicitly excluded by **BR-10** (in-app only).

## 9. Open questions
- None; all G1 project decisions (recipient matrix, 4 notification types, `SET_NULL` FKs, pagination `50`/`100`, read-time Persian copy without PII, no delete/purge in v1) are fixed for T-039.

## 10. Frontend Owner Notification Bell & Dropdown (Follow-up (f))
- **Location & Role Gating:** `frontend/src/components/NotificationsBell.tsx` mounted in `frontend/src/components/Header.tsx` only when `!loading && user?.role === "VENUE_OWNER"` (customers, admins, and logged-out users see no bell; no dedicated `/notifications` route; no background polling).
- **API Client (`frontend/src/lib/api.ts`):** Hand-written `NotificationOut`, `UnreadCountOut`, `MarkAllReadOut`, `listNotifications({ limit?, offset? })`, `getUnreadCount()`, `markNotificationRead(notificationId)`, and `markAllNotificationsRead()`.
- **Dropdown & Mark-Read Flows:**
  - Fetches `getUnreadCount()` on mount and hides the badge when `0`.
  - Opening the bell fetches `listNotifications({ limit: 20, offset: 0 })`, displaying server-rendered Persian `title` and `body` verbatim with `formatJalaliDate(created_at, { includeTime: true })`, unread/read distinction, empty state, and `"نمایش اعلان‌های بیشتر"` offset pagination.
  - Clicking an unread row calls `markNotificationRead`, updates the row in place, and decrements the badge; `"علامت‌گذاری همه به‌عنوان خوانده‌شده"` calls `markAllNotificationsRead`, marks listed rows read in place, and clears the badge.
  - `403 FORBIDDEN` renders a Persian error message without raw `error_code`.
- **Tests:** `frontend/src/lib/__tests__/api.test.ts` and `frontend/src/lib/__tests__/NotificationsBell.test.tsx`.
