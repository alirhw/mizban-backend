# Tasks — Feature 001 Booking Lock

| Task ID | Description | Owner | Status | Dependencies |
| :--- | :--- | :--- | :--- | :--- |
| **T-011** | Booking model, status lifecycle, constraints, indexes, and Jalali presentation helpers | `booking-lock-engineer` | Done (Gate G4 Approved) | None |
| **T-012** | Atomic lock service (`create_booking_lock`, `select_for_update`, concurrency race test) | `booking-lock-engineer` | Next | T-011 |
| **T-013** | Initiate-booking endpoint and API integration (`POST /api/v1/bookings/initiate/`) | `backend-api-engineer` | Pending | T-012 |
| **T-014** | Payment checkout & verification integration | `finance-engineer` | Pending | T-013 |

### Gate T-011 Approval Notes:
1. **Panoramas Foundation:** `Space` and `TablePin` in `apps/panoramas/models.py` form the FK foundation for bookings. The panoramas phase (T-015..T-019) must extend these models and their migrations, not replace them.
2. **Status Transitions:** Explicitly covers EXPIRED paths (from PENDING_PAYMENT / INITIATED via lock expiry) and CANCELLED reachability from PENDING_PAYMENT, supporting BR-004 cancellation and lock timeout cleanup.
