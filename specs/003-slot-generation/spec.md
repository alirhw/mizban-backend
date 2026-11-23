# Spec 003 — Slot Generation Engine
Status: Approved for build | Owner: Backend Team | Lane: Standard
Implements: BR-001, BR-002 | Decided by: TD-004 | Architecture: ARCH-004, ARCH-006

## 1. Problem and Goal
Customers need to book visual table reservations during venue operating hours. Slots must be deterministically generated according to business rules without drifting, manual slot generation, or stale cache states.

## 2. User Stories
* **US-01:** As a customer, I want to see the available 90-minute time slots for a venue on my selected date, so I can reserve a table.
* **US-02:** As a customer, I want to see slots starting in less than 24 hours marked as disabled with a clear reason, so I understand the lead-time requirement.
* **US-03:** As a venue owner, I want my operating hours (including those crossing midnight) to automatically generate uniform 90-minute slots with 30-minute cleaning buffers without manual schedule maintenance.

## 3. Requirements (EARS)
* **REQ-SLOT-001:** When given a venue's operating hours (`open_time`, `close_time`) and target date, the system shall deterministically generate slots of exactly 90 minutes duration with starts spaced 120 minutes apart (90 min slot + 30 min cleaning buffer) (BR-001).
* **REQ-SLOT-002:** When `close_time <= open_time`, the system shall treat the operating hours as crossing midnight and extend the operating window to the subsequent calendar day.
* **REQ-SLOT-003:** A candidate slot shall only be emitted if its entire 90-minute duration fits within the operating window (`slot.start + 90m <= close_dt`). Buffer is not required after the final slot.
* **REQ-SLOT-004:** When a slot starts less than 24 hours from `now` (`slot.start - now < 24h`), the system shall mark `is_bookable = False` and set `disabled_reason = "LEAD_TIME_VIOLATION"` (BR-002).
* **REQ-SLOT-005:** When a slot starts at least 24 hours from `now` (`slot.start - now >= 24h`), the system shall mark `is_bookable = True`.
* **REQ-SLOT-006:** All slot timestamps (`start`, `end`) shall be computed, stored, and compared as timezone-aware UTC instants (ARCH-006). Venue local times shall be interpreted in `Asia/Tehran`.
* **REQ-SLOT-007:** When querying slots for a date on which a venue has no configured operating hours (closed day), the system shall return an empty list of slots.
* **REQ-SLOT-008:** Slot availability shall never be cached (ARCH-004).

## 4. Business Rules Touched
* **BR-001:** A slot is exactly 90 minutes, followed by exactly 30 minutes of cleaning buffer (120-minute cycle).
* **BR-002:** A slot can only be booked if it starts at least 24 hours from now (`slot.start - now >= 24 hours`).

## 5. Non-functional Targets
* Deterministic output: idempotent calculation on demand.
* UTC instants: zero local time drift or ambiguity.
* Sub-millisecond computation time per date query.

## 6. Acceptance Criteria
* Scenario 1: Standard operating hours (09:00 - 13:00) produces 2 slots (09:00-10:30, 11:00-12:30).
* Scenario 2: Slots <24h away have `is_bookable=False`.
* Scenario 3: Exact 24h boundary: slot starting in exactly 24h00m is bookable; 23h59m is not.
* Scenario 4: Cross-midnight hours (e.g. 20:00 - 02:00) generate slots spanning across midnight without errors.
* Scenario 5: Closed weekday returns empty list.

## 7. Out of Scope & Task Boundaries
* **Task T-012 (Atomic Booking Lock):** Concurrency lock and race handling. The remaining skipped test `apps/bookings/tests/test_booking_race.py::test_two_simultaneous_initiates_exactly_one_wins` is the fail-first spec for **Task T-012**, not T-011.
* **Task T-013 (Initiate-Booking & Lock Integration):** The public `GET /api/v1/scheduling/venues/{venue_id}/slots` endpoint is implemented and delivered in T-010. Task T-013 scope is accordingly adjusted to cover only initiate-booking and lock integration.

---

## 8. Manual Slot Blocking by Venue Owners (Task T-026 / FR-011)

**Owning App:** `apps/scheduling` (`booking-lock-engineer` per `ownership.yaml`).  
**Migration:** `apps/scheduling/migrations/0001_initial.py` (no `apps/bookings` or `apps/wallets` migration).

### 8.1 Governing Policies
1. **Single Pin + Single Generated Slot:** A `BlockedSlot` covers ONE `TablePin` and ONE concrete generated slot `[start_at, end_at)` derived server-side from `get_venue_slots_for_date` (no whole-day, venue/space-wide, or arbitrary ranges).
2. **Never Overrides Existing Bookings:** Creating a block over a slot with an occupying booking (`CONFIRMED` or `PENDING_PAYMENT` with `lock_expires_at > now`) is rejected with HTTP 409 `SLOT_ALREADY_RESERVED`.
3. **Shared `TablePin` Row Lock:** `create_blocked_slot` acquires `TablePin.objects.select_for_update()` inside `transaction.atomic()` — the exact same lock as `create_booking_lock` — guaranteeing serialisation under concurrent block vs book attempts.
4. **Hard-Delete Unblocking:** Deleting a `BlockedSlot` hard-deletes the row and immediately restores slot availability; past blocks may also be deleted for cleanup.

### 8.2 Availability & Booking Indistinguishability
- Public availability (`filter_available_slots_for_table` / `is_table_slot_occupied`) **omits** blocked slots identically to occupied slots.
- Booking initiation (`create_booking_lock`) raises the exact same `SlotAlreadyReservedError` (`SLOT_ALREADY_RESERVED`, HTTP 409) so customers cannot distinguish owner blocks from bookings.
- `BlockedSlot.reason` is owner-private and never exposed in any public response.
- Owners may block any future slot (`start_at > now`), including slots $< 24\text{h}$ away (BR-002 lead time binds customers only). Past slots (`start_at <= now`) raise `InvalidSlotError` (`INVALID_SLOT`, HTTP 400); misaligned `start_at` raises `ValidationError` (`VALIDATION_ERROR`, HTTP 422).

### 8.3 Endpoints (`apps/scheduling/api.py`, `ActiveSessionAuth`, owner-only)
- `POST /api/v1/scheduling/pins/{pin_id}/blocked-slots/` (`BlockedSlotCreateIn(start_at, reason)`) $\to$ `201 BlockedSlotOut(id, pin_id, start_at, end_at, jalali_start_at, reason)`
- `GET /api/v1/scheduling/pins/{pin_id}/blocked-slots/` $\to$ `200 List[BlockedSlotOut]` (upcoming `start_at >= now`, ordered by `start_at`, capped at 100)
- `DELETE /api/v1/scheduling/blocked-slots/{block_id}/` $\to$ `204`
- Registered read-only in Django Admin (`apps/scheduling/admin.py`).
