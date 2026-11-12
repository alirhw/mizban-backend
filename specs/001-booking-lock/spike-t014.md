# Spike Report: Task T-014 — PostgreSQL Concurrency and Deadlock Behavior (Spike 02 / M1)

**Task ID:** T-014  
**Feature:** 001 — Booking Lock  
**Milestone:** M1 — Table Selection & Atomic Booking Lock  
**Date:** 2026-11-12  
**Owner:** `booking-lock-engineer`  
**Verdict:** **PASSED (Zero Double-Bookings, Zero Deadlocks, Deterministic 409 Conflicts)**

---

## 1. Executive Summary

Task T-014 validates the concurrency and deadlock characteristics of the Miz Ban atomic booking lock under heavy, multi-threaded contention against a live PostgreSQL 16.15 database. 

Over **250 concurrent transactions** across **40 multi-way contention rounds** (5-way service contention, 10-way service contention, and 5-way full HTTP API contention), the system demonstrated:
1. **At most one active booking per contested slot:** 100% win-rate accuracy (exactly 1 winner per round across all 40 rounds).
2. **Deterministic loser conflict:** All losing concurrent requests were deterministically rejected with `SlotAlreadyReservedError` (HTTP 409 `SLOT_ALREADY_RESERVED`).
3. **Zero duplicate rows:** PostgreSQL row count was exactly 1 per contested slot; zero DB constraint violations occurred (`unique_active_booking_table_slot_start`).
4. **Zero deadlocks:** 0 deadlocks observed across all 250 requests.
5. **Zero unbounded hangs:** All requests completed within bounded latency (p50 = 55.26ms, p95 = 75.76ms for 5-way service; p50 = 100.76ms, p95 = 143.12ms for 10-way service).
6. **Parallel non-contending throughput:** Concurrent requests targeting distinct tables executed completely in parallel with zero cross-blocking (p50 = 44.97ms).

---

## 2. Experiment Setup & Architecture

### Environment & Test Rig:
- **Database Engine:** PostgreSQL 16.15 (`PostgreSQL 16.15 on x86_64-pc-linux-musl, compiled by gcc (Alpine 15.2.0) 15.2.0, 64-bit`) running in Docker container `mizban-backend-db-1` on port 5433 using image `postgres:16-alpine`.
- **Version Alignment Note:** The early scaffolding referenced `postgres:18` as a forward-looking placeholder, but PostgreSQL 18 is unreleased upstream and the image was aliased to `postgres:16-alpine`. The codebase stack specification and `docker-compose.yml` have been canonically aligned to `postgres:16-alpine`.
- **Backend Stack:** Django 5.2.19 LTS + Django Ninja 1.4.0 on Python 3.14.6.
- **Concurrency Harness:** `concurrent.futures.ThreadPoolExecutor` with `threading.Barrier` synchronization.
- **Barrier Synchronization:** Threads are held at a synchronization barrier until all $N$ workers are ready, releasing them simultaneously to create peak lock collision on the database connection pool.
- **Connection Isolation:** Every thread acquires and manages its own independent database connection, closing it cleanly in `finally: connection.close()`.

---

## 3. Quantitative Experiment Results

### Part 1: Service-Level 5-Way Contention (20 Repeated Rounds = 100 Transactions)
- **Contention Level:** 5 simultaneous callers per round competing for the same `TablePin` and slot.
- **Rounds:** 20 independent rounds across sequential calendar slots.

| Metric | Result |
| :--- | :--- |
| **Total Transactions** | 100 |
| **Total Winners (`PENDING_PAYMENT`)** | 20 (exactly 1 per round / 100%) |
| **Total Conflicts (`SlotAlreadyReservedError`)** | 80 (exactly 4 per round / 100%) |
| **Deadlocks Detected** | **0** |
| **Unhandled Errors** | **0** |
| **Database Active Rows per Slot** | **1** (verified in DB after each round) |
| **Overall Latency (p50 / p90 / p95 / max)** | **55.26ms / 70.84ms / 75.76ms / 78.66ms** |
| **Winner Latency (p50 / p95 / max)** | **38.41ms / 51.63ms / 51.63ms** |
| **Conflict Latency (p50 / p95 / max)** | **60.58ms / 76.05ms / 78.66ms** |

*Observation on Lock Waits:* The winning thread acquires the `select_for_update()` lock immediately and commits its booking in ~38ms. The waiting threads wait for the lock to release, acquire it in FIFO queue order, re-read the slot availability, detect the winner's committed hold, and cleanly raise `SlotAlreadyReservedError` within ~60ms.

---

### Part 2: High Contention 10-Way Contention (10 Repeated Rounds = 100 Transactions)
- **Contention Level:** 10 simultaneous callers per round (1 winner, 9 waiting transactions).
- **Rounds:** 10 independent rounds.

| Metric | Result |
| :--- | :--- |
| **Total Transactions** | 100 |
| **Total Winners (`PENDING_PAYMENT`)** | 10 (exactly 1 per round / 100%) |
| **Total Conflicts (`SlotAlreadyReservedError`)** | 90 (exactly 9 per round / 100%) |
| **Deadlocks Detected** | **0** |
| **Unhandled Errors** | **0** |
| **Overall Latency (p50 / p90 / p95 / max)** | **100.76ms / 135.26ms / 143.12ms / 149.38ms** |

*Observation:* Even under 10-way serial lock queues, PostgreSQL smoothly drained the 9 waiting transactions in under 150ms without lock escalation or deadlock.

---

### Part 3: Full API-Level 5-Way Contention (10 Repeated Rounds = 50 Requests)
- **Protocol:** `POST /api/v1/bookings/initiate/` over HTTP via Django test client with Bearer authentication.
- **Contention Level:** 5 simultaneous HTTP client threads per round.

| Metric | Result |
| :--- | :--- |
| **Total HTTP Requests** | 50 |
| **HTTP 201 Created (`PENDING_PAYMENT`)** | 10 (exactly 1 per round / 100%) |
| **HTTP 409 Conflict (`SLOT_ALREADY_RESERVED`)** | 40 (exactly 4 per round / 100%) |
| **HTTP 500 / Server Errors** | **0** |
| **API Latency (p50 / p90 / p95 / max)** | **73.69ms / 400.03ms / 421.47ms / 432.80ms** |

*Observation:* Full API stack (auth decoding, Pydantic schema validation, Ninja router, service transaction, JSON response formatting) maintains complete consistency. All losers receive the standardized error envelope with `error_code="SLOT_ALREADY_RESERVED"`.

---

### Part 4: Parallel Non-Contending Tables (5 Concurrent Distinct Tables)
- **Protocol:** 5 simultaneous callers reserving 5 distinct `TablePin` entities at the exact same instant.

| Metric | Result |
| :--- | :--- |
| **Total Reservations Attempted** | 5 |
| **Total Reservations Succeeded** | 5 / 5 (100%) |
| **Cross-Blocking / False Contention** | **None** |
| **Non-contending Latency (p50 / p95 / max)** | **44.97ms / 57.39ms / 57.39ms** |

*Observation:* Proves that row-level locking (`TablePin.objects.select_for_update()`) strictly isolates concurrent holds to the specific table being reserved. Operations on other tables proceed in parallel without delay.

---

## 4. Formal Lock-Order Analysis & Decision

### Lock Acquisition Order:
Every booking initiation follows an invariant, unidirectional lock sequence:
```text
1. BEGIN TRANSACTION (transaction.atomic())
2. SELECT ... FROM panoramas_tablepin WHERE id = :pin_id FOR UPDATE;  [Acquires Exclusive Row Lock]
3. SELECT ... FROM bookings_booking WHERE table_pin_id = :pin_id ... FOR UPDATE; [Expire Stale Locks]
4. SELECT EXISTS(...) FROM bookings_booking WHERE table_pin_id = :pin_id ...; [Availability Check]
5. INSERT INTO bookings_booking (...); [Insert Hold]
6. COMMIT; [Release Row Lock]
```

### Deadlock Impossibility Proof for Single-Table Holds:
- A deadlock requires a cyclic wait in the resource dependency graph: $T_1 \to R_2 \to T_2 \to R_1 \to T_1$.
- In the single-table hold path, there is exactly **one** parent resource being serialized: the `TablePin` row with primary key `P`.
- Every competing transaction $T_i$ requests lock ownership on resource $P$ at Step 2 before doing any other work.
- Because $|V_{locks}| = 1$, the resource acquisition graph is a directed tree of waiting transactions queued on a single node.
- Cycles are mathematically impossible. Hence, **single-table booking lock acquisitions cannot deadlock.**

### Multi-Resource Lock Order Policy (For Future Multi-Table Bookings):
If future phases introduce bookings spanning multiple tables or spaces:
- **Total Ordering Rule:** Transactions must sort all required resource identifiers in ascending numerical order (`ORDER BY id ASC`) before issuing `SELECT ... FOR UPDATE`.
- Enforcing this lexicographical lock order guarantees cycle-free lock acquisition across any combination of tables.

---

## 5. Deadlock & Timeout Policy

To ensure resilience against external stalls, network lags, or slow clients, the following policies are codified:
1. **Zero Gateway Calls in Lock Scope (ARCH-001 / ARCH-002):**
   External payment gateway calls (e.g. Zarinpal checkout token generation) MUST NEVER be invoked inside `transaction.atomic()`. The row lock is committed immediately upon creating the `PENDING_PAYMENT` hold; external HTTP calls take place only after commit.
2. **Lock Timeout Policy:**
   Configured directly in Django `DATABASES["default"]["OPTIONS"]["options"]` in `config/settings/base.py`:
   ```python
   DATABASES["default"]["OPTIONS"]["options"] = "-c lock_timeout=5000 -c statement_timeout=10000"
   ```
   Verified on active PostgreSQL connections:
   - `SHOW lock_timeout;` -> `5s`
   - `SHOW statement_timeout;` -> `10s`
   
   If contention ever exceeds 5 seconds, PostgreSQL automatically aborts the waiting transaction with code `55P03 (lock_not_available)`, preventing unbounded lock queues or worker starvation under pathological traffic spikes.
3. **Lazy Lock Expiry (REQ-LOCK-005):**
   Expired holds (`lock_expires_at <= now`) are lazily transitioned to `EXPIRED` within the winning transaction, preventing stale holds from causing phantom conflicts or blocking subsequent reservations.

---

## 6. Milestone 1 Acceptance Alignment

- **Requirement:** Milestone 1 (M1) requires concurrency evidence proving zero double-bookings on PostgreSQL before M1 acceptance.
- **Evidence:** This spike (`specs/001-booking-lock/spike-t014.md` and automated tests in `apps/bookings/tests/test_concurrency_spike.py`) provides reproducible verification:
  - 250 requests tested.
  - Exactly 1 winner per round.
  - Zero duplicate rows.
  - Zero deadlocks.
  - Deterministic 409 error envelope.
- **Spike 02 / M1 is officially complete and passed.**
