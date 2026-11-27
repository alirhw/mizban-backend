"""Payment domain services.

Task T-020 (PH-05 / WS-BILLING-WALLET / ARCH-005):
- initiate_payment_for_booking:
  * Idempotency check: duplicate idempotency_key returns existing transaction immediately.
  * Online amount = booking.amount_online_toman ONLY (BR-003 platform share split).
  * PaymentTransaction row created and committed in INITIATED status before calling gateway.
  * STRICT RULE: No network call inside transaction.atomic().
  * Updates to PENDING with provider_reference and redirect_url on gateway success.
  * Transitions to TIMEOUT or FAILED on gateway errors.
- verify_payment_transaction:
  * Looks up transaction by provider_reference (authority).
  * Untrusted callback params: server-side verify only.
  * Exact amount matching against stored amount_toman (never client amount).
  * Idempotent replay: already SUCCESS returns existing row without re-verification.
  * Transitions to SUCCESS with tracking_code and card_pan_masked on success.
"""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import models, transaction
from django.http import Http404
from django.utils import timezone

from apps.billing.models import PaymentStatus, PaymentTransaction
from apps.billing.services.gateway import (
    PaymentInitiateRequest,
    PaymentVerifyRequest,
    get_gateway,
)
from apps.bookings.models import Booking, BookingStatus
from core.exceptions import (
    InvalidStatusTransitionError,
    PaymentAlreadyProcessedError,
    PaymentAmountMismatchError,
    PaymentGatewayError,
    PaymentGatewayTimeoutError,
    PaymentVerificationFailedError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PaymentCallbackResult:
    """Outcome of processing a payment gateway callback (Task T-021 / ADR-006)."""

    booking_id: int | None
    booking_status: str
    payment_status: str
    refund_required: bool
    tracking_code: str = ""
    message: str = ""



def initiate_payment_for_booking(
    *,
    user: Any,
    booking_id: int,
    idempotency_key: str,
    callback_url: str,
    gateway_name: str | None = None,
) -> tuple[PaymentTransaction, str]:
    """Initiate an online payment transaction for a booking.

    Guarantees:
    - Idempotent: repeated calls with the same idempotency_key return the existing transaction.
    - Zero network calls inside transaction.atomic().
    - Charges table reservation fee only (amount_online_toman per BR-003).

    Returns:
        (PaymentTransaction, redirect_url)
    """
    # 1. Idempotency fast-path: return existing transaction if already recorded
    existing_tx = PaymentTransaction.objects.filter(idempotency_key=idempotency_key).first()
    if existing_tx:
        logger.info(
            "Payment initiate idempotency hit for key %s (tx id=%s, status=%s)",
            idempotency_key,
            existing_tx.pk,
            existing_tx.status,
        )
        return existing_tx, existing_tx.redirect_url

    # 2. Lock and validate booking inside transaction.atomic()
    provider = (gateway_name or getattr(settings, "PAYMENT_GATEWAY_PROVIDER", "sandbox")).lower()
    with transaction.atomic():
        booking = (
            Booking.objects.select_for_update()
            .select_related("venue", "customer")
            .filter(pk=booking_id)
            .first()
        )
        if not booking:
            raise InvalidStatusTransitionError("Booking not found.")

        # Authorize: user must own booking or be staff
        if booking.customer_id != user.id and not getattr(user, "is_staff", False):
            raise PermissionDenied("You do not have permission to pay for this booking.")

        # Booking state check
        if booking.status not in {BookingStatus.INITIATED, BookingStatus.PENDING_PAYMENT}:
            raise InvalidStatusTransitionError(
                f"Booking is in state {booking.status} and cannot accept payment."
            )

        # Lock expiration check (TD-004)
        now = timezone.now()
        if booking.lock_expires_at and booking.lock_expires_at <= now:
            raise InvalidStatusTransitionError("Booking reservation lock has expired.")

        # Amount split check (BR-003 / ARCH-005): online payment is table fee only
        amount_toman = booking.amount_online_toman
        if amount_toman <= 0:
            raise ValueError("Booking online table fee must be greater than zero.")

        # Create row in INITIATED status before calling external gateway
        tx = PaymentTransaction.objects.create(
            booking=booking,
            customer=booking.customer,
            amount_toman=amount_toman,
            currency="TOMAN",
            status=PaymentStatus.INITIATED,
            provider_name=provider,
            idempotency_key=idempotency_key,
        )

    # 3. Transaction committed. OUTSIDE transaction.atomic(), invoke gateway
    gateway = get_gateway(provider)
    init_request = PaymentInitiateRequest(
        amount_toman=tx.amount_toman,
        callback_url=callback_url,
        description=f"Table reservation at {booking.venue.name} (Booking #{booking.id})",
        order_id=str(tx.id),
        customer_phone=getattr(booking.customer, "phone_number", ""),
        customer_email=getattr(booking.customer, "email", ""),
        metadata={"booking_id": booking.id, "transaction_id": tx.id},
    )

    try:
        result = gateway.initiate(init_request)
    except PaymentGatewayTimeoutError as exc:
        logger.warning("Gateway initiate timeout for tx %s: %s", tx.id, exc)
        tx.transition_to(PaymentStatus.TIMEOUT, error_message=str(exc))
        raise
    except Exception as exc:
        logger.exception("Gateway initiate unexpected error for tx %s: %s", tx.id, exc)
        tx.transition_to(PaymentStatus.FAILED, error_message=str(exc))
        raise PaymentGatewayError(f"Payment gateway initiation failed: {exc}") from exc

    if not result.success:
        logger.warning("Gateway rejected initiate for tx %s: %s", tx.id, result.error_message)
        tx.transition_to(PaymentStatus.FAILED, error_message=result.error_message)
        raise PaymentGatewayError(f"Payment gateway rejected initiation: {result.error_message}")

    # 4. Gateway accepted: update transaction with authority and redirect URL -> PENDING
    tx.transition_to(
        PaymentStatus.PENDING,
        provider_reference=result.authority,
        redirect_url=result.redirect_url,
    )
    logger.info(
        "Payment initiated: booking_id=%s tx_id=%s authority=%s",
        booking.id,
        tx.id,
        result.authority,
    )
    return tx, result.redirect_url


def verify_payment_transaction(
    *,
    provider_reference: str,
    callback_params: dict[str, Any] | None = None,
    gateway_name: str | None = None,
) -> PaymentTransaction:
    """Verify an online payment transaction server-to-server.

    Guarantees:
    - Never trusts client callback parameters alone.
    - Idempotent: repeated verify calls for an already SUCCESS transaction return safely.
    - Asserts exact amount match against stored transaction row (BR-003).

    Returns:
        PaymentTransaction in terminal state (SUCCESS).
    """
    tx = (
        PaymentTransaction.objects.select_related("booking", "customer")
        .filter(provider_reference=provider_reference)
        .first()
    )
    if not tx:
        raise PaymentVerificationFailedError("No payment transaction found for the specified provider reference.")

    # Idempotent replay: already verified transaction is returned immediately
    if tx.status == PaymentStatus.SUCCESS:
        logger.info("Payment verify idempotency hit for reference %s (tx id=%s)", provider_reference, tx.id)
        return tx

    # Terminal failure cannot be re-verified
    if tx.status == PaymentStatus.FAILED:
        raise PaymentAlreadyProcessedError("Payment transaction has already failed and cannot be verified.")

    # Must be in PENDING or TIMEOUT (in case a prior verify timed out)
    if tx.status not in {PaymentStatus.PENDING, PaymentStatus.TIMEOUT}:
        raise InvalidStatusTransitionError(
            f"Cannot verify transaction in status {tx.status}."
        )

    provider = gateway_name or tx.provider_name
    gateway = get_gateway(provider)

    verify_request = PaymentVerifyRequest(
        authority=provider_reference,
        amount_toman=tx.amount_toman,  # Strictly from DB row
        callback_params=callback_params or {},
    )

    try:
        result = gateway.verify(verify_request)
    except PaymentGatewayTimeoutError as exc:
        logger.warning("Gateway verify timeout for tx %s: %s", tx.id, exc)
        tx.transition_to(PaymentStatus.TIMEOUT, error_message=str(exc))
        raise
    except Exception as exc:
        logger.exception("Gateway verify unexpected error for tx %s: %s", tx.id, exc)
        tx.transition_to(PaymentStatus.FAILED, error_message=str(exc))
        raise PaymentVerificationFailedError(f"Payment verification failed: {exc}") from exc

    if not result.success:
        logger.warning("Gateway verify rejected for tx %s: %s", tx.id, result.error_message)
        tx.transition_to(PaymentStatus.FAILED, error_message=result.error_message)
        raise PaymentVerificationFailedError(f"Payment verification rejected: {result.error_message}")

    # Amount mismatch safety defense (BR-003)
    if result.amount_toman != tx.amount_toman:
        msg = f"Amount mismatch: gateway verified {result.amount_toman} Toman, expected {tx.amount_toman} Toman"
        logger.error("Payment verify amount mismatch for tx %s: %s", tx.id, msg)
        tx.transition_to(PaymentStatus.FAILED, error_message=msg)
        raise PaymentAmountMismatchError(msg)

    # Verification successful: record tracking details and set SUCCESS
    tx.transition_to(
        PaymentStatus.SUCCESS,
        tracking_code=result.tracking_code,
        card_pan_masked=result.card_pan_masked,
        verified_at=timezone.now(),
    )
    return tx


def handle_payment_callback(
    *,
    callback_params: dict[str, Any],
    gateway_name: str | None = None,
) -> PaymentCallbackResult:
    """Process incoming payment gateway callback and confirm booking (Task T-021 / ADR-006).

    Guarantees:
    - Step 1: Outside any atomic block, verifies payment transaction server-to-server.
    - Step 2: Inside transaction.atomic(), row-locks TablePin and Booking under select_for_update.
    - Re-checks occupancy excluding this booking:
        (a) On-time success -> CONFIRMED, refund_required=False.
        (b) Late callback with slot free -> CONFIRMED, refund_required=False (ADR-006).
        (c) Late callback with slot taken -> EXPIRED, refund_required=True to bank card (ADR-006).
        (d) Cancelled booking -> CANCELLED, refund_required=True (never resurrect).
    - Idempotent replay: already confirmed/processed transaction returns stored outcome without duplicate side effects.
    - Zero network calls inside transaction.atomic().
    - Never logs callback payloads, card numbers, or secrets (AGENTS.md).
    """
    provider = (gateway_name or getattr(settings, "PAYMENT_GATEWAY_PROVIDER", "sandbox")).lower()
    gateway = get_gateway(provider)

    reference = gateway.extract_reference(callback_params)
    if not reference:
        logger.warning("Payment callback received without provider reference.")
        raise Http404("Missing or invalid payment reference.")

    tx = (
        PaymentTransaction.objects.select_related("booking", "customer")
        .filter(provider_reference=reference)
        .first()
    )
    if not tx:
        logger.warning("Payment callback for unknown reference (no transaction found).")
        raise Http404("Payment transaction not found.")

    # Idempotency fast-path: if already terminal and confirmed or flagged
    if tx.status == PaymentStatus.SUCCESS:
        if tx.booking.status == BookingStatus.CONFIRMED:
            return PaymentCallbackResult(
                booking_id=tx.booking.id,
                booking_status=BookingStatus.CONFIRMED,
                payment_status=PaymentStatus.SUCCESS,
                refund_required=False,
                tracking_code=tx.tracking_code,
                message="Payment already verified and booking confirmed.",
            )
        if tx.refund_required:
            return PaymentCallbackResult(
                booking_id=tx.booking.id,
                booking_status=tx.booking.status,
                payment_status=PaymentStatus.SUCCESS,
                refund_required=True,
                tracking_code=tx.tracking_code,
                message="Payment verified but slot was occupied; refund required to bank card.",
            )

    if tx.status in (PaymentStatus.FAILED, PaymentStatus.TIMEOUT):
        return PaymentCallbackResult(
            booking_id=tx.booking.id,
            booking_status=tx.booking.status,
            payment_status=tx.status,
            refund_required=False,
            tracking_code="",
            message=tx.error_message or "Payment was not successful.",
        )

    # Step 1: OUTSIDE any transaction, call verify_payment_transaction if not already SUCCESS
    if tx.status != PaymentStatus.SUCCESS:
        try:
            tx = verify_payment_transaction(
                provider_reference=reference,
                callback_params=callback_params,
                gateway_name=tx.provider_name,
            )
        except PaymentGatewayTimeoutError as exc:
            logger.warning("Gateway verify timeout during callback for tx %s: %s", tx.id, exc)
            return PaymentCallbackResult(
                booking_id=tx.booking.id,
                booking_status=tx.booking.status,
                payment_status=PaymentStatus.TIMEOUT,
                refund_required=False,
                tracking_code="",
                message="Payment gateway verification timed out.",
            )
        except PaymentAlreadyProcessedError:
            tx.refresh_from_db()
            return PaymentCallbackResult(
                booking_id=tx.booking.id,
                booking_status=tx.booking.status,
                payment_status=tx.status,
                refund_required=tx.refund_required,
                tracking_code=tx.tracking_code,
                message=tx.error_message or "Payment transaction already processed.",
            )
        except (PaymentVerificationFailedError, PaymentAmountMismatchError, PaymentGatewayError) as exc:
            logger.warning("Gateway verify failed during callback for tx %s: %s", tx.id, exc)
            tx.refresh_from_db()
            return PaymentCallbackResult(
                booking_id=tx.booking.id,
                booking_status=tx.booking.status,
                payment_status=PaymentStatus.FAILED,
                refund_required=False,
                tracking_code="",
                message=str(exc) or "Payment verification failed.",
            )

    # If verification did not produce SUCCESS, do not proceed to confirmation
    if tx.status != PaymentStatus.SUCCESS:
        return PaymentCallbackResult(
            booking_id=tx.booking.id,
            booking_status=tx.booking.status,
            payment_status=tx.status,
            refund_required=False,
            tracking_code="",
            message=tx.error_message or "Payment verification was not successful.",
        )

    # Step 2: Atomic confirmation under TablePin and Booking row locks (ADR-006)
    from apps.panoramas.models import TablePin

    with transaction.atomic():
        # Lock TablePin row first (matching create_booking_lock lock ordering discipline)
        pin = TablePin.objects.select_for_update().get(pk=tx.booking.table_pin_id)
        booking = (
            Booking.objects.select_for_update()
            .select_related("table_pin")
            .get(pk=tx.booking_id)
        )
        tx_locked = PaymentTransaction.objects.select_for_update().get(pk=tx.pk)

        # Concurrency safety: check if another thread confirmed or updated while we waited for lock
        if booking.status == BookingStatus.CONFIRMED:
            return PaymentCallbackResult(
                booking_id=booking.id,
                booking_status=BookingStatus.CONFIRMED,
                payment_status=PaymentStatus.SUCCESS,
                refund_required=False,
                tracking_code=tx_locked.tracking_code,
                message="Payment verified and booking confirmed successfully.",
            )
        if tx_locked.refund_required:
            return PaymentCallbackResult(
                booking_id=booking.id,
                booking_status=booking.status,
                payment_status=PaymentStatus.SUCCESS,
                refund_required=True,
                tracking_code=tx_locked.tracking_code,
                message="Slot is no longer available; refund required to bank card.",
            )

        # Case (d): Cancelled booking is NEVER resurrected (ADR-006)
        if booking.status == BookingStatus.CANCELLED:
            if not tx_locked.refund_required:
                tx_locked.refund_required = True
                tx_locked.save(update_fields=["refund_required", "updated_at"])
            return PaymentCallbackResult(
                booking_id=booking.id,
                booking_status=BookingStatus.CANCELLED,
                payment_status=PaymentStatus.SUCCESS,
                refund_required=True,
                tracking_code=tx_locked.tracking_code,
                message="Booking was cancelled by customer; refund required to bank card.",
            )

        now = timezone.now()

        # Check occupancy for table_pin and slot, excluding this booking
        is_slot_taken = Booking.objects.filter(
            table_pin_id=pin.id,
            slot_date=booking.slot_date,
            slot_start_time=booking.slot_start_time,
        ).exclude(pk=booking.pk).filter(
            models.Q(status=BookingStatus.CONFIRMED)
            | models.Q(status=BookingStatus.PENDING_PAYMENT, lock_expires_at__gt=now)
        ).exists()

        if is_slot_taken:
            # Case (c): Slot taken by another booking -> mark EXPIRED, refund_required = True
            if booking.status != BookingStatus.EXPIRED:
                if booking.status == BookingStatus.PENDING_PAYMENT:
                    booking.transition_to(BookingStatus.EXPIRED)
                else:
                    booking.status = BookingStatus.EXPIRED
                    booking.save(update_fields=["status", "updated_at"])
            tx_locked.refund_required = True
            tx_locked.save(update_fields=["refund_required", "updated_at"])
            logger.warning(
                "Late payment conflict: slot occupied for pin=%s slot=%s %s; tx=%s marked refund_required.",
                pin.id,
                booking.slot_date,
                booking.slot_start_time,
                tx_locked.id,
            )
            return PaymentCallbackResult(
                booking_id=booking.id,
                booking_status=BookingStatus.EXPIRED,
                payment_status=PaymentStatus.SUCCESS,
                refund_required=True,
                tracking_code=tx_locked.tracking_code,
                message="Slot is no longer available; refund required to bank card.",
            )

        # Slot is free! Lazily expire any other stale pending holds on this slot (REQ-LOCK-005)
        Booking.objects.filter(
            table_pin_id=pin.id,
            slot_date=booking.slot_date,
            slot_start_time=booking.slot_start_time,
            status=BookingStatus.PENDING_PAYMENT,
            lock_expires_at__lte=now,
        ).exclude(pk=booking.pk).update(status=BookingStatus.EXPIRED, updated_at=now)

        # Confirm booking (Case a: on-time; Case b: late callback with free slot)
        if booking.status == BookingStatus.INITIATED:
            booking.transition_to(BookingStatus.PENDING_PAYMENT)
        booking.transition_to(BookingStatus.CONFIRMED)
        logger.info(
            "Payment callback confirmed booking_id=%s tx_id=%s authority=%s",
            booking.id,
            tx_locked.id,
            tx_locked.provider_reference,
        )
        return PaymentCallbackResult(
            booking_id=booking.id,
            booking_status=BookingStatus.CONFIRMED,
            payment_status=PaymentStatus.SUCCESS,
            refund_required=False,
            tracking_code=tx_locked.tracking_code,
            message="Payment verified and booking confirmed successfully.",
        )

