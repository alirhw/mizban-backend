"""PostgreSQL tests for booking auto-completion after slot end (Spec 009 / FR-22 / T-033-03)."""
from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from io import StringIO
from unittest.mock import patch

import pytest
from celery.exceptions import Retry
from django.core.management import call_command
from django.db import OperationalError, connection, transaction
from django.test import Client
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.billing.models import PaymentStatus, PaymentTransaction
from apps.bookings.models import Booking, BookingStatus
from apps.bookings.services import complete_expired_bookings
from apps.bookings.tasks import complete_expired_bookings_task
from apps.bookings.tests.factories import BookingAddonFactory, BookingFactory
from apps.panoramas.tests.factories import TablePinFactory
from apps.venues.tests.factories import DesignAddonFactory, UserFactory, VenueFactory
from apps.wallets.models import WalletTransaction
from core.testing import authenticate_client

pytestmark = pytest.mark.django_db

_LOG_BOOKING_ID_RE = re.compile(r"Auto-completed booking: booking_id=(\d+)")


def _make_booking(
    *,
    status: str,
    end_at: datetime,
    customer=None,
    table_pin=None,
    amount_online_toman: int = 50_000,
    amount_in_person_toman: int = 0,
) -> Booking:
    """Create a Booking with a 90-minute slot ending at `end_at`."""
    kwargs: dict = {
        "status": status,
        "start_at": end_at - timedelta(minutes=90),
        "end_at": end_at,
        "amount_online_toman": amount_online_toman,
        "amount_in_person_toman": amount_in_person_toman,
    }
    if customer is not None:
        kwargs["customer"] = customer
    if table_pin is not None:
        kwargs["table_pin"] = table_pin
        kwargs["venue"] = table_pin.venue
    return BookingFactory(**kwargs)


def test_confirmed_booking_with_past_end_at_transitions_to_completed():
    """Scenario 1: Past CONFIRMED booking transitions to COMPLETED and returns 1."""
    assert connection.vendor == "postgresql"
    now = timezone.now()
    booking = _make_booking(status=BookingStatus.CONFIRMED, end_at=now - timedelta(minutes=5))

    completed_count = complete_expired_bookings(now=now)

    assert completed_count == 1
    booking.refresh_from_db()
    assert booking.status == BookingStatus.COMPLETED


def test_confirmed_booking_with_future_end_at_remains_confirmed():
    """Scenario 2: Future CONFIRMED booking stays CONFIRMED and returns 0."""
    now = timezone.now()
    booking = _make_booking(status=BookingStatus.CONFIRMED, end_at=now + timedelta(minutes=30))

    completed_count = complete_expired_bookings(now=now)

    assert completed_count == 0
    booking.refresh_from_db()
    assert booking.status == BookingStatus.CONFIRMED


def test_boundary_end_at_equal_to_now_completes_while_plus_one_minute_stays_confirmed():
    """Scenario 3: end_at == now completes; end_at == now + 1 minute remains CONFIRMED."""
    now = timezone.now()
    booking_at_now = _make_booking(status=BookingStatus.CONFIRMED, end_at=now)
    booking_one_min_future = _make_booking(
        status=BookingStatus.CONFIRMED,
        end_at=now + timedelta(minutes=1),
    )

    completed_count = complete_expired_bookings(now=now)

    assert completed_count == 1
    booking_at_now.refresh_from_db()
    booking_one_min_future.refresh_from_db()
    assert booking_at_now.status == BookingStatus.COMPLETED
    assert booking_one_min_future.status == BookingStatus.CONFIRMED


def test_past_pending_payment_booking_is_not_completed():
    """Scenario 4: Past PENDING_PAYMENT booking must never transition to COMPLETED."""
    now = timezone.now()
    booking = _make_booking(status=BookingStatus.PENDING_PAYMENT, end_at=now - timedelta(minutes=10))

    completed_count = complete_expired_bookings(now=now)

    assert completed_count == 0
    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING_PAYMENT


def test_past_cancelled_and_expired_bookings_remain_untouched():
    """Scenario 5: Past CANCELLED and EXPIRED bookings remain untouched and return 0."""
    now = timezone.now()
    cancelled_booking = _make_booking(
        status=BookingStatus.CANCELLED,
        end_at=now - timedelta(minutes=10),
    )
    expired_booking = _make_booking(
        status=BookingStatus.EXPIRED,
        end_at=now - timedelta(minutes=10),
    )

    completed_count = complete_expired_bookings(now=now)

    assert completed_count == 0
    cancelled_booking.refresh_from_db()
    expired_booking.refresh_from_db()
    assert cancelled_booking.status == BookingStatus.CANCELLED
    assert expired_booking.status == BookingStatus.EXPIRED


def test_already_completed_booking_untouched_and_second_run_returns_zero():
    """Scenario 6: Already-COMPLETED booking is untouched and a second run returns 0."""
    now = timezone.now()
    already_completed = _make_booking(
        status=BookingStatus.COMPLETED,
        end_at=now - timedelta(hours=2),
    )
    already_completed_updated_at = already_completed.updated_at
    eligible = _make_booking(
        status=BookingStatus.CONFIRMED,
        end_at=now - timedelta(hours=1),
    )

    first_count = complete_expired_bookings(now=now)

    assert first_count == 1
    already_completed.refresh_from_db()
    eligible.refresh_from_db()
    assert already_completed.status == BookingStatus.COMPLETED
    assert already_completed.updated_at == already_completed_updated_at
    assert eligible.status == BookingStatus.COMPLETED

    eligible_updated_at = eligible.updated_at
    second_count = complete_expired_bookings(now=now)

    assert second_count == 0
    already_completed.refresh_from_db()
    eligible.refresh_from_db()
    assert already_completed.updated_at == already_completed_updated_at
    assert eligible.updated_at == eligible_updated_at


def test_bulk_completion_order_naive_datetime_rejection_and_zero_pii_in_logs(caplog):
    """Scenario 7: 3 past + 2 future CONFIRMED; deterministic order; naive now rejected; zero PII."""
    now = timezone.now()
    # Create out of end_at order so insertion ID order differs from end_at ASC order.
    past_1h = _make_booking(status=BookingStatus.CONFIRMED, end_at=now - timedelta(hours=1))
    past_3h = _make_booking(status=BookingStatus.CONFIRMED, end_at=now - timedelta(hours=3))
    past_2h = _make_booking(status=BookingStatus.CONFIRMED, end_at=now - timedelta(hours=2))
    future_1h = _make_booking(status=BookingStatus.CONFIRMED, end_at=now + timedelta(hours=1))
    future_2h = _make_booking(status=BookingStatus.CONFIRMED, end_at=now + timedelta(hours=2))
    all_bookings = [past_1h, past_3h, past_2h, future_1h, future_2h]

    with caplog.at_level(logging.INFO, logger="apps.bookings.services"):
        completed_count = complete_expired_bookings(now=now)

    assert completed_count == 3

    for b in (past_3h, past_2h, past_1h):
        b.refresh_from_db()
        assert b.status == BookingStatus.COMPLETED
    for b in (future_1h, future_2h):
        b.refresh_from_db()
        assert b.status == BookingStatus.CONFIRMED

    logged_ids = [
        int(match.group(1))
        for record in caplog.records
        if (match := _LOG_BOOKING_ID_RE.search(record.getMessage())) is not None
    ]
    assert logged_ids == [past_3h.id, past_2h.id, past_1h.id]
    assert "completed_count=3" in caplog.text

    for b in all_bookings:
        assert b.customer.phone not in caplog.text

    with pytest.raises(ValueError, match="timezone-aware"):
        complete_expired_bookings(now=datetime(2026, 1, 10, 12, 0))


def test_same_end_at_tiebreaks_by_id_asc_and_default_now_uses_utc(caplog):
    """Tie-breaker on equal end_at orders by id ASC, and omitted now defaults to aware UTC."""
    now = timezone.now()
    first = _make_booking(status=BookingStatus.CONFIRMED, end_at=now - timedelta(minutes=20))
    second = _make_booking(status=BookingStatus.CONFIRMED, end_at=now - timedelta(minutes=20))
    assert first.id < second.id

    with caplog.at_level(logging.INFO, logger="apps.bookings.services"):
        completed_count = complete_expired_bookings()

    assert completed_count == 2
    logged_ids = [
        int(match.group(1))
        for record in caplog.records
        if (match := _LOG_BOOKING_ID_RE.search(record.getMessage())) is not None
    ]
    assert logged_ids == [first.id, second.id]


def test_management_command_dry_run_and_normal_execution():
    """Scenario 8: Management command --dry-run prints IDs without mutating; normal run completes."""
    now = timezone.now()
    past_oldest = _make_booking(status=BookingStatus.CONFIRMED, end_at=now - timedelta(hours=2))
    past_newer = _make_booking(status=BookingStatus.CONFIRMED, end_at=now - timedelta(hours=1))
    future_booking = _make_booking(status=BookingStatus.CONFIRMED, end_at=now + timedelta(hours=2))
    all_bookings = [past_oldest, past_newer, future_booking]

    dry_stdout = StringIO()
    call_command("complete_expired_bookings", "--dry-run", stdout=dry_stdout)
    dry_output = dry_stdout.getvalue()

    assert "Eligible bookings (2)" in dry_output
    assert f"{past_oldest.id}, {past_newer.id}" in dry_output
    assert str(future_booking.id) not in dry_output
    for b in all_bookings:
        assert b.customer.phone not in dry_output

    for b in all_bookings:
        b.refresh_from_db()
        assert b.status == BookingStatus.CONFIRMED

    run_stdout = StringIO()
    call_command("complete_expired_bookings", stdout=run_stdout)
    run_output = run_stdout.getvalue()

    assert "Completed 2 expired booking(s)." in run_output
    for b in all_bookings:
        assert b.customer.phone not in run_output

    past_oldest.refresh_from_db()
    past_newer.refresh_from_db()
    future_booking.refresh_from_db()
    assert past_oldest.status == BookingStatus.COMPLETED
    assert past_newer.status == BookingStatus.COMPLETED
    assert future_booking.status == BookingStatus.CONFIRMED


def test_celery_task_delegates_and_retries_only_on_transient_errors():
    """Scenario 9: Celery task delegates, retries OperationalError, does not retry ValueError."""
    now = timezone.now()
    booking = _make_booking(status=BookingStatus.CONFIRMED, end_at=now - timedelta(minutes=15))

    result = complete_expired_bookings_task()

    assert result == 1
    booking.refresh_from_db()
    assert booking.status == BookingStatus.COMPLETED

    transient_error = OperationalError("transient db error")
    complete_expired_bookings_task.push_request(called_directly=False, is_eager=True, retries=0)
    try:
        with (
            patch(
                "apps.bookings.tasks.complete_expired_bookings",
                side_effect=transient_error,
            ),
            patch.object(
                complete_expired_bookings_task,
                "retry",
                wraps=complete_expired_bookings_task.retry,
            ) as mock_retry,
        ):
            with pytest.raises(Retry) as retry_exc:
                complete_expired_bookings_task()
            mock_retry.assert_called_once_with(exc=transient_error)
            assert retry_exc.value.exc is transient_error
    finally:
        complete_expired_bookings_task.pop_request()

    with (
        patch(
            "apps.bookings.tasks.complete_expired_bookings",
            side_effect=ValueError("now must be timezone-aware"),
        ),
        patch.object(
            complete_expired_bookings_task,
            "retry",
            wraps=complete_expired_bookings_task.retry,
        ) as mock_retry,
    ):
        with pytest.raises(ValueError, match="timezone-aware"):
            complete_expired_bookings_task()
        mock_retry.assert_not_called()


def test_completed_booking_visible_in_my_bookings_and_split_receipt_endpoints():
    """Scenario 10: Auto-completed booking visible in /bookings/my/ and /receipt/ with unchanged totals."""
    now = timezone.now()
    customer = UserFactory(role=UserRole.CUSTOMER)
    venue = VenueFactory(is_approved=True)
    pin = TablePinFactory(venue=venue, table_number="T-09", reservation_fee_toman=75_000)
    addon = DesignAddonFactory(venue=venue, title="Candlelight Setup", fee=45_000)

    booking = _make_booking(
        status=BookingStatus.CONFIRMED,
        end_at=now - timedelta(minutes=30),
        customer=customer,
        table_pin=pin,
        amount_online_toman=75_000,
        amount_in_person_toman=45_000,
    )
    BookingAddonFactory(
        booking=booking,
        design_addon=addon,
        price_snapshot_toman=45_000,
    )
    PaymentTransaction.objects.create(
        booking=booking,
        customer=customer,
        amount_toman=75_000,
        currency="TOMAN",
        status=PaymentStatus.SUCCESS,
        provider_name="sandbox",
        provider_reference=f"SBX-AUTO-{booking.id}",
        idempotency_key=f"auto-complete-{booking.id}",
        card_pan_masked="603799******4321",
        verified_at=now - timedelta(hours=3),
    )

    client = authenticate_client(Client(), customer)
    receipt_before_resp = client.get(f"/api/v1/bookings/{booking.id}/receipt/")
    assert receipt_before_resp.status_code == 200
    receipt_before = receipt_before_resp.json()
    assert receipt_before["status"] == BookingStatus.CONFIRMED

    assert complete_expired_bookings(now=now) == 1

    my_resp = client.get("/api/v1/bookings/my/")
    assert my_resp.status_code == 200
    my_items = [item for item in my_resp.json() if item["booking_id"] == booking.id]
    assert len(my_items) == 1
    assert my_items[0]["status"] == BookingStatus.COMPLETED
    assert my_items[0]["is_cancellable"] is False
    assert my_items[0]["cancel_refund_toman"] == 0

    receipt_after_resp = client.get(f"/api/v1/bookings/{booking.id}/receipt/")
    assert receipt_after_resp.status_code == 200
    receipt_after = receipt_after_resp.json()
    assert receipt_after["status"] == BookingStatus.COMPLETED
    assert receipt_after["total_online_toman"] == receipt_before["total_online_toman"] == 75_000
    assert receipt_after["total_in_person_toman"] == receipt_before["total_in_person_toman"] == 45_000
    assert receipt_after["grand_total_toman"] == receipt_before["grand_total_toman"] == 120_000
    assert receipt_after["paid_online"] == receipt_before["paid_online"]
    assert receipt_after["payable_in_person"] == receipt_before["payable_in_person"]


@pytest.mark.django_db(transaction=True)
def test_postgresql_select_for_update_skip_locked_concurrency():
    """Verify PostgreSQL select_for_update(skip_locked=True) under concurrent workers and row locks."""
    assert connection.vendor == "postgresql"
    now = timezone.now()

    # Part A: 2 concurrent workers synchronized via Barrier process 6 past CONFIRMED bookings cleanly.
    bookings = [
        _make_booking(status=BookingStatus.CONFIRMED, end_at=now - timedelta(minutes=10 + idx))
        for idx in range(6)
    ]
    barrier = threading.Barrier(2)

    def _concurrent_worker() -> int:
        try:
            barrier.wait(timeout=5)
            return complete_expired_bookings(now=now)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_concurrent_worker), pool.submit(_concurrent_worker)]
        counts = [future.result(timeout=15) for future in futures]

    assert sum(counts) == 6
    for booking in bookings:
        booking.refresh_from_db()
        assert booking.status == BookingStatus.COMPLETED

    # Part B: A locked Booking A is skipped immediately while unlocked Booking B completes.
    booking_a = _make_booking(status=BookingStatus.CONFIRMED, end_at=now - timedelta(minutes=30))
    booking_b = _make_booking(status=BookingStatus.CONFIRMED, end_at=now - timedelta(minutes=20))
    lock_acquired = threading.Event()
    release_lock = threading.Event()

    def _hold_row_lock() -> None:
        try:
            with transaction.atomic():
                Booking.objects.select_for_update().get(pk=booking_a.id)
                lock_acquired.set()
                assert release_lock.wait(timeout=10)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=1) as lock_pool:
        lock_future = lock_pool.submit(_hold_row_lock)
        try:
            assert lock_acquired.wait(timeout=5)
            first_count = complete_expired_bookings(now=now)
            assert first_count == 1
            booking_a.refresh_from_db()
            booking_b.refresh_from_db()
            assert booking_a.status == BookingStatus.CONFIRMED
            assert booking_b.status == BookingStatus.COMPLETED
        finally:
            release_lock.set()
        lock_future.result(timeout=10)

    second_count = complete_expired_bookings(now=now)
    assert second_count == 1
    booking_a.refresh_from_db()
    assert booking_a.status == BookingStatus.COMPLETED


def test_batch_cap_and_initiated_booking_exclusion():
    """Batch cap bounds completions per run in deterministic order and excludes INITIATED bookings."""
    now = timezone.now()
    earliest = _make_booking(status=BookingStatus.CONFIRMED, end_at=now - timedelta(hours=3))
    middle = _make_booking(status=BookingStatus.CONFIRMED, end_at=now - timedelta(hours=2))
    latest = _make_booking(status=BookingStatus.CONFIRMED, end_at=now - timedelta(hours=1))
    initiated = _make_booking(status=BookingStatus.INITIATED, end_at=now - timedelta(hours=4))

    with patch("apps.bookings.services.MAX_AUTO_COMPLETE_BATCH", 2):
        assert complete_expired_bookings(now=now) == 2

        earliest.refresh_from_db()
        middle.refresh_from_db()
        latest.refresh_from_db()
        initiated.refresh_from_db()
        assert earliest.status == BookingStatus.COMPLETED
        assert middle.status == BookingStatus.COMPLETED
        assert latest.status == BookingStatus.CONFIRMED
        assert initiated.status == BookingStatus.INITIATED

        assert complete_expired_bookings(now=now) == 1

        latest.refresh_from_db()
        initiated.refresh_from_db()
        assert latest.status == BookingStatus.COMPLETED
        assert initiated.status == BookingStatus.INITIATED

        assert complete_expired_bookings(now=now) == 0

        initiated.refresh_from_db()
        assert initiated.status == BookingStatus.INITIATED


def test_post_auto_completion_cancel_rejected_409_with_zero_wallet_refund():
    """Auto-completed booking cannot be cancelled (409 BOOKING_NOT_CANCELLABLE) and creates zero wallet entries."""
    now = timezone.now()
    customer = UserFactory(role=UserRole.CUSTOMER)
    # Even if start_at is >36h from real wall-clock now, COMPLETED status must reject cancellation.
    future_start = now + timedelta(hours=48)
    booking = _make_booking(
        status=BookingStatus.CONFIRMED,
        end_at=future_start + timedelta(minutes=90),
        customer=customer,
        amount_online_toman=80_000,
    )

    assert complete_expired_bookings(now=booking.end_at + timedelta(minutes=1)) == 1
    booking.refresh_from_db()
    assert booking.status == BookingStatus.COMPLETED

    client = authenticate_client(Client(), customer)
    cancel_resp = client.post(f"/api/v1/bookings/{booking.id}/cancel/")

    assert cancel_resp.status_code == 409
    assert cancel_resp.json()["error_code"] == "BOOKING_NOT_CANCELLABLE"
    booking.refresh_from_db()
    assert booking.status == BookingStatus.COMPLETED
    assert WalletTransaction.objects.filter(wallet__user=customer).count() == 0

