# Tasks — Feature 001 Booking Lock

| Task ID | Description | Owner | Status | Dependencies |
| :--- | :--- | :--- | :--- | :--- |
| **T-011** | Booking model, status lifecycle, constraints, indexes, and Jalali presentation helpers | `booking-lock-engineer` | Done (Gate G4 Approved) | None |
| **T-012** | Atomic lock service (`create_booking_lock`, `select_for_update`, concurrency race test) | `booking-lock-engineer` | Done (Gate G4 Approved) | T-011 |
| **T-013** | Initiate-booking endpoint and API integration (`POST /api/v1/bookings/initiate/`) | `backend-api-engineer` | Done (Gate G4 Approved) | T-012 |
| **T-014** | Validate PostgreSQL Concurrency and Deadlock Behavior (Spike 02 / M1) | `booking-lock-engineer` | Next | T-013 |

### Gate T-013 Approval Notes:
1. **Thin Views & Error Envelope:** `POST /api/v1/bookings/initiate/` validated via Pydantic schemas, business logic encapsulated in `services.py`, errors mapped to standard envelope (400, 403, 409, 422).
2. **Availability Filter Integration:** `GET /api/v1/scheduling/venues/{venue_id}/slots` wires in `filter_available_slots_for_table` when `table_pin_id` is supplied.
3. **M1 Alignment:** T-014 is the Concurrency and Deadlock Behavior Spike (Spike 02 / M1) required for Milestone 1 acceptance (real payment checkout is PH-05, T-020..T-024).

### Gate T-012 Approval Notes:
1. **Concurrency Race Protection:** Proved with PostgreSQL row locking via `select_for_update()` under `ThreadPoolExecutor(max_workers=2)`.
2. **In-Transaction Stale Lock Expiry:** Expired locks are lazily marked `EXPIRED` in-transaction at the start of lock evaluation, eliminating false conflict rejections.

### Gate T-011 Approval Notes:
1. **Panoramas Foundation:** `Space` and `TablePin` in `apps/panoramas/models.py` form the FK foundation for bookings. The panoramas phase (T-015..T-019) must extend these models and their migrations, not replace them.
2. **Status Transitions:** Explicitly covers EXPIRED paths (from PENDING_PAYMENT / INITIATED via lock expiry) and CANCELLED reachability from PENDING_PAYMENT, supporting BR-004 cancellation and lock timeout cleanup.
