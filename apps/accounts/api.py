"""Django Ninja router for the accounts app (Tasks T-006 & T-007 / TD-006).

Mounted centrally in config/api.py under /api/v1/auth.
Views stay thin (Architecture Spec section 14 & ARCH-001):
- authenticate via ActiveSessionAuth (Django session cookie + CSRF)
- validate via schemas.py
- delegate to services.py
- return typed schemas
"""
from __future__ import annotations

from django.middleware.csrf import get_token
from ninja import Router

from apps.accounts import services
from apps.accounts.auth import auth
from apps.accounts.schemas import (
    CsrfOut,
    LogoutOut,
    OtpRequestIn,
    OtpRequestOut,
    OtpVerifyIn,
    OtpVerifyOut,
)

router = Router(tags=["accounts"])


def _get_client_ip(request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        first_hop = forwarded_for.split(",")[0].strip()
        if first_hop:
            return first_hop
    return (request.META.get("REMOTE_ADDR") or "unknown").strip() or "unknown"


@router.get(
    "/csrf/",
    response={200: CsrfOut},
    auth=None,
    summary="Issue CSRF cookie and token for session clients (TD-006)",
)
@router.get(
    "/csrf",
    response={200: CsrfOut},
    auth=None,
    summary="Issue CSRF cookie and token (trailing-slash alias)",
    include_in_schema=False,
)
def get_csrf_endpoint(request):
    """Ensure the csrftoken cookie is set via CsrfViewMiddleware and return the token."""
    return CsrfOut(csrf_token=get_token(request))


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
    summary="Verify an OTP code and establish a Django session (TD-006)",
)
@router.post(
    "/otp/verify",
    response={200: OtpVerifyOut},
    auth=None,
    summary="Verify an OTP code (trailing-slash alias)",
    include_in_schema=False,
)
def verify_otp_endpoint(request, payload: OtpVerifyIn):
    """Verify the OTP code, resolve the User, and issue an HttpOnly session cookie."""
    user = services.verify_otp(payload.phone, payload.code)
    services.login_session(request, user)
    return user


@router.post(
    "/logout/",
    response={200: LogoutOut},
    auth=auth,
    summary="Flush the active session and log out (TD-006)",
)
@router.post(
    "/logout",
    response={200: LogoutOut},
    auth=auth,
    summary="Log out (trailing-slash alias)",
    include_in_schema=False,
)
def logout_endpoint(request):
    """Flush the authenticated user's Django session and expire the cookie."""
    services.logout_session(request)
    return LogoutOut(logged_out=True)


@router.get(
    "/me/",
    response={200: OtpVerifyOut},
    auth=auth,
    summary="Return the currently authenticated user's profile (TD-006)",
)
@router.get(
    "/me",
    response={200: OtpVerifyOut},
    auth=auth,
    summary="Return the currently authenticated user (trailing-slash alias)",
    include_in_schema=False,
)
def me_endpoint(request):
    """Return {id, phone, role} for the currently authenticated session user."""
    return request.auth
