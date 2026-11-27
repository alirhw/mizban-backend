"""Tests for booking cancellation and wallet refund credit service (BR-004 / UF-003).

Task T-023 (PH-05 / WS-BILLING-WALLET / BR-004 / ADR-006):
1. Happy path: CONFIRMED booking cancelled >= 36h ahead -> CANCELLED, 100% amount_online_toman credited to wallet.
2. Boundary: exactly 36h ahead is allowed and refunds.
3. Boundary: 35h59m ahead is rejected with CANCELLATION_WINDOW_CLOSED (400), booking stays CONFIRMED, 0 wallet credit.
4. Add-on split: in-person add-on fee is NEVER refunded; only amount_online_toman is credited.
5. Double cancellation: second call returns idempotently, refunded_to_wallet_toman=0, wallet credited exactly once.
6. PENDING_PAYMENT cancellation: releases hold cleanly with zero refund and zero ledger entries.
7. ADR-006 boundary: EXPIRED booking carrying refund_required payment is rejected (409) and creates ZERO wallet credit.
8. COMPLETED booking cancellation rejected (409).
9. Authorization: foreign customer returns 403; unauthenticated returns 401.
10. Non-existent booking returns 404.
11. Freed slot is immediately bookable after cancellation.
12. Concurrency race test on PostgreSQL: concurrent cancel calls produce exactly one credit and one ledger entry.
13. Trailing-slash tolerance on API endpoint.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.db import connection
from django.test import Client
from django.utils import timezone

from apps.billing.models import PaymentStatus, PaymentTransaction
from apps.bookings.models import BookingStatus
from apps.bookings.services import (
    cancel_booking,
    create_booking_lock,
    is_table_slot_occupied,
)
from apps.bookings.tests.factories import BookingFactory
from apps.panoramas.tests.factories import TablePinFactory
from apps.venues.tests.factories import UserFactory
from apps.wallets.models import Wallet, WalletTransaction, WalletTransactionType
from core.exceptions import CancellationWindowClosedError
from core.testing import authenticate_client


@pytest.fixture(autouse=True)
def setup_test_env(settings):
    settings.DEBUG = True
    yield


@pytest.fixture
def client():
    return Client()



@pytest.fixture
def customer():
    return UserFactory(role="CUSTOMER")


@pytest.fixture
def pin():
    return TablePinFactory(reservation_fee_toman=50_000)


@pytest.fixture
def confirmed_booking(customer, pin):
    """Booking CONFIRMED 48 hours in the future with 50,000 Toman online table fee."""
    now = timezone.now()
    target_dt = now + timedelta(hours=48)
    booking = BookingFactory(
        customer=customer,
        table_pin=pin,
        venue=pin.venue,
        status=BookingStatus.CONFIRMED,
        start_at=target_dt,
        end_at=target_dt + timedelta(minutes=90),
        slot_date=target_dt.date(),
        slot_start_time=target_dt.time(),
        amount_online_toman=50_000,
        amount_in_person_toman=0,
    )
    return booking


# ==============================================================================
# 1. Happy Path & Window Validation (BR-004)
# ==============================================================================


@pytest.mark.django_db
def test_happy_path_confirmed_booking_cancelled_48h_ahead(client, customer, confirmed_booking):
    """CONFIRMED booking cancelled 48h ahead: status CANCELLED, wallet credited full online fee."""
    authenticate_client(client, customer)
    headers = {}
    url = f"/api/v1/bookings/{confirmed_booking.id}/cancel/"

    resp = client.post(url, **headers)
    assert resp.status_code == 200

    data = resp.json()
    assert data["booking_id"] == confirmed_booking.id
    assert data["status"] == BookingStatus.CANCELLED
    assert data["refunded_to_wallet_toman"] == 50_000
    assert data["wallet_balance_toman"] == 50_000

    confirmed_booking.refresh_from_db()
    assert confirmed_booking.status == BookingStatus.CANCELLED

    # Verify wallet ledger entry
    wallet = customer.wallet
    assert wallet.balance_toman == 50_000

    ledger_entries = WalletTransaction.objects.filter(wallet=wallet)
    assert ledger_entries.count() == 1
    tx = ledger_entries.first()
    assert tx.type == WalletTransactionType.CREDIT
    assert tx.amount_toman == 50_000
    assert tx.balance_after_toman == 50_000
    assert tx.booking == confirmed_booking
    assert tx.idempotency_key == f"cancel-refund-{confirmed_booking.id}"


@pytest.mark.django_db
def test_boundary_cancellation_exactly_36h_ahead_allowed_and_refunds(customer, pin):
    """Boundary test: exactly 36h before start is allowed and refunds full online fee."""
    now = timezone.now()
    start_at = now + timedelta(hours=36)
    booking = BookingFactory(
        customer=customer,
        table_pin=pin,
        status=BookingStatus.CONFIRMED,
        start_at=start_at,
        amount_online_toman=50_000,
    )

    result = cancel_booking(booking=booking, actor=customer, now=now)
    assert result.status == BookingStatus.CANCELLED
    assert result.refunded_to_wallet_toman == 50_000
    assert result.wallet_balance_toman == 50_000

    booking.refresh_from_db()
    assert booking.status == BookingStatus.CANCELLED
    assert customer.wallet.balance_toman == 50_000


@pytest.mark.django_db
def test_boundary_cancellation_35h59m_ahead_rejected_with_window_error(client, customer, pin):
    """Boundary test: 35h59m before start is rejected (400 CANCELLATION_WINDOW_CLOSED)."""
    now = timezone.now()
    start_at = now + timedelta(hours=35, minutes=59)
    booking = BookingFactory(
        customer=customer,
        table_pin=pin,
        status=BookingStatus.CONFIRMED,
        start_at=start_at,
        amount_online_toman=50_000,
    )

    # Direct service call raises CancellationWindowClosedError
    with pytest.raises(CancellationWindowClosedError):
        cancel_booking(booking=booking, actor=customer, now=now)

    # API call returns HTTP 400 with standard envelope
    authenticate_client(client, customer)
    headers = {}
    resp = client.post(f"/api/v1/bookings/{booking.id}/cancel/", **headers)
    assert resp.status_code == 400
    err = resp.json()
    assert err["error_code"] == "CANCELLATION_WINDOW_CLOSED"

    # Invariants: booking stays CONFIRMED, zero wallet credit
    booking.refresh_from_db()
    assert booking.status == BookingStatus.CONFIRMED
    assert not Wallet.objects.filter(user=customer).exists()
    assert WalletTransaction.objects.count() == 0


@pytest.mark.django_db
def test_in_person_addons_are_never_refunded(client, customer, pin):
    """Add-ons paid in person are never refunded; only amount_online_toman is credited."""
    now = timezone.now()
    start_at = now + timedelta(hours=48)
    booking = BookingFactory(
        customer=customer,
        table_pin=pin,
        status=BookingStatus.CONFIRMED,
        start_at=start_at,
        amount_online_toman=50_000,
        amount_in_person_toman=300_000,  # In-person add-on
    )

    authenticate_client(client, customer)
    headers = {}
    resp = client.post(f"/api/v1/bookings/{booking.id}/cancel/", **headers)
    assert resp.status_code == 200

    data = resp.json()
    assert data["refunded_to_wallet_toman"] == 50_000  # NOT 350_000
    assert customer.wallet.balance_toman == 50_000


# ==============================================================================
# 2. Idempotency & Repeat Calls (UF-003)
# ==============================================================================


@pytest.mark.django_db
def test_double_cancellation_is_idempotent(client, customer, confirmed_booking):
    """Second cancellation call returns idempotently, refunded_to_wallet_toman=0, wallet credited once."""
    authenticate_client(client, customer)
    headers = {}
    url = f"/api/v1/bookings/{confirmed_booking.id}/cancel/"

    # 1. First call cancels and refunds
    resp1 = client.post(url, **headers)
    assert resp1.status_code == 200
    assert resp1.json()["refunded_to_wallet_toman"] == 50_000

    # 2. Second call replays idempotently
    resp2 = client.post(url, **headers)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["status"] == BookingStatus.CANCELLED
    assert data2["refunded_to_wallet_toman"] == 0  # Zero additional refund

    # Invariants: wallet credited exactly once, exactly one ledger row
    assert customer.wallet.balance_toman == 50_000  # NOT 100_000
    assert WalletTransaction.objects.filter(wallet=customer.wallet).count() == 1


# ==============================================================================
# 3. Non-Confirmed Bookings (PENDING_PAYMENT, EXPIRED, COMPLETED)
# ==============================================================================


@pytest.mark.django_db
def test_pending_payment_cancellation_releases_hold_without_credit(client, customer, pin):
    """Cancelling a PENDING_PAYMENT booking releases hold early with 0 refund and 0 ledger entries."""
    booking = BookingFactory(
        customer=customer,
        table_pin=pin,
        status=BookingStatus.PENDING_PAYMENT,
        amount_online_toman=50_000,
    )

    authenticate_client(client, customer)
    headers = {}
    resp = client.post(f"/api/v1/bookings/{booking.id}/cancel/", **headers)
    assert resp.status_code == 200

    data = resp.json()
    assert data["status"] == BookingStatus.CANCELLED
    assert data["refunded_to_wallet_toman"] == 0
    assert data["wallet_balance_toman"] is None

    booking.refresh_from_db()
    assert booking.status == BookingStatus.CANCELLED
    assert not Wallet.objects.filter(user=customer).exists()
    assert WalletTransaction.objects.count() == 0


@pytest.mark.django_db
def test_cancelling_expired_booking_with_refund_required_payment_rejected_409(client, customer, pin):
    """ADR-006 boundary: EXPIRED booking with refund_required payment is rejected (409) with no wallet credit."""
    booking = BookingFactory(
        customer=customer,
        table_pin=pin,
        status=BookingStatus.EXPIRED,
        amount_online_toman=50_000,
    )
    # Payment was flagged for bank card refund under ADR-006
    PaymentTransaction.objects.create(
        booking=booking,
        customer=customer,
        amount_toman=50_000,
        status=PaymentStatus.SUCCESS,
        provider_reference="REF-EXPIRED-LATE",
        idempotency_key="late-pay-tx-1",
        refund_required=True,
    )

    authenticate_client(client, customer)
    headers = {}
    resp = client.post(f"/api/v1/bookings/{booking.id}/cancel/", **headers)
    assert resp.status_code == 409
    err = resp.json()
    assert err["error_code"] == "BOOKING_NOT_CANCELLABLE"

    booking.refresh_from_db()
    assert booking.status == BookingStatus.EXPIRED
    assert not Wallet.objects.filter(user=customer).exists()
    assert WalletTransaction.objects.count() == 0


@pytest.mark.django_db
def test_completed_booking_cancellation_rejected_409(client, customer, pin):
    """Completed booking cancellation is rejected with 409 BOOKING_NOT_CANCELLABLE."""
    booking = BookingFactory(
        customer=customer,
        table_pin=pin,
        status=BookingStatus.COMPLETED,
    )

    authenticate_client(client, customer)
    headers = {}
    resp = client.post(f"/api/v1/bookings/{booking.id}/cancel/", **headers)
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "BOOKING_NOT_CANCELLABLE"

    booking.refresh_from_db()
    assert booking.status == BookingStatus.COMPLETED


# ==============================================================================
# 4. Auth & Authorization (401, 403, 404)
# ==============================================================================


@pytest.mark.django_db
def test_unauthenticated_cancellation_returns_401(client, confirmed_booking):
    """Unauthenticated cancel request returns 401."""
    resp = client.post(f"/api/v1/bookings/{confirmed_booking.id}/cancel/")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_foreign_customer_cancellation_returns_403(client, confirmed_booking):
    """Another customer attempting to cancel someone else's booking returns 403."""
    attacker = UserFactory(role="CUSTOMER")
    authenticate_client(client, attacker)
    headers = {}

    resp = client.post(f"/api/v1/bookings/{confirmed_booking.id}/cancel/", **headers)
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "FORBIDDEN"

    confirmed_booking.refresh_from_db()
    assert confirmed_booking.status == BookingStatus.CONFIRMED
    assert not Wallet.objects.filter(user=confirmed_booking.customer).exists()


@pytest.mark.django_db
def test_unknown_booking_cancellation_returns_404(client, customer):
    """Non-existent booking returns 404 NOT_FOUND."""
    authenticate_client(client, customer)
    headers = {}
    resp = client.post("/api/v1/bookings/999999/cancel/", **headers)
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "NOT_FOUND"


# ==============================================================================
# 5. Freed Slot Re-Bookability
# ==============================================================================


@pytest.mark.django_db
def test_freed_slot_is_immediately_bookable_after_cancellation(customer, pin, confirmed_booking):
    """Freed slot can immediately be locked and booked by another customer."""
    # Before cancellation: slot is occupied
    assert is_table_slot_occupied(pin, start_at=confirmed_booking.start_at) is True

    # Customer A cancels
    cancel_booking(booking=confirmed_booking, actor=customer)
    confirmed_booking.refresh_from_db()
    assert confirmed_booking.status == BookingStatus.CANCELLED

    # After cancellation: slot is NO LONGER occupied
    assert is_table_slot_occupied(pin, start_at=confirmed_booking.start_at) is False

    # Customer B successfully initiates hold on the same slot
    customer_b = UserFactory(role="CUSTOMER")
    new_hold = create_booking_lock(
        user=customer_b,
        table_pin=pin,
        slot_date=confirmed_booking.slot_date,
        slot_start_time=confirmed_booking.slot_start_time,
    )
    assert new_hold.status == BookingStatus.PENDING_PAYMENT
    assert new_hold.customer == customer_b


# ==============================================================================
# 6. Trailing-Slash Tolerance
# ==============================================================================


@pytest.mark.django_db
def test_cancellation_endpoint_trailing_slash_tolerance(client, customer, pin):
    """Both /cancel/ and /cancel routes work without redirect."""
    now = timezone.now()

    for idx, path_suffix in enumerate(["/cancel/", "/cancel"]):
        target_dt = now + timedelta(hours=48 + idx)
        b = BookingFactory(
            customer=customer,
            table_pin=pin,
            status=BookingStatus.CONFIRMED,
            start_at=target_dt,
            amount_online_toman=50_000,
        )
        authenticate_client(client, customer)
        headers = {}
        resp = client.post(f"/api/v1/bookings/{b.id}{path_suffix}", **headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == BookingStatus.CANCELLED


# ==============================================================================
# 7. PostgreSQL Concurrency Race Condition Test
# ==============================================================================


@pytest.mark.django_db(transaction=True)
def test_concurrency_race_concurrent_cancel_calls_produce_exactly_one_credit():
    """THE RACE (BR-004 / TD-005): Two concurrent cancel calls for the same booking.

    Row-level lock (select_for_update) on Booking serializes both threads.
    Exactly one call performs the cancellation and credits the wallet; the other returns 0 refund.
    Zero double-refunds occur.
    """
    customer = UserFactory(role="CUSTOMER")
    pin = TablePinFactory(reservation_fee_toman=50_000)
    now = timezone.now()
    target_dt = now + timedelta(hours=48)

    booking = BookingFactory(
        customer=customer,
        table_pin=pin,
        status=BookingStatus.CONFIRMED,
        start_at=target_dt,
        amount_online_toman=50_000,
    )

    def _execute_cancel():
        try:
            return cancel_booking(booking=booking.id, actor=customer, now=now)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(_execute_cancel)
        future_b = pool.submit(_execute_cancel)
        res_a = future_a.result()
        res_b = future_b.result()

    outcomes = sorted([res_a.refunded_to_wallet_toman, res_b.refunded_to_wallet_toman])
    assert outcomes == [0, 50_000]

    # Verify database state
    booking.refresh_from_db()
    assert booking.status == BookingStatus.CANCELLED

    wallet = customer.wallet
    assert wallet.balance_toman == 50_000

    # Exactly ONE ledger row in WalletTransaction
    assert WalletTransaction.objects.filter(wallet=wallet).count() == 1
