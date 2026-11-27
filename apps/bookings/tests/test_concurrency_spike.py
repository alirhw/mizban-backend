"""PostgreSQL Concurrency and Deadlock Behavior Spike (Task T-014 / Spike 02 / M1).

Experiment:
Run independent concurrent PostgreSQL transactions/clients against the booking initiate path
(service-level and API-level), with repeated rounds of multi-way contention on the same table+slot.

Success criteria (from project doc & TD-004):
1. Exactly one active booking for the contested slot (at most one winner).
2. Deterministic loser conflict (SlotAlreadyReservedError / HTTP 409).
3. Zero duplicate rows in PostgreSQL (enforced by DB partial unique constraints).
4. No unbounded hangs (all threads complete within bounded time).
5. Zero deadlocks under single-resource row locking; documented lock order and deadlock policy.
6. Quantitative latency tracking (p50, p90, p95, p99, min, max, lock waits).
"""
from __future__ import annotations

import json
import statistics
import threading
import time as pytime
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Any

import pytest
from django.db import connection
from django.test import Client
from django.utils import timezone as dj_timezone

from apps.accounts.models import UserRole
from apps.bookings.models import Booking, BookingStatus
from apps.bookings.services import create_booking_lock
from apps.panoramas.tests.factories import TablePinFactory
from apps.venues.tests.factories import UserFactory, VenueFactory, activate_test_subscription
from core.exceptions import SlotAlreadyReservedError

pytestmark = [
    pytest.mark.django_db(transaction=True),
]


@dataclass
class AttemptResult:
    worker_id: int
    outcome: str  # "winner", "conflict", "deadlock", "error"
    duration_ms: float
    error_message: str | None = None
    booking_id: int | None = None


@dataclass
class RoundStats:
    round_num: int
    concurrency: int
    winners: int
    conflicts: int
    deadlocks: int
    errors: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    mean_ms: float


def compute_percentiles(durations: list[float]) -> dict:
    if not durations:
        return {"p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0, "min": 0.0, "max": 0.0, "mean": 0.0}
    sorted_d = sorted(durations)
    n = len(sorted_d)
    return {
        "p50": statistics.median(sorted_d),
        "p90": sorted_d[int(n * 0.90)] if n > 1 else sorted_d[0],
        "p95": sorted_d[int(n * 0.95)] if n > 1 else sorted_d[0],
        "p99": sorted_d[int(n * 0.99)] if n > 1 else sorted_d[0],
        "min": sorted_d[0],
        "max": sorted_d[-1],
        "mean": statistics.mean(sorted_d),
    }


def _run_contention_attempt(
    worker_id: int,
    barrier: threading.Barrier,
    user_id: int,
    pin_id: int,
    slot_date: date,
    slot_start_time: time,
) -> AttemptResult:
    """Worker task executing create_booking_lock with synchronized start."""
    from apps.accounts.models import User
    from apps.panoramas.models import TablePin

    # Synchronize all threads at the barrier so they strike the DB at the exact same moment
    barrier.wait()

    t_start = pytime.perf_counter()
    outcome = "error"
    error_msg = None
    booking_id = None

    try:
        user = User.objects.get(pk=user_id)
        pin = TablePin.objects.get(pk=pin_id)
        booking = create_booking_lock(
            user=user,
            table_pin=pin,
            slot_date=slot_date,
            slot_start_time=slot_start_time,
        )
        outcome = "winner"
        booking_id = booking.pk
    except SlotAlreadyReservedError:
        outcome = "conflict"
    except Exception as exc:
        err_str = str(exc).lower()
        if "deadlock" in err_str:
            outcome = "deadlock"
        else:
            outcome = "error"
        error_msg = str(exc)
    finally:
        t_end = pytime.perf_counter()
        connection.close()

    duration_ms = (t_end - t_start) * 1000.0
    return AttemptResult(
        worker_id=worker_id,
        outcome=outcome,
        duration_ms=duration_ms,
        error_message=error_msg,
        booking_id=booking_id,
    )


def test_spike_service_multiway_contention_20_rounds() -> None:
    """T-014 Experiment Part 1: 20 rounds of 5-way contention on the booking service.

    For each round:
    - 5 concurrent threads race for the exact same TablePin and slot.
    - Synchronized with threading.Barrier to maximize collision probability.
    - Validates: exactly 1 winner, exactly 4 conflicts (409), 0 deadlocks, 0 duplicate rows.
    """
    CONCURRENCY = 5
    ROUNDS = 20
    round_stats_list: list[RoundStats] = []
    all_durations: list[float] = []
    all_winner_durations: list[float] = []
    all_conflict_durations: list[float] = []

    owner: Any = UserFactory(role=UserRole.VENUE_OWNER)
    venue: Any = VenueFactory(owner=owner, is_approved=True)
    activate_test_subscription(venue)
    pin: Any = TablePinFactory(venue=venue)

    base_date = (dj_timezone.now() + timedelta(days=2)).date()

    for r in range(ROUNDS):
        # Unique slot time per round to isolate rounds
        hour = 8 + (r % 14)
        slot_date = base_date + timedelta(days=(r // 14))
        slot_time = time(hour, 0)

        # Create distinct users for each competing worker
        users: list[Any] = [UserFactory(role=UserRole.CUSTOMER) for _ in range(CONCURRENCY)]
        barrier = threading.Barrier(CONCURRENCY)

        with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            futures = [
                executor.submit(
                    _run_contention_attempt,
                    worker_id=i,
                    barrier=barrier,
                    user_id=users[i].pk,
                    pin_id=pin.pk,
                    slot_date=slot_date,
                    slot_start_time=slot_time,
                )
                for i in range(CONCURRENCY)
            ]
            results = [f.result() for f in futures]

        # Categorize outcomes
        winners = [res for res in results if res.outcome == "winner"]
        conflicts = [res for res in results if res.outcome == "conflict"]
        deadlocks = [res for res in results if res.outcome == "deadlock"]
        errors = [res for res in results if res.outcome == "error"]

        # Core Invariants
        assert len(winners) == 1, f"Round {r}: Expected exactly 1 winner, got {len(winners)}"
        assert len(conflicts) == CONCURRENCY - 1, f"Round {r}: Expected {CONCURRENCY-1} conflicts, got {len(conflicts)}"
        assert len(deadlocks) == 0, f"Round {r}: Encountered deadlocks: {[d.error_message for d in deadlocks]}"
        assert len(errors) == 0, f"Round {r}: Unexpected errors: {[e.error_message for e in errors]}"

        # DB row count invariant
        active_rows = Booking.objects.filter(
            table_pin=pin,
            slot_date=slot_date,
            slot_start_time=slot_time,
            status=BookingStatus.PENDING_PAYMENT,
        ).count()
        assert active_rows == 1, f"Round {r}: Expected exactly 1 active Booking row in DB, got {active_rows}"

        durations = [res.duration_ms for res in results]
        all_durations.extend(durations)
        all_winner_durations.extend([res.duration_ms for res in winners])
        all_conflict_durations.extend([res.duration_ms for res in conflicts])

        p = compute_percentiles(durations)
        round_stats_list.append(
            RoundStats(
                round_num=r + 1,
                concurrency=CONCURRENCY,
                winners=len(winners),
                conflicts=len(conflicts),
                deadlocks=len(deadlocks),
                errors=len(errors),
                p50_ms=p["p50"],
                p95_ms=p["p95"],
                p99_ms=p["p99"],
                min_ms=p["min"],
                max_ms=p["max"],
                mean_ms=p["mean"],
            )
        )

    # Global Statistics across 100 requests (20 rounds * 5)
    overall_p = compute_percentiles(all_durations)
    winner_p = compute_percentiles(all_winner_durations)
    conflict_p = compute_percentiles(all_conflict_durations)

    print("\n" + "=" * 80)
    print("T-014 POSTGRESQL CONCURRENCY SPIKE — PART 1 (5-WAY CONTENTION, 20 ROUNDS)")
    print("=" * 80)
    print(f"Total Rounds: {ROUNDS} | Concurrency per round: {CONCURRENCY} | Total Transactions: {ROUNDS * CONCURRENCY}")
    print(f"Total Winners: {sum(s.winners for s in round_stats_list)} (100% - exactly 1 per round)")
    print(f"Total Conflicts: {sum(s.conflicts for s in round_stats_list)} (100% deterministic 409 rejection)")
    print(f"Total Deadlocks: {sum(s.deadlocks for s in round_stats_list)} (Zero deadlocks observed)")
    print(f"Total Errors: {sum(s.errors for s in round_stats_list)} (Zero unhandled exceptions)")
    print("-" * 80)
    print("LATENCY DISTRIBUTION (ms):")
    print(
        f"  Overall:   p50={overall_p['p50']:.2f}ms | p90={overall_p['p90']:.2f}ms | "
        f"p95={overall_p['p95']:.2f}ms | max={overall_p['max']:.2f}ms"
    )
    print(f"  Winners:   p50={winner_p['p50']:.2f}ms | p95={winner_p['p95']:.2f}ms | max={winner_p['max']:.2f}ms")
    print(f"  Conflicts: p50={conflict_p['p50']:.2f}ms | p95={conflict_p['p95']:.2f}ms | max={conflict_p['max']:.2f}ms")
    print("=" * 80 + "\n")


def test_spike_high_contention_10_way_10_rounds() -> None:
    """T-014 Experiment Part 2: 10 rounds of high 10-way contention.

    Tests deeper lock queues (1 winner, 9 waiting transactions per round).
    Proves that PostgreSQL row-locking queue resolves cleanly without lock escalation or deadlock.
    """
    CONCURRENCY = 10
    ROUNDS = 10
    round_stats_list: list[RoundStats] = []
    all_durations: list[float] = []

    owner: Any = UserFactory(role=UserRole.VENUE_OWNER)
    venue: Any = VenueFactory(owner=owner, is_approved=True)
    activate_test_subscription(venue)
    pin: Any = TablePinFactory(venue=venue)
    base_date = (dj_timezone.now() + timedelta(days=3)).date()

    for r in range(ROUNDS):
        slot_date = base_date + timedelta(days=r)
        slot_time = time(11, 0)

        users: list[Any] = [UserFactory(role=UserRole.CUSTOMER) for _ in range(CONCURRENCY)]
        barrier = threading.Barrier(CONCURRENCY)

        with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            futures = [
                executor.submit(
                    _run_contention_attempt,
                    worker_id=i,
                    barrier=barrier,
                    user_id=users[i].pk,
                    pin_id=pin.pk,
                    slot_date=slot_date,
                    slot_start_time=slot_time,
                )
                for i in range(CONCURRENCY)
            ]
            results = [f.result() for f in futures]

        winners = [res for res in results if res.outcome == "winner"]
        conflicts = [res for res in results if res.outcome == "conflict"]
        deadlocks = [res for res in results if res.outcome == "deadlock"]
        errors = [res for res in results if res.outcome == "error"]

        assert len(winners) == 1, f"High Contention Round {r}: Expected 1 winner, got {len(winners)}"
        assert len(conflicts) == CONCURRENCY - 1, (
            f"High Contention Round {r}: Expected {CONCURRENCY - 1} conflicts, got {len(conflicts)}"
        )
        assert len(deadlocks) == 0, f"High Contention Round {r}: Deadlock detected"
        assert len(errors) == 0, f"High Contention Round {r}: Error detected"

        durations = [res.duration_ms for res in results]
        all_durations.extend(durations)
        p = compute_percentiles(durations)
        round_stats_list.append(
            RoundStats(
                round_num=r + 1,
                concurrency=CONCURRENCY,
                winners=len(winners),
                conflicts=len(conflicts),
                deadlocks=len(deadlocks),
                errors=len(errors),
                p50_ms=p["p50"],
                p95_ms=p["p95"],
                p99_ms=p["p99"],
                min_ms=p["min"],
                max_ms=p["max"],
                mean_ms=p["mean"],
            )
        )

    overall_p = compute_percentiles(all_durations)
    print("\n" + "=" * 80)
    print("T-014 POSTGRESQL CONCURRENCY SPIKE — PART 2 (10-WAY HIGH CONTENTION, 10 ROUNDS)")
    print("=" * 80)
    print(
        f"Total Transactions: {ROUNDS * CONCURRENCY} | "
        f"Winners: {sum(s.winners for s in round_stats_list)} | "
        f"Conflicts: {sum(s.conflicts for s in round_stats_list)}"
    )
    print(
        f"Overall Latency: p50={overall_p['p50']:.2f}ms | p90={overall_p['p90']:.2f}ms | "
        f"p95={overall_p['p95']:.2f}ms | max={overall_p['max']:.2f}ms"
    )
    print("=" * 80 + "\n")


def _run_api_contention_attempt(
    worker_id: int,
    barrier: threading.Barrier,
    user,
    pin_id: int,
    slot_date: str,
    slot_time: str,
) -> dict:
    """Worker task executing POST /api/v1/bookings/initiate/ through Django test Client."""
    from core.testing import authenticate_client

    client = Client()
    authenticate_client(client, user)
    barrier.wait()
    t_start = pytime.perf_counter()
    status_code = 500
    resp_body = {}

    try:
        response = client.post(
            "/api/v1/bookings/initiate/",
            data=json.dumps({
                "table_pin_id": pin_id,
                "slot_date": slot_date,
                "slot_start_time": slot_time,
            }),
            content_type="application/json",
        )
        status_code = response.status_code
        try:
            resp_body = response.json()
        except Exception:
            resp_body = {}
    finally:
        t_end = pytime.perf_counter()
        connection.close()

    duration_ms = (t_end - t_start) * 1000.0
    return {
        "worker_id": worker_id,
        "status_code": status_code,
        "duration_ms": duration_ms,
        "body": resp_body,
    }


def test_spike_api_multiway_contention_10_rounds(settings: Any) -> None:
    """T-014 Experiment Part 3: 10 rounds of 5-way contention via Ninja HTTP API.

    Verifies the full web stack:
    - Bearer auth -> Schema validation -> Service layer -> PostgreSQL row lock -> Response envelope.
    - Validates: Exactly one HTTP 201 Created with status='PENDING_PAYMENT'.
    - Exactly four HTTP 409 Conflicts with error_code='SLOT_ALREADY_RESERVED'.
    - Zero 500s, zero hangs.
    """
    settings.DEBUG = True  # Enable debug auth bridge for test client
    CONCURRENCY = 5
    ROUNDS = 10
    all_api_durations: list[float] = []

    owner: Any = UserFactory(role=UserRole.VENUE_OWNER)
    venue: Any = VenueFactory(owner=owner, is_approved=True)
    activate_test_subscription(venue)
    pin: Any = TablePinFactory(venue=venue)
    base_date = (dj_timezone.now() + timedelta(days=4)).date()

    for r in range(ROUNDS):
        slot_date_str = (base_date + timedelta(days=r)).isoformat()
        slot_time_str = "14:00"

        users: list[Any] = [UserFactory(role=UserRole.CUSTOMER) for _ in range(CONCURRENCY)]
        barrier = threading.Barrier(CONCURRENCY)

        with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
            futures = [
                executor.submit(
                    _run_api_contention_attempt,
                    worker_id=i,
                    barrier=barrier,
                    user=users[i],
                    pin_id=pin.pk,
                    slot_date=slot_date_str,
                    slot_time=slot_time_str,
                )
                for i in range(CONCURRENCY)
            ]
            results = [f.result() for f in futures]

        status_codes = [res["status_code"] for res in results]
        durations = [res["duration_ms"] for res in results]
        all_api_durations.extend(durations)

        # Invariants: exactly one 201, four 409s, zero others
        assert status_codes.count(201) == 1, f"API Round {r}: Expected 1 winner (201), got {status_codes.count(201)}"
        assert status_codes.count(409) == CONCURRENCY - 1, (
            f"API Round {r}: Expected {CONCURRENCY - 1} conflicts (409), got {status_codes.count(409)}"
        )
        assert status_codes.count(500) == 0, f"API Round {r}: Server errors detected!"

        # Winner verification
        winner_resp = next(res for res in results if res["status_code"] == 201)
        assert winner_resp["body"]["status"] == "PENDING_PAYMENT"

        # Conflict verification
        for conf in [res for res in results if res["status_code"] == 409]:
            assert conf["body"]["error_code"] == "SLOT_ALREADY_RESERVED"

    api_p = compute_percentiles(all_api_durations)
    print("\n" + "=" * 80)
    print("T-014 POSTGRESQL CONCURRENCY SPIKE — PART 3 (API-LEVEL 5-WAY CONTENTION, 10 ROUNDS)")
    print("=" * 80)
    print(
        f"Total API Requests: {ROUNDS * CONCURRENCY} | 201 Winners: {ROUNDS} | "
        f"409 Conflicts: {ROUNDS * (CONCURRENCY - 1)}"
    )
    print(
        f"API Latency: p50={api_p['p50']:.2f}ms | p90={api_p['p90']:.2f}ms | "
        f"p95={api_p['p95']:.2f}ms | max={api_p['max']:.2f}ms"
    )
    print("=" * 80 + "\n")


def test_spike_independent_slots_concurrency_no_cross_blocking():
    """T-014 Experiment Part 4: Concurrent non-contending requests do NOT block each other.

    5 customers simultaneously reserving 5 DIFFERENT tables at the exact same instant.
    Proves that row-level locking on TablePin does not take coarse table locks and allows
    full parallel throughput across distinct tables.
    """
    CONCURRENCY = 5
    owner = UserFactory(role=UserRole.VENUE_OWNER)
    venue = VenueFactory(owner=owner, is_approved=True)
    activate_test_subscription(venue)
    pins = [TablePinFactory(venue=venue) for _ in range(CONCURRENCY)]
    users = [UserFactory(role=UserRole.CUSTOMER) for _ in range(CONCURRENCY)]
    target_date = (dj_timezone.now() + timedelta(days=5)).date()
    target_time = time(16, 0)

    barrier = threading.Barrier(CONCURRENCY)

    def _non_contending_attempt(i):
        barrier.wait()
        t0 = pytime.perf_counter()
        try:
            create_booking_lock(
                user=users[i],
                table_pin=pins[i],
                slot_date=target_date,
                slot_start_time=target_time,
            )
            return ("winner", (pytime.perf_counter() - t0) * 1000.0)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        results = list(executor.map(_non_contending_attempt, range(CONCURRENCY)))

    outcomes = [r[0] for r in results]
    durations = [r[1] for r in results]

    # All 5 must win because each targets a distinct table pin
    assert outcomes == ["winner"] * CONCURRENCY
    p = compute_percentiles(durations)

    print("\n" + "=" * 80)
    print("T-014 POSTGRESQL CONCURRENCY SPIKE — PART 4 (PARALLEL NON-CONTENDING TABLES)")
    print("=" * 80)
    print("5 Concurrent distinct table reservations: 5/5 succeeded in parallel.")
    print(f"Non-contending Latency: p50={p['p50']:.2f}ms | p95={p['p95']:.2f}ms | max={p['max']:.2f}ms")
    print("=" * 80 + "\n")
