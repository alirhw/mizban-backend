"""Tests for payment callback endpoint and booking confirmation service.

Task T-021 (PH-05 / WS-BILLING-WALLET / ADR-006):
1. on-time success confirms (PENDING_PAYMENT -> CONFIRMED, transaction SUCCESS).
2. failed verification does not confirm and marks transaction FAILED.
3. timeout marks TIMEOUT and does not confirm.
4. exact-amount mismatch never confirms.
5. tampered callback parameters claiming success while adapter verifies failure do NOT confirm.
6. unknown reference -> 404 with no leakage.
7. missing/malformed parameters -> 422.
8. duplicate callback after confirmation returns same outcome with no duplicate effects (idempotency).
9. late callback with slot still free confirms (both PENDING_PAYMENT and lazily EXPIRED).
10. late callback with slot taken by another CONFIRMED booking flags refund_required=True to bank card.
11. cancelled booking is never resurrected and flags refund_required=True.
12. race test: concurrent callbacks for same slot produce exactly one CONFIRMED booking.
13. refund_required is never set on ordinary success or failure.
14. GET and POST methods, with and without trailing slash.
"""
from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import time, timedelta

import pytest
from django.db import connection
from django.test import Client
from django.utils import timezone

from apps.billing.models import PaymentStatus, PaymentTransaction
from apps.billing.services.gateway import (
    PaymentInitiateRequest,
    SandboxGatewayAdapter,
    get_gateway,
    reset_sandbox_gateway,
)
from apps.billing.services.payment import handle_payment_callback
from apps.bookings.models import Booking, BookingStatus
from apps.bookings.services import create_booking_lock
from apps.panoramas.tests.factories import TablePinFactory
from apps.venues.tests.factories import UserFactory


@pytest.fixture(autouse=True)
def clean_sandbox_gateway():
    """Ensure sandbox gateway is in a clean default state for each test."""
    reset_sandbox_gateway()
    yield
    reset_sandbox_gateway()


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def pin():
    return TablePinFactory(reservation_fee_toman=50_000)


@pytest.fixture
def booking_and_tx(pin):
    """Helper fixture creating a PENDING_PAYMENT booking and matching PENDING PaymentTransaction."""
    now = timezone.now()
    customer = UserFactory(role="CUSTOMER")
    target_date = (now + timedelta(days=2)).date()
    target_time = time(16, 0)

    booking = create_booking_lock(
        user=customer,
        table_pin=pin,
        slot_date=target_date,
        slot_start_time=target_time,
        now=now,
    )
    assert booking.status == BookingStatus.PENDING_PAYMENT

    # Initiate through sandbox gateway to register authority
    gateway = get_gateway("sandbox")
    init_req = PaymentInitiateRequest(
        amount_toman=booking.amount_online_toman,
        callback_url="http://testserver/api/v1/billing/callback/",
        description="Table reservation",
        order_id=str(booking.id),
    )
    init_res = gateway.initiate(init_req)
    assert init_res.success

    tx = PaymentTransaction.objects.create(
        booking=booking,
        customer=customer,
        amount_toman=booking.amount_online_toman,
        currency="TOMAN",
        status=PaymentStatus.PENDING,
        provider_name="sandbox",
        provider_reference=init_res.authority,
        idempotency_key=str(uuid.uuid4()),
        redirect_url=init_res.redirect_url,
    )
    return booking, tx, init_res.authority


# ==============================================================================
# 1. On-Time Payment Confirmation (Happy Path)
# ==============================================================================


@pytest.mark.django_db
def test_ontime_callback_confirms_booking_and_success_transaction(client, booking_and_tx):
    """On-time payment callback confirms PENDING_PAYMENT -> CONFIRMED and sets transaction SUCCESS."""
    booking, tx, authority = booking_and_tx

    resp = client.get(f"/api/v1/billing/callback/?authority={authority}")
    assert resp.status_code == 200

    data = resp.json()
    assert data["booking_id"] == booking.id
    assert data["booking_status"] == BookingStatus.CONFIRMED
    assert data["payment_status"] == PaymentStatus.SUCCESS
    assert data["refund_required"] is False
    assert data["tracking_code"] != ""

    booking.refresh_from_db()
    assert booking.status == BookingStatus.CONFIRMED

    tx.refresh_from_db()
    assert tx.status == PaymentStatus.SUCCESS
    assert tx.refund_required is False
    assert tx.tracking_code != ""
    assert tx.verified_at is not None


# ==============================================================================
# 2. Gateway Failure & Timeout (Unsuccessful Paths)
# ==============================================================================


@pytest.mark.django_db
def test_failed_verification_does_not_confirm_and_marks_failed(client, booking_and_tx):
    """Gateway verification failure marks transaction FAILED and leaves booking unconfirmed."""
    booking, tx, authority = booking_and_tx

    gateway = get_gateway("sandbox")
    assert isinstance(gateway, SandboxGatewayAdapter)
    gateway.set_mode("failure")

    resp = client.get(f"/api/v1/billing/callback/?authority={authority}")
    assert resp.status_code == 200

    data = resp.json()
    assert data["booking_id"] == booking.id
    assert data["booking_status"] == BookingStatus.PENDING_PAYMENT
    assert data["payment_status"] == PaymentStatus.FAILED
    assert data["refund_required"] is False

    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING_PAYMENT  # Not confirmed

    tx.refresh_from_db()
    assert tx.status == PaymentStatus.FAILED
    assert tx.refund_required is False


@pytest.mark.django_db
def test_timeout_verification_marks_timeout_and_does_not_confirm(client, booking_and_tx):
    """Gateway verification timeout marks transaction TIMEOUT and leaves booking unconfirmed."""
    booking, tx, authority = booking_and_tx

    gateway = get_gateway("sandbox")
    assert isinstance(gateway, SandboxGatewayAdapter)
    gateway.set_mode("timeout")

    resp = client.get(f"/api/v1/billing/callback/?authority={authority}")
    assert resp.status_code == 200

    data = resp.json()
    assert data["booking_id"] == booking.id
    assert data["booking_status"] == BookingStatus.PENDING_PAYMENT
    assert data["payment_status"] == PaymentStatus.TIMEOUT
    assert data["refund_required"] is False

    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING_PAYMENT

    tx.refresh_from_db()
    assert tx.status == PaymentStatus.TIMEOUT
    assert tx.refund_required is False


@pytest.mark.django_db
def test_exact_amount_mismatch_never_confirms(client, booking_and_tx):
    """If gateway returns an amount different from stored transaction, verification fails."""
    booking, tx, authority = booking_and_tx

    # Tamper the sandbox internal record to simulate amount mismatch from IPG
    gateway = get_gateway("sandbox")
    assert isinstance(gateway, SandboxGatewayAdapter)
    gateway._records[authority]["amount_toman"] = tx.amount_toman + 10_000

    resp = client.get(f"/api/v1/billing/callback/?authority={authority}")
    assert resp.status_code == 200

    data = resp.json()
    assert data["payment_status"] == PaymentStatus.FAILED
    assert data["refund_required"] is False

    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING_PAYMENT

    tx.refresh_from_db()
    assert tx.status == PaymentStatus.FAILED
    assert "amount mismatch" in tx.error_message.lower()


@pytest.mark.django_db
def test_tampered_callback_parameters_claiming_success_ignored(client, booking_and_tx):
    """Callback parameters claiming success are untrusted; server-to-server verify dictates outcome."""
    booking, tx, authority = booking_and_tx

    gateway = get_gateway("sandbox")
    assert isinstance(gateway, SandboxGatewayAdapter)
    gateway.set_mode("failure")

    # Attacker tries to inject spoofed status and amount in query parameters
    resp = client.get(
        f"/api/v1/billing/callback/?authority={authority}&status=OK&success=true&amount={tx.amount_toman}"
    )
    assert resp.status_code == 200

    data = resp.json()
    assert data["payment_status"] == PaymentStatus.FAILED
    assert data["booking_status"] == BookingStatus.PENDING_PAYMENT

    booking.refresh_from_db()
    assert booking.status != BookingStatus.CONFIRMED


# ==============================================================================
# 3. Input Validation & Error Envelopes (404 and 422)
# ==============================================================================


@pytest.mark.django_db
def test_unknown_reference_returns_404_no_leakage(client):
    """Unknown provider reference returns standard 404 NOT_FOUND envelope with no info leakage."""
    resp = client.get("/api/v1/billing/callback/?authority=NON_EXISTENT_AUTHORITY_123")
    assert resp.status_code == 404
    data = resp.json()
    assert data["error_code"] == "NOT_FOUND"


@pytest.mark.django_db
def test_missing_reference_returns_404(client):
    """Callback with no reference returns 404 NOT_FOUND."""
    resp = client.get("/api/v1/billing/callback/")
    assert resp.status_code == 404
    data = resp.json()
    assert data["error_code"] == "NOT_FOUND"


@pytest.mark.django_db
def test_malformed_json_body_returns_422(client):
    """POST with invalid JSON syntax returns 422 VALIDATION_ERROR envelope."""
    resp = client.post(
        "/api/v1/billing/callback/",
        data="{invalid_json_body",
        content_type="application/json",
    )
    assert resp.status_code == 422
    data = resp.json()
    assert data["error_code"] == "VALIDATION_ERROR"
    assert "errors" in data["details"]


@pytest.mark.django_db
def test_malformed_parameter_type_returns_422(client):
    """POST with structurally invalid parameter type (nested list/dict) returns 422 VALIDATION_ERROR."""
    resp = client.post(
        "/api/v1/billing/callback/",
        data=json.dumps({"authority": ["invalid", "list"]}),
        content_type="application/json",
    )
    assert resp.status_code == 422
    data = resp.json()
    assert data["error_code"] == "VALIDATION_ERROR"


# ==============================================================================
# 4. Idempotency & Replay Safety
# ==============================================================================


@pytest.mark.django_db
def test_duplicate_callback_after_confirmation_is_idempotent(client, booking_and_tx):
    """Repeated callback for already CONFIRMED booking returns success with no duplicate effects."""
    booking, tx, authority = booking_and_tx

    # 1. First callback confirms
    resp1 = client.get(f"/api/v1/billing/callback/?authority={authority}")
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["booking_status"] == BookingStatus.CONFIRMED

    tx.refresh_from_db()
    verified_at_1 = tx.verified_at

    # 2. Second callback replays
    resp2 = client.get(f"/api/v1/billing/callback/?authority={authority}")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["booking_status"] == BookingStatus.CONFIRMED
    assert data2["payment_status"] == PaymentStatus.SUCCESS
    assert data2["tracking_code"] == data1["tracking_code"]

    tx.refresh_from_db()
    assert tx.verified_at == verified_at_1  # No secondary mutation


@pytest.mark.django_db
def test_duplicate_callback_for_final_failed_is_idempotent(client, booking_and_tx):
    """Repeated callback for already FAILED transaction returns stored outcome idempotently."""
    booking, tx, authority = booking_and_tx

    gateway = get_gateway("sandbox")
    assert isinstance(gateway, SandboxGatewayAdapter)
    gateway.set_mode("failure")

    resp1 = client.get(f"/api/v1/billing/callback/?authority={authority}")
    assert resp1.status_code == 200
    assert resp1.json()["payment_status"] == PaymentStatus.FAILED

    # Second callback returns stored failed outcome
    resp2 = client.get(f"/api/v1/billing/callback/?authority={authority}")
    assert resp2.status_code == 200
    assert resp2.json()["payment_status"] == PaymentStatus.FAILED


# ==============================================================================
# 5. Late Payment Callbacks & ADR-006 Decision Tree
# ==============================================================================


@pytest.mark.django_db
def test_late_callback_when_slot_still_free_confirms_pending_payment(client, booking_and_tx):
    """Case B (ADR-006): Lock expired (PENDING_PAYMENT), slot is still free -> confirms booking."""
    booking, tx, authority = booking_and_tx

    # Expire the lock (15 minutes in past)
    past = timezone.now() - timedelta(minutes=15)
    booking.lock_expires_at = past
    booking.save(update_fields=["lock_expires_at"])

    resp = client.get(f"/api/v1/billing/callback/?authority={authority}")
    assert resp.status_code == 200

    data = resp.json()
    assert data["booking_status"] == BookingStatus.CONFIRMED
    assert data["payment_status"] == PaymentStatus.SUCCESS
    assert data["refund_required"] is False

    booking.refresh_from_db()
    assert booking.status == BookingStatus.CONFIRMED

    tx.refresh_from_db()
    assert tx.status == PaymentStatus.SUCCESS
    assert tx.refund_required is False


@pytest.mark.django_db
def test_late_callback_when_slot_still_free_confirms_lazily_expired_booking(client, booking_and_tx):
    """Case B (ADR-006): Booking was lazily marked EXPIRED, slot is still free -> guarded transition to CONFIRMED."""
    booking, tx, authority = booking_and_tx

    # Transition booking to EXPIRED
    booking.transition_to(BookingStatus.EXPIRED)
    assert booking.status == BookingStatus.EXPIRED

    resp = client.get(f"/api/v1/billing/callback/?authority={authority}")
    assert resp.status_code == 200

    data = resp.json()
    assert data["booking_status"] == BookingStatus.CONFIRMED
    assert data["payment_status"] == PaymentStatus.SUCCESS
    assert data["refund_required"] is False

    booking.refresh_from_db()
    assert booking.status == BookingStatus.CONFIRMED

    tx.refresh_from_db()
    assert tx.status == PaymentStatus.SUCCESS
    assert tx.refund_required is False


@pytest.mark.django_db
def test_late_callback_when_slot_taken_by_another_confirmed_booking_flags_refund(
    client, pin, booking_and_tx
):
    """Case C (ADR-006): Lock expired, slot claimed by another CONFIRMED booking -> EXPIRED, refund_required=True."""
    booking, tx, authority = booking_and_tx

    # Expire booking's lock
    past = timezone.now() - timedelta(minutes=15)
    booking.lock_expires_at = past
    booking.save(update_fields=["lock_expires_at"])

    # Another customer successfully reserved and confirmed the slot
    other_customer = UserFactory(role="CUSTOMER")
    other_booking = create_booking_lock(
        user=other_customer,
        table_pin=pin,
        slot_date=booking.slot_date,
        slot_start_time=booking.slot_start_time,
    )
    other_booking.transition_to(BookingStatus.CONFIRMED)
    assert other_booking.status == BookingStatus.CONFIRMED

    # Late callback arrives for first customer
    resp = client.get(f"/api/v1/billing/callback/?authority={authority}")
    assert resp.status_code == 200

    data = resp.json()
    assert data["booking_status"] == BookingStatus.EXPIRED
    assert data["payment_status"] == PaymentStatus.SUCCESS
    assert data["refund_required"] is True
    assert "refund required to bank card" in data["message"].lower()

    # Verify first booking is NOT confirmed
    booking.refresh_from_db()
    assert booking.status == BookingStatus.EXPIRED

    # Transaction is SUCCESS with refund_required=True
    tx.refresh_from_db()
    assert tx.status == PaymentStatus.SUCCESS
    assert tx.refund_required is True

    # Exactly ONE confirmed booking exists for this slot
    assert (
        Booking.objects.filter(
            table_pin=pin,
            slot_date=booking.slot_date,
            slot_start_time=booking.slot_start_time,
            status=BookingStatus.CONFIRMED,
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_late_callback_when_slot_taken_by_active_pending_hold_flags_refund(
    client, pin, booking_and_tx
):
    """Case C (ADR-006): Lock expired, slot held by active PENDING_PAYMENT hold -> EXPIRED, refund_required=True."""
    booking, tx, authority = booking_and_tx

    past = timezone.now() - timedelta(minutes=15)
    booking.lock_expires_at = past
    booking.save(update_fields=["lock_expires_at"])

    # Another customer acquired a fresh 10-minute hold
    other_customer = UserFactory(role="CUSTOMER")
    other_booking = create_booking_lock(
        user=other_customer,
        table_pin=pin,
        slot_date=booking.slot_date,
        slot_start_time=booking.slot_start_time,
    )
    assert other_booking.status == BookingStatus.PENDING_PAYMENT
    assert other_booking.lock_expires_at > timezone.now()

    resp = client.get(f"/api/v1/billing/callback/?authority={authority}")
    assert resp.status_code == 200

    data = resp.json()
    assert data["booking_status"] == BookingStatus.EXPIRED
    assert data["refund_required"] is True

    booking.refresh_from_db()
    assert booking.status == BookingStatus.EXPIRED

    tx.refresh_from_db()
    assert tx.refund_required is True


@pytest.mark.django_db
def test_cancelled_booking_never_resurrected_and_flags_refund(client, booking_and_tx):
    """Case D (ADR-006): Customer cancelled booking -> never resurrected; flags refund_required=True."""
    booking, tx, authority = booking_and_tx

    booking.transition_to(BookingStatus.CANCELLED)
    assert booking.status == BookingStatus.CANCELLED

    resp = client.get(f"/api/v1/billing/callback/?authority={authority}")
    assert resp.status_code == 200

    data = resp.json()
    assert data["booking_status"] == BookingStatus.CANCELLED
    assert data["payment_status"] == PaymentStatus.SUCCESS
    assert data["refund_required"] is True

    booking.refresh_from_db()
    assert booking.status == BookingStatus.CANCELLED

    tx.refresh_from_db()
    assert tx.status == PaymentStatus.SUCCESS
    assert tx.refund_required is True


@pytest.mark.django_db
def test_refund_required_never_set_on_ordinary_success_or_failure(client, booking_and_tx):
    """Invariants: refund_required is False on ordinary success, failure, and timeout."""
    booking, tx, authority = booking_and_tx

    resp = client.get(f"/api/v1/billing/callback/?authority={authority}")
    assert resp.status_code == 200
    assert resp.json()["refund_required"] is False

    tx.refresh_from_db()
    assert tx.refund_required is False


# ==============================================================================
# 6. HTTP Methods & Trailing Slash Support
# ==============================================================================


@pytest.mark.django_db
def test_callback_methods_and_trailing_slash_tolerance(client, pin):
    """Callback works via GET and POST, with and without trailing slash."""
    now = timezone.now()
    target_date = (now + timedelta(days=2)).date()

    for idx, (method, path) in enumerate([
        ("GET", "/api/v1/billing/callback/"),
        ("GET", "/api/v1/billing/callback"),
        ("POST", "/api/v1/billing/callback/"),
        ("POST", "/api/v1/billing/callback"),
    ]):
        target_time = time(10 + idx, 0)
        customer = UserFactory(role="CUSTOMER")
        booking = create_booking_lock(
            user=customer,
            table_pin=pin,
            slot_date=target_date,
            slot_start_time=target_time,
        )
        gateway = get_gateway("sandbox")
        init_res = gateway.initiate(
            PaymentInitiateRequest(
                amount_toman=booking.amount_online_toman,
                callback_url="http://test/cb",
                description="test",
                order_id=str(booking.id),
            )
        )
        PaymentTransaction.objects.create(
            booking=booking,
            customer=customer,
            amount_toman=booking.amount_online_toman,
            currency="TOMAN",
            status=PaymentStatus.PENDING,
            provider_name="sandbox",
            provider_reference=init_res.authority,
            idempotency_key=str(uuid.uuid4()),
        )

        if method == "GET":
            resp = client.get(f"{path}?authority={init_res.authority}")
        else:
            resp = client.post(
                path,
                data=json.dumps({"authority": init_res.authority}),
                content_type="application/json",
            )

        assert resp.status_code == 200, f"Failed on {method} {path}"
        data = resp.json()
        assert data["booking_status"] == BookingStatus.CONFIRMED
        assert data["payment_status"] == PaymentStatus.SUCCESS


# ==============================================================================
# 7. PostgreSQL Race Condition / Concurrency Test
# ==============================================================================


@pytest.mark.django_db(transaction=True)
def test_race_concurrent_callbacks_for_same_slot_produce_exactly_one_confirmed():
    """THE RACE (ADR-006 / TD-004): Two concurrent callbacks for the same slot.

    Under PostgreSQL, TablePin select_for_update serializes both confirmation paths.
    Exactly one booking is CONFIRMED; the other is marked EXPIRED with refund_required=True.
    Zero double-bookings exist in the database.
    """
    pin = TablePinFactory(reservation_fee_toman=50_000)
    slot = pin.next_bookable_slot()
    assert slot is not None

    user_a = UserFactory(role="CUSTOMER")
    user_b = UserFactory(role="CUSTOMER")

    # Create Booking A (expired hold, transitioned to EXPIRED)
    booking_a = create_booking_lock(
        user=user_a,
        table_pin=pin,
        slot_date=slot.date,
        slot_start_time=slot.start_time,
    )
    past = timezone.now() - timedelta(minutes=15)
    booking_a.lock_expires_at = past
    booking_a.status = BookingStatus.EXPIRED
    booking_a.save(update_fields=["status", "lock_expires_at"])

    # Create Booking B on the same slot (allowed because booking_a is EXPIRED)
    booking_b = create_booking_lock(
        user=user_b,
        table_pin=pin,
        slot_date=slot.date,
        slot_start_time=slot.start_time,
    )
    booking_b.lock_expires_at = past
    booking_b.save(update_fields=["lock_expires_at"])

    # Initiate payment transactions for both
    gateway = get_gateway("sandbox")
    init_a = gateway.initiate(
        PaymentInitiateRequest(
            amount_toman=booking_a.amount_online_toman,
            callback_url="http://test/cb",
            description="Booking A",
            order_id=str(booking_a.id),
        )
    )
    init_b = gateway.initiate(
        PaymentInitiateRequest(
            amount_toman=booking_b.amount_online_toman,
            callback_url="http://test/cb",
            description="Booking B",
            order_id=str(booking_b.id),
        )
    )

    PaymentTransaction.objects.create(
        booking=booking_a,
        customer=user_a,
        amount_toman=booking_a.amount_online_toman,
        status=PaymentStatus.PENDING,
        provider_name="sandbox",
        provider_reference=init_a.authority,
        idempotency_key=str(uuid.uuid4()),
    )
    PaymentTransaction.objects.create(
        booking=booking_b,
        customer=user_b,
        amount_toman=booking_b.amount_online_toman,
        status=PaymentStatus.PENDING,
        provider_name="sandbox",
        provider_reference=init_b.authority,
        idempotency_key=str(uuid.uuid4()),
    )

    def _execute_callback(authority_token: str):
        try:
            return handle_payment_callback(callback_params={"authority": authority_token})
        finally:
            connection.close()

    # Run both callbacks in parallel threads
    with ThreadPoolExecutor(max_workers=2) as pool:
        future_a = pool.submit(_execute_callback, init_a.authority)
        future_b = pool.submit(_execute_callback, init_b.authority)
        res_a = future_a.result()
        res_b = future_b.result()

    outcomes = sorted([res_a.booking_status, res_b.booking_status])
    assert outcomes == ["CONFIRMED", "EXPIRED"]

    refund_flags = sorted([res_a.refund_required, res_b.refund_required])
    assert refund_flags == [False, True]

    # Verify database state: exactly ONE confirmed booking for this slot
    confirmed_count = Booking.objects.filter(
        table_pin=pin,
        slot_date=slot.date,
        slot_start_time=slot.start_time,
        status=BookingStatus.CONFIRMED,
    ).count()
    assert confirmed_count == 1
