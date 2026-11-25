"""Django Ninja router for the billing app (Payment gateway, payment transactions, split receipts).

Mounted centrally in config/api.py under /api/v1/billing. Endpoints land here task by task;
views stay thin (Architecture Spec section 14 & ARCH-001): authenticate, validate
via schemas.py, delegate to services.py, map domain errors.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponseRedirect
from ninja import Router
from ninja.errors import ValidationError
from ninja.responses import Status

from apps.accounts.auth import auth
from apps.accounts.models import UserRole
from apps.billing.schemas import (
    PaymentCallbackOut,
    PaymentInitiateIn,
    PaymentInitiateOut,
)
from apps.billing.services.payment import (
    handle_payment_callback,
    initiate_payment_for_booking,
)
from apps.bookings.models import Booking

logger = logging.getLogger(__name__)

router = Router(tags=["billing"])


def _extract_callback_params(request: HttpRequest) -> dict[str, Any]:
    """Safely extract untrusted callback parameters from GET query or POST body.

    Handles form-encoded and application/json bodies.
    Raises ValidationError (HTTP 422) if the payload is malformed or invalid JSON.
    Never logs raw payload contents or sensitive card/phone data.
    """
    params: dict[str, Any] = {}
    if request.GET:
        params.update(request.GET.dict())

    if request.method == "POST":
        content_type = (
            request.content_type.split(";")[0].strip().lower()
            if request.content_type
            else ""
        )
        if content_type == "application/json":
            if request.body:
                try:
                    body = json.loads(request.body.decode("utf-8"))
                    if not isinstance(body, dict):
                        raise ValidationError(
                            [{"loc": ["body"], "msg": "Request body must be a JSON object.", "type": "type_error"}]
                        )
                    params.update(body)
                except json.JSONDecodeError as exc:
                    raise ValidationError(
                        [{"loc": ["body"], "msg": f"Malformed JSON payload: {exc}", "type": "value_error.jsondecode"}]
                    ) from exc
        else:
            if request.POST:
                params.update(request.POST.dict())

    # Structure validation: if a reference key is provided, ensure it is a scalar (str/int)
    for ref_key in ("provider_reference", "reference", "authority"):
        if ref_key in params:
            val = params[ref_key]
            if isinstance(val, (dict, list)):
                raise ValidationError(
                    [{"loc": [ref_key], "msg": f"Field '{ref_key}' must be a scalar string or number.", "type": "type_error"}]
                )

    return params


def _append_callback_query(callback_url: str, result: Any) -> str:
    """Append standardized outcome parameters to a dev browser callback_url."""
    parsed = urlparse(callback_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(
        {
            "booking_id": "" if result.booking_id is None else str(result.booking_id),
            "booking_status": result.booking_status,
            "payment_status": result.payment_status,
            "refund_required": "true" if result.refund_required else "false",
            "tracking_code": result.tracking_code,
        }
    )
    return urlunparse(parsed._replace(query=urlencode(query)))


@router.post(
    "/initiate/",
    response={201: PaymentInitiateOut},
    auth=auth,
    summary="Initiate online payment for a pending booking",
)
@router.post(
    "/initiate",
    response={201: PaymentInitiateOut},
    auth=auth,
    summary="Initiate online payment (no trailing slash)",
    include_in_schema=False,
)
def initiate_payment(request: HttpRequest, payload: PaymentInitiateIn):
    """Expose initiate_payment_for_booking over HTTP (Task T-028-PRE).

    - Session cookie + CSRF (ActiveSessionAuth), CUSTOMER role only.
    - Derives amount_toman strictly server-side from booking.amount_online_toman.
    """
    if getattr(request.auth, "role", None) != UserRole.CUSTOMER:
        raise PermissionDenied("Only customers can initiate booking payments.")

    if not Booking.objects.filter(pk=payload.booking_id).exists():
        raise Http404("Booking not found.")

    tx, redirect_url = initiate_payment_for_booking(
        user=request.auth,
        booking_id=payload.booking_id,
        idempotency_key=payload.idempotency_key,
        callback_url=payload.callback_url,
    )
    return Status(
        201,
        PaymentInitiateOut(
            transaction_id=tx.id,
            booking_id=tx.booking_id,
            amount_toman=tx.amount_toman,
            currency=tx.currency,
            status=tx.status,
            provider_name=tx.provider_name,
            provider_reference=tx.provider_reference,
            redirect_url=redirect_url,
        ),
    )


@router.api_operation(
    ["GET", "POST"],
    "/callback/",
    response={200: PaymentCallbackOut},
    auth=None,
    summary="Process payment gateway callback",
)
@router.api_operation(
    ["GET", "POST"],
    "/callback",
    response={200: PaymentCallbackOut},
    auth=None,
    summary="Process payment gateway callback (no trailing slash)",
    include_in_schema=False,
)
def payment_callback(request: HttpRequest):
    """Process incoming payment gateway callback (Task T-021 / ADR-006).

    Public endpoint (auth=None): Gateway callbacks originate from customer browsers
    or gateway servers without an authorization header.
    Extracts reference via adapter, verifies server-to-server, and atomically confirms
    or flags for refund.
    """
    params = _extract_callback_params(request)
    result = handle_payment_callback(callback_params=params)

    callback_url = params.get("callback_url")
    accept = request.META.get("HTTP_ACCEPT", "")
    if (
        getattr(settings, "DEBUG", False)
        and request.method == "GET"
        and isinstance(callback_url, str)
        and callback_url
        and "text/html" in accept
    ):
        return HttpResponseRedirect(_append_callback_query(callback_url, result))

    return result
