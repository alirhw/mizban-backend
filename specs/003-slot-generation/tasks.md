# Tasks — Feature 003 Slot Generation Engine (Task T-010)

| Task ID | Description | Owner | Status | Dependencies |
| :--- | :--- | :--- | :--- | :--- |
| **T-010.1** | Implement `generate_slots` core generator in `apps/scheduling/services.py` | `booking-lock-engineer` | Done | None |
| **T-010.2** | Implement `get_venue_slots_for_date` venue service function | `booking-lock-engineer` | Done | T-010.1 |
| **T-010.3** | Implement Pydantic schema `SlotOut` and Ninja API router in `apps/scheduling/` | `backend-api-engineer` | Done | T-010.2 |
| **T-010.4** | Unskip and pass fail-first tests in `test_slot_rules.py` + add edge case tests | `test-engineer` | Done | T-010.1, T-010.2 |
| **T-010.5** | Review & Gate Packet compilation (Accepted by Human Gate) | `orchestrator` | Done | All |

### Boundary Notes Recorded:
1. `GET /api/v1/scheduling/venues/{venue_id}/slots` was built and verified in T-010; Task T-013 now covers only initiate-booking (plus lock integration).
2. The remaining skipped test (`test_two_simultaneous_initiates_exactly_one_wins`) is the fail-first test for the atomic lock task (**T-012**).
