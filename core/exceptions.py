"""Domain exceptions and the standard API error envelope.

Architecture Spec section 19: expected domain errors are raised anywhere
in the service layer as DomainError subclasses and converted by ONE
central handler into the standard body:

    {"error_code": "SLOT_ALREADY_RESERVED", "message": "...", "details": {}}

Unexpected exceptions become a safe generic 500; the detail goes to the
server log / Sentry only, never to the client.
"""
from __future__ import annotations

import logging

from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from django.db.models import ProtectedError
from django.http import Http404
from ninja.errors import HttpError, ValidationError

logger = logging.getLogger(__name__)


class DomainError(Exception):
    """Base class for expected, user-visible business errors."""

    error_code = "DOMAIN_ERROR"
    status_code = 400
    default_message = "The request could not be completed."

    def __init__(self, message: str | None = None, *, details: dict | None = None):
        self.message = message or self.default_message
        self.details = details or {}
        super().__init__(self.message)


class SlotAlreadyReservedError(DomainError):
    """TD-004: the table already has an active lock or a confirmed booking."""

    error_code = "SLOT_ALREADY_RESERVED"
    status_code = 409
    default_message = "This table is currently being reserved by another user for the selected time."


class LeadTimeViolationError(DomainError):
    """BR-002: slots must start at least 24 hours from now."""

    error_code = "LEAD_TIME_VIOLATION"
    status_code = 400
    default_message = "Bookings must be made at least 24 hours before the slot start time."


class CancellationWindowClosedError(DomainError):
    """BR-004: cancellation is only allowed 36+ hours before the slot."""

    error_code = "CANCELLATION_WINDOW_CLOSED"
    status_code = 400
    default_message = "Reservations can only be cancelled at least 36 hours before the slot start time."


class InsufficientWalletBalanceError(DomainError):
    """TD-005: the wallet may never go negative."""

    error_code = "WALLET_INSUFFICIENT_BALANCE"
    status_code = 400
    default_message = "The wallet balance is not enough for this operation."


class InvalidStatusTransitionError(DomainError):
    """Booking state machine: illegal transition between states."""

    error_code = "INVALID_STATUS_TRANSITION"
    status_code = 400
    default_message = "The requested status transition is not permitted."


class VenueNotBookableError(DomainError):
    """BR-005: A venue is publicly visible/bookable only when admin-approved and active."""

    error_code = "VENUE_NOT_BOOKABLE"
    status_code = 400
    default_message = "This venue is not currently available for reservations."


class TableNotBookableError(DomainError):
    """Table is inactive or not available."""

    error_code = "TABLE_NOT_BOOKABLE"
    status_code = 400
    default_message = "The selected table is currently not available for reservations."


class VenueMismatchError(DomainError):
    """Table pin does not belong to the requested venue."""

    error_code = "VENUE_MISMATCH"
    status_code = 400
    default_message = "The specified table does not belong to this venue."


class InvalidSlotError(DomainError):
    """Slot is not within the venue operating hours."""

    error_code = "INVALID_SLOT"
    status_code = 400
    default_message = "The selected slot is outside the venue's operating hours."


class FileTooLargeError(DomainError):
    """File size exceeds the maximum allowed limit."""

    error_code = "FILE_TOO_LARGE"
    status_code = 400
    default_message = "File size exceeds the maximum allowed limit of 20MB."


class InvalidImageError(DomainError):
    """Uploaded file is not a valid or supported image."""

    error_code = "INVALID_IMAGE"
    status_code = 400
    default_message = "The uploaded file is not a valid or supported image."


class ImageDecompressionBombError(DomainError):
    """Uploaded image exceeds decompression bomb safety limits."""

    error_code = "IMAGE_DECOMPRESSION_BOMB"
    status_code = 400
    default_message = "The uploaded image exceeds maximum pixel limits."


class TablePinProtectedError(DomainError):
    """Table pin has existing bookings and cannot be deleted (ADR-005)."""

    error_code = "TABLE_PIN_PROTECTED"
    status_code = 409
    default_message = "Cannot delete table pin with existing booking history. Deactivate it instead."


class TableNumberAlreadyExistsError(DomainError):
    """Table number already exists within the venue."""

    error_code = "TABLE_NUMBER_ALREADY_EXISTS"
    status_code = 409
    default_message = "A table with this number already exists in this venue."


class PaymentGatewayError(DomainError):
    """Payment gateway rejected operation or experienced communication failure (ARCH-005)."""

    error_code = "PAYMENT_GATEWAY_ERROR"
    status_code = 502
    default_message = "Payment gateway communication failed."


class PaymentGatewayTimeoutError(PaymentGatewayError):
    """Payment gateway timed out during initiate or verify (ARCH-005)."""

    error_code = "PAYMENT_GATEWAY_TIMEOUT"
    status_code = 504
    default_message = "Payment gateway request timed out."


class PaymentVerificationFailedError(DomainError):
    """Payment verification was rejected or declined by the gateway (ARCH-005)."""

    error_code = "PAYMENT_VERIFICATION_FAILED"
    status_code = 400
    default_message = "Payment verification was rejected by the gateway."


class PaymentAmountMismatchError(DomainError):
    """Verified payment amount does not match stored booking amount (BR-003)."""

    error_code = "PAYMENT_AMOUNT_MISMATCH"
    status_code = 400
    default_message = "Verified amount does not match booking reservation amount."


class PaymentAlreadyProcessedError(DomainError):
    """Payment transaction is already in a terminal state (ARCH-005)."""

    error_code = "PAYMENT_ALREADY_PROCESSED"
    status_code = 409
    default_message = "Payment transaction has already been processed."



def error_body(error_code: str, message: str, details: dict | None = None) -> dict:
    return {"error_code": error_code, "message": message, "details": details or {}}


def register_exception_handlers(api) -> None:
    """Attach the section-19 error contract to a NinjaAPI instance."""

    @api.exception_handler(DomainError)
    def _domain_error(request, exc: DomainError):
        return api.create_response(
            request,
            error_body(exc.error_code, exc.message, exc.details),
            status=exc.status_code,
        )

    @api.exception_handler(ValidationError)
    def _validation_error(request, exc: ValidationError):
        return api.create_response(
            request,
            error_body(
                "VALIDATION_ERROR",
                "The request payload failed validation.",
                {"errors": exc.errors},
            ),
            status=422,
        )

    @api.exception_handler(DjangoValidationError)
    def _django_validation_error(request, exc: DjangoValidationError):
        details = exc.message_dict if hasattr(exc, "message_dict") else {"non_field_errors": exc.messages}
        return api.create_response(
            request,
            error_body(
                "VALIDATION_ERROR",
                "The request payload failed validation.",
                {"errors": details},
            ),
            status=422,
        )

    @api.exception_handler(Http404)
    def _not_found(request, exc: Http404):
        return api.create_response(
            request,
            error_body("NOT_FOUND", "The requested resource was not found."),
            status=404,
        )

    @api.exception_handler(PermissionDenied)
    def _forbidden(request, exc: PermissionDenied):
        return api.create_response(
            request,
            error_body("FORBIDDEN", "You do not have permission to perform this action."),
            status=403,
        )

    @api.exception_handler(ProtectedError)
    def _protected_error(request, exc: ProtectedError):
        return api.create_response(
            request,
            error_body(
                "TABLE_PIN_PROTECTED",
                "Cannot delete table pin with existing booking history. Deactivate it instead.",
            ),
            status=409,
        )

    @api.exception_handler(Exception)
    def _unexpected(request, exc: Exception):
        # Ninja's own HTTP errors (401/404 raised by the framework) keep
        # their status; everything else is a safe, generic 500.
        if isinstance(exc, HttpError):
            return api.create_response(
                request,
                error_body("HTTP_ERROR", exc.message),
                status=exc.status_code,
            )
        logger.exception("Unhandled API error: %s", exc)
        return api.create_response(
            request,
            error_body("INTERNAL_ERROR", "An unexpected error occurred."),
            status=500,
        )
