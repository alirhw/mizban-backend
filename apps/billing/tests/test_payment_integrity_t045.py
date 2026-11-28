"""Reproduction and integrity tests for payment services (Task T-045)."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.billing.models import PaymentStatus, PaymentTransaction
from apps.billing.services.payment import (
    handle_payment_callback,
    initiate_payment_for_booking,
    pay_booking_with_wallet,
)
from apps.bookings.models import BookingStatus
from apps.bookings.services import create_booking_lock
from apps.panoramas.tests.factories import TablePinFactory
from apps.venues.tests.factories import UserFactory
from apps.wallets.services import credit_wallet, get_or_create_wallet_for_user
from core.exceptions import InvalidStatusTransitionError

pytestmark = [
    pytest.mark.django_db(transaction=True),
]


def _make_locked_booking(customer=None):
    if customer is None:
        customer = UserFactory(role=UserRole.CUSTOMER)
    pin = TablePinFactory(reservation_fee_toman=150_000)
    now = timezone.now()
    slot_dt = (now + timedelta(days=3)).replace(hour=10, minute=0, second=0, microsecond=0)
    booking = create_booking_lock(
        user=customer,
        table_pin=pin,
        slot_date=slot_dt.date(),
        slot_start_time=slot_dt.time(),
        now=now,
    )
    return customer, booking


def test_second_distinct_payment_callback_flags_refund_required():
    """M1: A second distinct SUCCESS payment for an already-CONFIRMED booking must set refund_required=True."""
    customer, booking = _make_locked_booking()

    tx1, _ = initiate_payment_for_booking(
        booking_id=booking.id,
        user=customer,
        idempotency_key="t045-m1-key-1",
        callback_url="http://localhost:3000/bookings/callback",
    )
    tx2, _ = initiate_payment_for_booking(
        booking_id=booking.id,
        user=customer,
        idempotency_key="t045-m1-key-2",
        callback_url="http://localhost:3000/bookings/callback",
    )

    res1 = handle_payment_callback(
        callback_params={"authority": tx1.provider_reference, "status": "OK"},
        gateway_name="sandbox",
    )
    assert res1.booking_status == BookingStatus.CONFIRMED
    assert res1.payment_status == PaymentStatus.SUCCESS
    assert res1.refund_required is False

    # Re-callback of the confirming transaction must keep refund_required=False
    replay1 = handle_payment_callback(
        callback_params={"authority": tx1.provider_reference, "status": "OK"},
        gateway_name="sandbox",
    )
    assert replay1.refund_required is False

    # Distinct second payment callback arriving after booking is CONFIRMED -> refund_required=True
    res2 = handle_payment_callback(
        callback_params={"authority": tx2.provider_reference, "status": "OK"},
        gateway_name="sandbox",
    )
    assert res2.booking_status == BookingStatus.CONFIRMED
    assert res2.payment_status == PaymentStatus.SUCCESS
    assert res2.refund_required is True

    tx2.refresh_from_db()
    assert tx2.refund_required is True
    booking.refresh_from_db()
    assert booking.status == BookingStatus.CONFIRMED


def test_gateway_callback_after_wallet_pay_flags_refund_required():
    """M1 wallet variant: wallet-pay confirms booking, then gateway callback arrives -> refund_required=True."""
    customer, booking = _make_locked_booking()
    wallet = get_or_create_wallet_for_user(customer)
    credit_wallet(
        wallet,
        200_000,
        reason="test-topup",
        idempotency_key=f"topup-{booking.id}",
    )

    tx_gw, _ = initiate_payment_for_booking(
        booking_id=booking.id,
        user=customer,
        idempotency_key="t045-wallet-gw-1",
        callback_url="http://localhost:3000/bookings/callback",
    )
    pay_booking_with_wallet(
        booking_id=booking.id,
        user=customer,
        idempotency_key="t045-wallet-pay-1",
    )

    res = handle_payment_callback(
        callback_params={"authority": tx_gw.provider_reference, "status": "OK"},
        gateway_name="sandbox",
    )
    assert res.booking_status == BookingStatus.CONFIRMED
    assert res.payment_status == PaymentStatus.SUCCESS
    assert res.refund_required is True

    tx_gw.refresh_from_db()
    assert tx_gw.refund_required is True


def test_concurrent_same_key_initiate_returns_single_tx_no_500():
    """m6: Two concurrent initiate calls with the same idempotency_key return the same tx without IntegrityError."""
    customer, booking = _make_locked_booking()
    barrier = threading.Barrier(2)

    def _call():
        barrier.wait(timeout=5)
        try:
            return initiate_payment_for_booking(
                booking_id=booking.id,
                user=customer,
                idempotency_key="t045-concurrent-same-key",
                callback_url="http://localhost:3000/bookings/callback",
            )
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(_call)
        f2 = pool.submit(_call)
        tx1, _ = f1.result()
        tx2, _ = f2.result()

    assert tx1.id == tx2.id
    assert (
        PaymentTransaction.objects.filter(idempotency_key="t045-concurrent-same-key").count()
        == 1
    )


def test_initiate_payment_and_wallet_pay_reject_lock_expires_at_none():
    """m12: lock_expires_at=None is treated as expired (fail-closed) by both initiate and wallet-pay."""
    customer, booking = _make_locked_booking()
    booking.lock_expires_at = None
    booking.save(update_fields=["lock_expires_at", "updated_at"])

    with pytest.raises(InvalidStatusTransitionError):
        initiate_payment_for_booking(
            booking_id=booking.id,
            user=customer,
            idempotency_key="t045-none-lock-init",
            callback_url="http://localhost:3000/bookings/callback",
        )

    with pytest.raises(InvalidStatusTransitionError):
        pay_booking_with_wallet(
            booking_id=booking.id,
            user=customer,
            idempotency_key="t045-none-lock-wallet",
        )
