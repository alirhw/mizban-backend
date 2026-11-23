"""Django Ninja router for the accounts app (Task T-006 / TD-006).

Mounted centrally in config/api.py under /api/v1/auth.
Views stay thin (Architecture Spec section 14 & ARCH-001):
- validate via schemas.py
- delegate to services.py
- return typed schemas (session issuance deferred to Task T-007)
"""
from __future__ import annotations

from ninja import Router

from apps.accounts import services
from apps.accounts.schemas import OtpRequestIn, OtpRequestOut, OtpVerifyIn, OtpVerifyOut

router = Router(tags=["accounts"])


def _get_client_ip(request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        first_hop = forwarded_for.split(",")[0].strip()
        if first_hop:
            return first_hop
    return (request.META.get("REMOTE_ADDR") or "unknown").strip() or "unknown"


@router.post(
    "/otp/request/",
    response={200: OtpRequestOut},
    auth=None,
    summary="Request a 5-digit OTP code via SMS (TD-006)",
)
@router.post(
    "/otp/request",
    response={200: OtpRequestOut},
    auth=None,
    summary="Request an OTP code (trailing-slash alias)",
    include_in_schema=False,
)
def request_otp_endpoint(request, payload: OtpRequestIn):
    """Issue a 5-digit OTP code with Redis rate limiting (3/10m per phone and per IP)."""
    expires_in = services.request_otp(payload.phone, ip=_get_client_ip(request))
    return OtpRequestOut(sent=True, expires_in_seconds=expires_in)


@router.post(
    "/otp/verify/",
    response={200: OtpVerifyOut},
    auth=None,
    summary="Verify an OTP code and resolve user identity (TD-006)",
)
@router.post(
    "/otp/verify",
    response={200: OtpVerifyOut},
    auth=None,
    summary="Verify an OTP code (trailing-slash alias)",
    include_in_schema=False,
)
def verify_otp_endpoint(request, payload: OtpVerifyIn):
    """Verify the OTP code and resolve (get_or_create) the User.

    Session cookie issuance is deferred to Task T-007.
    """
    return services.verify_otp(payload.phone, payload.code)
