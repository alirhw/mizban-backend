# Spec 001 - Booking Lock (temporary reservation while paying)
Status: Approved for build | Owner: Ali | Lane: FULL (money + concurrency)
Implements: BR-001, BR-002 | Decided by: TD-004, ADR-003 | Architecture: ARCH-002, ARCH-004

## 1. Problem and goal
A customer who picked a table and slot is sent to the payment gateway.
While they pay, that table+slot must be held for them - and for nobody
else - for exactly 10 minutes. If payment does not complete, the table
must become bookable again with zero manual cleanup. Double-booking a
table for the same slot must be mathematically impossible.

## 2. User stories
US-01  As a customer, I want my chosen table held while I pay, so that
       nobody can take it from under me at the gateway.
US-02  As a customer, I want a clear answer when a table was just taken,
       so that I can pick another slot instead of paying for a conflict.
US-03  As a venue owner, I want every confirmed booking to be real, so
       that I never face two parties for one table.

## 3. Requirements (EARS)
REQ-LOCK-001  When a customer initiates a booking for a table pin, date
  and slot start, the system shall create a Booking in PENDING_PAYMENT
  with locked_at = now and lock_expires_at = now + 10 minutes.
REQ-LOCK-002  When the slot start is less than 24 hours from now, the
  system shall reject the request with 400 LEAD_TIME_VIOLATION (BR-002).
REQ-LOCK-003  If an overlapping Booking exists in CONFIRMED, or in
  PENDING_PAYMENT with lock_expires_at > now, the system shall reject
  the request with 409 SLOT_ALREADY_RESERVED.
REQ-LOCK-004  The availability check and the lock insert shall run in a
  single transaction.atomic() block with select_for_update() on the
  table pin row (ARCH-002). Availability shall never be read from cache
  (ARCH-004).
REQ-LOCK-005  If the lock expires unpaid, the slot shall be bookable by
  others immediately; a periodic Celery task may later mark the stale
  row EXPIRED, but correctness shall not depend on that task.
REQ-LOCK-006  Selected design add-ons shall be recorded on the booking
  (BookingAddon) with their price snapshot, marked payable-in-person
  (BR-003); only the table fee is charged online (spec 002, billing).

## 4. State machine (Architecture Spec section 7 & Task T-011)
```text
INITIATED -> PENDING_PAYMENT --(payment verified before expiry)--> CONFIRMED
INITIATED -> EXPIRED (hold creation timeout)
INITIATED -> CANCELLED (aborted before gateway)
PENDING_PAYMENT --(lock expiry / payment failed / timeout)--> EXPIRED
PENDING_PAYMENT --(customer abort / cancellation during checkout)--> CANCELLED
CONFIRMED --(customer cancel >= 36h before slot, BR-004)--> CANCELLED (refund to wallet)
CONFIRMED --(slot end passed)--> COMPLETED
EXPIRED, CANCELLED, COMPLETED: Terminal states
```

### Status Transition Table:
| From Status | Allowed Target Statuses | Trigger / Condition |
| :--- | :--- | :--- |
| `INITIATED` | `PENDING_PAYMENT`, `EXPIRED`, `CANCELLED` | Lock acquired; gateway token requested; abort/timeout |
| `PENDING_PAYMENT` | `CONFIRMED`, `EXPIRED`, `CANCELLED` | Payment verified; lock expired unpaid; payment cancelled/aborted |
| `CONFIRMED` | `CANCELLED`, `COMPLETED` | Cancellation >= 36h before slot (BR-004); slot end passed |
| `EXPIRED` | *(none)* | Terminal state |
| `CANCELLED` | *(none)* | Terminal state |
| `COMPLETED` | *(none)* | Terminal state |

### Panoramas Foundation Note (Gate T-011 Approval Note 1):
The minimal `Space` and `TablePin` models in `apps/panoramas/models.py` and migration `panoramas.0001_initial` serve as the foreign key foundation for bookings. The upcoming Panoramas phase (Tasks T-015..T-019) must **EXTEND** these existing models and migrations rather than rebuilding or replacing them.

## 5. API
POST /api/v1/bookings/initiate/
  In:  { table_pin_id, slot_date (YYYY-MM-DD), slot_start_time (HH:MM), addon_ids: [] }
  Out: 201 { booking_id, status: "PENDING_PAYMENT", lock_expires_at, amount_online_toman, amount_in_person_toman }
  Errors (standard envelope): 409 SLOT_ALREADY_RESERVED, 400 LEAD_TIME_VIOLATION,
  422 VALIDATION_ERROR, 401 for guests (login is required at payment step).

## 6. Acceptance criteria (Gherkin)
Scenario: Happy path lock
  Given table 12 at Cafe Demo is free on 1404/09/01 at 19:00 (slot >= 24h ahead)
  When the customer initiates a booking for that slot
  Then a PENDING_PAYMENT booking exists, lock_expires_at is 10 minutes
    after locked_at, and the slot shows as taken for everyone else.

Scenario: THE RACE - two customers, one table (automated in
  apps/bookings/tests/test_booking_race.py, PostgreSQL only)
  Given table 12 is free for the slot
  When two customers initiate a booking for the same table and slot at
    the same moment
  Then exactly one receives 201 with a PENDING_PAYMENT lock
    And exactly one receives 409 with error_code SLOT_ALREADY_RESERVED
    And exactly one Booking row exists for that table and slot.

Scenario: Last-minute booking refused
  Given a slot that starts 12 hours from now
  When a customer initiates a booking for it
  Then the response is 400 with error_code LEAD_TIME_VIOLATION
    And no Booking row is created.

Scenario: Expired lock frees the table
  Given a PENDING_PAYMENT lock whose lock_expires_at has passed unpaid
  When another customer initiates a booking for the same slot
  Then the request succeeds with a fresh lock.

## 7. Non-functional targets
- Concurrency proof runs against PostgreSQL (SQLite cannot prove
  select_for_update semantics). Zero double-bookings, ever.
- Initiate endpoint p95 < 300 ms excluding gateway calls (no gateway
  call happens inside the lock transaction).

## 8. Out of scope
- Gateway checkout + verify callback (billing spec, phase PH-05 / tasks T-020..T-024).
- Cancellation + wallet refund (spec of its own; BR-004).
- Slot generation itself (scheduling spec, task T-010).

## 9. Open questions
None - decided in TD-004 / ADR-003.
