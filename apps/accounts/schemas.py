"""Pydantic in/out schemas for the accounts app (Task T-006 / TD-006).

Naming (Architecture Spec section 28): PascalCase with an explicit In/Out suffix.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from ninja import Field, Schema
from pydantic import ConfigDict, field_validator

from apps.accounts.services import validate_iranian_phone


class OtpRequestIn(Schema):
    """Request payload for requesting an OTP verification code."""

    model_config = ConfigDict(extra="forbid")

    phone: str = Field(..., description="Iranian mobile number (09xxxxxxxxx, +98..., 0098...)")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        try:
            return validate_iranian_phone(v)
        except DjangoValidationError as exc:
            raise ValueError("Enter a valid Iranian mobile number (e.g. 09123456789).") from exc


class OtpRequestOut(Schema):
    """Generic response payload for OTP request (no account enumeration)."""

    model_config = ConfigDict(extra="forbid")

    sent: bool
    expires_in_seconds: int


class OtpVerifyIn(Schema):
    """Request payload for verifying an OTP code."""

    model_config = ConfigDict(extra="forbid")

    phone: str = Field(..., description="Iranian mobile number")
    code: str = Field(..., min_length=1, max_length=10, description="5-digit OTP code")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        try:
            return validate_iranian_phone(v)
        except DjangoValidationError as exc:
            raise ValueError("Enter a valid Iranian mobile number (e.g. 09123456789).") from exc


class OtpVerifyOut(Schema):
    """Verified user identity returned on OTP verification (Task T-006 / T-007)."""

    model_config = ConfigDict(extra="forbid")

    id: int
    phone: str
    role: str


class LogoutOut(Schema):
    """Response payload returned on session logout (Task T-007)."""

    model_config = ConfigDict(extra="forbid")

    logged_out: bool


class CsrfOut(Schema):
    """Response payload for CSRF token bootstrap endpoint (Task T-007)."""

    model_config = ConfigDict(extra="forbid")

    csrf_token: str
