"""PostgreSQL integration and concurrency tests for wallet booking payments (Task T-034-03 / FR-17)."""
from __future__ import annotations

import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import pytest
from django.db import connection
from django.test import Client
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.billing.models import PaymentStatus, PaymentTransaction
from apps.billing.services.payment import pay_booking_with_wallet
from apps.bookings.models import Booking, BookingStatus
from apps.bookings.tests.factories import BookingAddonFactory, BookingFactory
from apps.venues.tests.factories import DesignAddonFactory, UserFactory
from apps.wallets.models import Wallet, WalletTransaction, WalletTransactionType
from apps.wallets.services import credit_wallet, get_or_create_wallet_for_user
from core.exceptions import InvalidStatusTransitionError

pytestmark = pytest.mark.django_db


def _pending_booking(
    *,
    customer: Any = None,
    amount_online_toman: int = 100_000,
    amount_in_person_toman: int = 0,
    lock_expires_at: Any = None,
    status: str = BookingStatus.PENDING_PAYMENT,
) -> Booking:
    now = timezone.now()
    customer = customer or UserFactory(role=UserRole.CUSTOMER)
    booking = BookingFactory(
        customer=customer,
        status=status,
        amount_online_toman=amount_online_toman,
        amount_in_person_toman=amount_in_person_toman,
        locked_at=now,
        lock_expires_at=lock_expires_at if lock_expires_at is not None else now + timedelta(minutes=10),
    )
    if amount_in_person_toman > 0:
        addon = DesignAddonFactory(venue=booking.venue, fee=amount_in_person_toman)
        BookingAddonFactory(
            booking=booking,
            design_addon=addon,
            price_snapshot_toman=amount_in_person_toman,
        )
    return booking


def _funded_wallet(user: Any, balance_toman: int) -> Wallet:
    wallet = get_or_create_wallet_for_user(user)
    if balance_toman > 0:
        credit_wallet(
            wallet,
            balance_toman,
            reason="test-seed",
            idempotency_key=f"seed-{uuid.uuid4().hex}",
        )
        wallet.refresh_from_db()
    return wallet


def _post_wallet_pay(client: Client, payload: dict[str, Any]):
    return client.post(
        "/api/v1/billing/wallet-pay/",
        data=json.dumps(payload),
        content_type="application/json",
    )


def test_wallet_pay_happy_path_with_addons_and_receipt():
    customer = UserFactory(role=UserRole.CUSTOMER)
    wallet = _funded_wallet(customer, 300_000)
    booking = _pending_booking(
        customer=customer,
        amount_online_toman=120_000,
        amount_in_person_toman=250_000,
    )

    client = Client()
    client.force_login(customer)
    resp = _post_wallet_pay(
        client,
        {"booking_id": booking.id, "idempotency_key": f"wpay-{uuid.uuid4().hex}"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["booking_id"] == booking.id
    assert data["amount_toman"] == 120_000
    assert data["currency"] == "TOMAN"
    assert data["status"] == PaymentStatus.SUCCESS
    assert data["provider_name"] == "wallet"
    assert data["provider_reference"] is None
    assert data["tracking_code"] == ""
    assert data["card_pan_masked"] == ""
    assert data["verified_at"] is not None

    booking.refresh_from_db()
    assert booking.status == BookingStatus.CONFIRMED
    assert booking.amount_online_toman == 120_000
    assert booking.amount_in_person_toman == 250_000

    wallet.refresh_from_db()
    assert wallet.balance_toman == 180_000

    debits = WalletTransaction.objects.filter(wallet=wallet, type=WalletTransactionType.DEBIT)
    assert debits.count() == 1
    debit_tx = debits.get()
    assert debit_tx.amount_toman == 120_000
    assert debit_tx.balance_after_toman == 180_000
    assert debit_tx.reason == f"booking-pay:{booking.id}"
    assert debit_tx.idempotency_key == f"booking-pay:{booking.id}"
    assert debit_tx.booking_id == booking.id

    payments = PaymentTransaction.objects.filter(booking=booking)
    assert payments.count() == 1
    payment_tx = payments.get()
    assert payment_tx.status == PaymentStatus.SUCCESS
    assert payment_tx.provider_name == "wallet"
    assert payment_tx.provider_reference is None

    receipt_resp = client.get(f"/api/v1/bookings/{booking.id}/receipt/")
    assert receipt_resp.status_code == 200
    receipt = receipt_resp.json()
    assert receipt["total_online_toman"] == 120_000
    assert receipt["total_in_person_toman"] == 250_000
    assert receipt["grand_total_toman"] == 370_000
    assert receipt["paid_online"]["provider_name"] == "wallet"


def test_wallet_pay_exact_balance_leaves_zero():
    customer = UserFactory(role=UserRole.CUSTOMER)
    wallet = _funded_wallet(customer, 85_000)
    booking = _pending_booking(customer=customer, amount_online_toman=85_000)

    client = Client()
    client.force_login(customer)
    resp = _post_wallet_pay(
        client,
        {"booking_id": booking.id, "idempotency_key": f"wpay-{uuid.uuid4().hex}"},
    )

    assert resp.status_code == 200
    wallet.refresh_from_db()
    assert wallet.balance_toman == 0
    booking.refresh_from_db()
    assert booking.status == BookingStatus.CONFIRMED


def test_wallet_pay_insufficient_balance_rolls_back_with_zero_side_effects():
    customer = UserFactory(role=UserRole.CUSTOMER)
    wallet = _funded_wallet(customer, 84_999)
    booking = _pending_booking(customer=customer, amount_online_toman=85_000)

    client = Client()
    client.force_login(customer)
    resp = _post_wallet_pay(
        client,
        {"booking_id": booking.id, "idempotency_key": f"wpay-{uuid.uuid4().hex}"},
    )

    assert resp.status_code == 400
    assert resp.json()["error_code"] == "WALLET_INSUFFICIENT_BALANCE"

    wallet.refresh_from_db()
    assert wallet.balance_toman == 84_999
    assert WalletTransaction.objects.filter(wallet=wallet, type=WalletTransactionType.DEBIT).count() == 0
    assert PaymentTransaction.objects.filter(booking=booking).count() == 0

    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING_PAYMENT


def test_wallet_pay_idempotent_replay_returns_same_transaction_and_debits_once():
    customer = UserFactory(role=UserRole.CUSTOMER)
    wallet = _funded_wallet(customer, 200_000)
    booking = _pending_booking(customer=customer, amount_online_toman=80_000)
    key = f"wpay-idem-{uuid.uuid4().hex}"

    client = Client()
    client.force_login(customer)
    r1 = _post_wallet_pay(client, {"booking_id": booking.id, "idempotency_key": key})
    r2 = _post_wallet_pay(client, {"booking_id": booking.id, "idempotency_key": key})

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]

    wallet.refresh_from_db()
    assert wallet.balance_toman == 120_000
    assert WalletTransaction.objects.filter(wallet=wallet, type=WalletTransactionType.DEBIT).count() == 1
    assert PaymentTransaction.objects.filter(booking=booking).count() == 1


def test_wallet_pay_different_idempotency_key_on_confirmed_booking_rejected():
    customer = UserFactory(role=UserRole.CUSTOMER)
    wallet = _funded_wallet(customer, 250_000)
    booking = _pending_booking(customer=customer, amount_online_toman=90_000)

    client = Client()
    client.force_login(customer)
    r1 = _post_wallet_pay(
        client,
        {"booking_id": booking.id, "idempotency_key": f"wpay-1-{uuid.uuid4().hex}"},
    )
    assert r1.status_code == 200

    r2 = _post_wallet_pay(
        client,
        {"booking_id": booking.id, "idempotency_key": f"wpay-2-{uuid.uuid4().hex}"},
    )
    assert r2.status_code == 400
    assert r2.json()["error_code"] == "INVALID_STATUS_TRANSITION"

    wallet.refresh_from_db()
    assert wallet.balance_toman == 160_000
    assert WalletTransaction.objects.filter(wallet=wallet, type=WalletTransactionType.DEBIT).count() == 1
    assert PaymentTransaction.objects.filter(booking=booking).count() == 1


def test_wallet_pay_authorization_rejects_non_owner_and_venue_owner():
    owner = UserFactory(role=UserRole.CUSTOMER)
    other_customer = UserFactory(role=UserRole.CUSTOMER)
    venue_owner = UserFactory(role=UserRole.VENUE_OWNER)
    other_wallet = _funded_wallet(other_customer, 200_000)
    booking = _pending_booking(customer=owner, amount_online_toman=75_000)

    other_client = Client()
    other_client.force_login(other_customer)
    resp_other = _post_wallet_pay(
        other_client,
        {"booking_id": booking.id, "idempotency_key": f"wpay-{uuid.uuid4().hex}"},
    )
    assert resp_other.status_code == 403
    other_wallet.refresh_from_db()
    assert other_wallet.balance_toman == 200_000

    owner_client = Client()
    owner_client.force_login(venue_owner)
    resp_venue_owner = _post_wallet_pay(
        owner_client,
        {"booking_id": booking.id, "idempotency_key": f"wpay-{uuid.uuid4().hex}"},
    )
    assert resp_venue_owner.status_code == 403

    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING_PAYMENT
    assert PaymentTransaction.objects.filter(booking=booking).count() == 0


def test_wallet_pay_expired_lock_rejected():
    customer = UserFactory(role=UserRole.CUSTOMER)
    wallet = _funded_wallet(customer, 200_000)
    expired_at = timezone.now() - timedelta(seconds=1)
    booking = _pending_booking(
        customer=customer,
        amount_online_toman=70_000,
        lock_expires_at=expired_at,
    )

    client = Client()
    client.force_login(customer)
    resp = _post_wallet_pay(
        client,
        {"booking_id": booking.id, "idempotency_key": f"wpay-{uuid.uuid4().hex}"},
    )

    assert resp.status_code == 400
    assert resp.json()["error_code"] == "INVALID_STATUS_TRANSITION"

    wallet.refresh_from_db()
    assert wallet.balance_toman == 200_000
    assert WalletTransaction.objects.filter(wallet=wallet, type=WalletTransactionType.DEBIT).count() == 0
    assert PaymentTransaction.objects.filter(booking=booking).count() == 0

    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING_PAYMENT


@pytest.mark.parametrize(
    "invalid_status",
    [
        BookingStatus.CANCELLED,
        BookingStatus.EXPIRED,
        BookingStatus.INITIATED,
        BookingStatus.COMPLETED,
    ],
)
def test_wallet_pay_invalid_booking_statuses_rejected(invalid_status: str):
    customer: Any = UserFactory(role=UserRole.CUSTOMER)
    wallet = _funded_wallet(customer, 200_000)
    booking = _pending_booking(
        customer=customer,
        amount_online_toman=65_000,
        status=invalid_status,
    )

    client = Client()
    client.force_login(customer)
    resp = _post_wallet_pay(
        client,
        {"booking_id": booking.id, "idempotency_key": f"wpay-{uuid.uuid4().hex}"},
    )

    assert resp.status_code == 400
    assert resp.json()["error_code"] == "INVALID_STATUS_TRANSITION"

    wallet.refresh_from_db()
    assert wallet.balance_toman == 200_000
    assert WalletTransaction.objects.filter(wallet=wallet, type=WalletTransactionType.DEBIT).count() == 0
    assert PaymentTransaction.objects.filter(booking=booking).count() == 0

    booking.refresh_from_db()
    assert booking.status == invalid_status


def test_wallet_pay_nonexistent_booking_returns_404() -> None:
    customer: Any = UserFactory(role=UserRole.CUSTOMER)
    wallet = _funded_wallet(customer, 200_000)

    client = Client()
    client.force_login(customer)
    resp = _post_wallet_pay(
        client,
        {"booking_id": 999999, "idempotency_key": f"wpay-{uuid.uuid4().hex}"},
    )

    assert resp.status_code == 404
    wallet.refresh_from_db()
    assert wallet.balance_toman == 200_000
    assert WalletTransaction.objects.filter(wallet=wallet, type=WalletTransactionType.DEBIT).count() == 0
    assert PaymentTransaction.objects.filter(customer=customer).count() == 0


def test_wallet_pay_none_lock_expires_at_rejected() -> None:
    customer: Any = UserFactory(role=UserRole.CUSTOMER)
    wallet = _funded_wallet(customer, 200_000)
    booking = _pending_booking(customer=customer, amount_online_toman=70_000)
    Booking.objects.filter(pk=booking.id).update(lock_expires_at=None)
    booking.refresh_from_db()
    assert booking.lock_expires_at is None

    client = Client()
    client.force_login(customer)
    resp = _post_wallet_pay(
        client,
        {"booking_id": booking.id, "idempotency_key": f"wpay-{uuid.uuid4().hex}"},
    )

    assert resp.status_code == 400
    assert resp.json()["error_code"] == "INVALID_STATUS_TRANSITION"

    wallet.refresh_from_db()
    assert wallet.balance_toman == 200_000
    assert WalletTransaction.objects.filter(wallet=wallet, type=WalletTransactionType.DEBIT).count() == 0
    assert PaymentTransaction.objects.filter(booking=booking).count() == 0

    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING_PAYMENT


def test_wallet_pay_zero_amount_online_rejected() -> None:
    customer: Any = UserFactory(role=UserRole.CUSTOMER)
    wallet = _funded_wallet(customer, 200_000)
    booking = _pending_booking(customer=customer, amount_online_toman=0)

    client = Client()
    client.force_login(customer)
    resp = _post_wallet_pay(
        client,
        {"booking_id": booking.id, "idempotency_key": f"wpay-{uuid.uuid4().hex}"},
    )

    assert resp.status_code == 400
    assert resp.json()["error_code"] == "INVALID_WALLET_AMOUNT"

    wallet.refresh_from_db()
    assert wallet.balance_toman == 200_000
    assert WalletTransaction.objects.filter(wallet=wallet, type=WalletTransactionType.DEBIT).count() == 0
    assert PaymentTransaction.objects.filter(booking=booking).count() == 0

    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING_PAYMENT


@pytest.mark.django_db(transaction=True)
def test_concurrent_wallet_pay_distinct_keys_debits_once():
    customer = UserFactory(role=UserRole.CUSTOMER)
    wallet = _funded_wallet(customer, 200_000)
    booking = _pending_booking(customer=customer, amount_online_toman=100_000)

    barrier = threading.Barrier(2)

    def _call(key: str) -> tuple[str, int | None]:
        try:
            barrier.wait(timeout=5)
            tx = pay_booking_with_wallet(
                user=customer,
                booking_id=booking.id,
                idempotency_key=key,
            )
            return ("success", tx.id)
        except InvalidStatusTransitionError:
            return ("rejected", None)
        finally:
            connection.close()

    keys = [f"race-a-{uuid.uuid4().hex}", f"race-b-{uuid.uuid4().hex}"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(_call, keys))

    statuses = sorted(status for status, _ in outcomes)
    assert statuses == ["rejected", "success"]

    wallet.refresh_from_db()
    assert wallet.balance_toman == 100_000
    assert WalletTransaction.objects.filter(wallet=wallet, type=WalletTransactionType.DEBIT).count() == 1
    assert PaymentTransaction.objects.filter(booking=booking).count() == 1

    booking.refresh_from_db()
    assert booking.status == BookingStatus.CONFIRMED


@pytest.mark.django_db(transaction=True)
def test_concurrent_wallet_pay_same_key_debits_once():
    customer = UserFactory(role=UserRole.CUSTOMER)
    wallet = _funded_wallet(customer, 200_000)
    booking = _pending_booking(customer=customer, amount_online_toman=100_000)

    barrier = threading.Barrier(2)
    shared_key = f"race-same-{uuid.uuid4().hex}"

    def _call(_idx: int) -> int:
        try:
            barrier.wait(timeout=5)
            tx = pay_booking_with_wallet(
                user=customer,
                booking_id=booking.id,
                idempotency_key=shared_key,
            )
            return tx.id
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        tx_ids = list(pool.map(_call, [0, 1]))

    assert len(tx_ids) == 2
    assert tx_ids[0] == tx_ids[1]

    wallet.refresh_from_db()
    assert wallet.balance_toman == 100_000
    assert WalletTransaction.objects.filter(wallet=wallet, type=WalletTransactionType.DEBIT).count() == 1
    assert PaymentTransaction.objects.filter(booking=booking).count() == 1

    booking.refresh_from_db()
    assert booking.status == BookingStatus.CONFIRMED


def test_wallet_pay_rejects_client_sent_amount_field():
    customer = UserFactory(role=UserRole.CUSTOMER)
    wallet = _funded_wallet(customer, 200_000)
    booking = _pending_booking(customer=customer, amount_online_toman=85_000)

    client = Client()
    client.force_login(customer)
    resp = _post_wallet_pay(
        client,
        {
            "booking_id": booking.id,
            "idempotency_key": f"wpay-{uuid.uuid4().hex}",
            "amount_toman": 1,
        },
    )

    assert resp.status_code == 422
    wallet.refresh_from_db()
    assert wallet.balance_toman == 200_000
    assert PaymentTransaction.objects.filter(booking=booking).count() == 0


def test_wallet_pay_leaves_gateway_untouched():
    customer = UserFactory(role=UserRole.CUSTOMER)
    _funded_wallet(customer, 150_000)
    booking = _pending_booking(customer=customer, amount_online_toman=95_000)

    client = Client()
    client.force_login(customer)
    resp = _post_wallet_pay(
        client,
        {"booking_id": booking.id, "idempotency_key": f"wpay-{uuid.uuid4().hex}"},
    )
    assert resp.status_code == 200

    assert PaymentTransaction.objects.filter(booking=booking).exclude(provider_name="wallet").count() == 0
    tx = PaymentTransaction.objects.get(booking=booking, provider_name="wallet")
    assert tx.provider_reference is None
    assert tx.tracking_code == ""
    assert tx.card_pan_masked == ""


def test_wallet_pay_visibility_across_bookings_receipt_and_wallet_me(
    caplog: pytest.LogCaptureFixture,
):
    customer: Any = UserFactory(role=UserRole.CUSTOMER)
    _funded_wallet(customer, 300_000)
    booking = _pending_booking(
        customer=customer,
        amount_online_toman=110_000,
        amount_in_person_toman=45_000,
    )

    client = Client()
    client.force_login(customer)
    with caplog.at_level(logging.INFO, logger="apps.billing.services.payment"):
        pay_resp = _post_wallet_pay(
            client,
            {"booking_id": booking.id, "idempotency_key": f"wpay-{uuid.uuid4().hex}"},
        )
    assert pay_resp.status_code == 200
    tx_id = pay_resp.json()["id"]

    payment_logs = [
        rec.getMessage()
        for rec in caplog.records
        if rec.name == "apps.billing.services.payment" and rec.levelno == logging.INFO
    ]
    assert any(
        f"booking_id={booking.id}" in msg
        and f"tx_id={tx_id}" in msg
        and f"amount_toman={booking.amount_online_toman}" in msg
        for msg in payment_logs
    )
    assert all(customer.phone not in msg for msg in payment_logs)

    my_bookings_resp = client.get("/api/v1/bookings/my/")
    assert my_bookings_resp.status_code == 200
    my_bookings = my_bookings_resp.json()
    matched = [b for b in my_bookings if b["booking_id"] == booking.id]
    assert len(matched) == 1
    assert matched[0]["status"] == BookingStatus.CONFIRMED

    receipt_resp = client.get(f"/api/v1/bookings/{booking.id}/receipt/")
    assert receipt_resp.status_code == 200
    receipt = receipt_resp.json()
    assert receipt["total_online_toman"] == 110_000
    assert receipt["total_in_person_toman"] == 45_000

    wallet_resp = client.get("/api/v1/wallets/me/")
    assert wallet_resp.status_code == 200
    wallet_data = wallet_resp.json()
    assert wallet_data["balance_toman"] == 190_000
    debit_entries = [
        e
        for e in wallet_data["entries"]
        if e["direction"] == "debit"
        and e["reason"] == f"booking-pay:{booking.id}"
    ]
    assert len(debit_entries) == 1
    assert debit_entries[0]["amount_toman"] == 110_000
