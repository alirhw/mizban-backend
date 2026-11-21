"""Django Ninja router for the billing app (Payment gateway, payment transactions, split receipts).

Mounted centrally in config/api.py under /api/v1/billing. Endpoints land here task by task;
views stay thin (Architecture Spec section 14 & ARCH-001): authenticate, validate
via schemas.py, delegate to services.py, map domain errors.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from django.http import HttpRequest
from ninja import Router
from ninja.errors import ValidationError

from apps.billing.schemas import PaymentCallbackOut
from apps.billing.services.payment import handle_payment_callback

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
    return result
