"""Pydantic schemas for the billing app (Payment gateway and transactions).

Architecture Spec section 28: PascalCase with explicit In/Out suffix.
Extra fields forbidden for strict validation.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from ninja import Schema
from pydantic import ConfigDict, Field


class PaymentInitiateIn(Schema):
    """Payload to initiate an online payment for a booking."""

    model_config = ConfigDict(extra="forbid")

    booking_id: int = Field(..., description="ID of the booking to pay for.")
    idempotency_key: str = Field(..., max_length=100, description="Client-generated unique idempotency token.")
    callback_url: str = Field(..., description="URL where the user returns after gateway interaction.")


class PaymentInitiateOut(Schema):
    """Response returned upon initiating a payment."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: int
    booking_id: int
    amount_toman: int
    currency: str
    status: str
    provider_name: str
    provider_reference: str | None
    redirect_url: str


class PaymentVerifyIn(Schema):
    """Payload to verify an online payment."""

    model_config = ConfigDict(extra="forbid")

    provider_reference: str = Field(..., description="Gateway authority / reference token.")
    callback_params: dict[str, Any] = Field(
        default_factory=dict,
        description="Raw query parameters returned by gateway.",
    )


class PaymentTransactionOut(Schema):
    """Public detail schema for a payment transaction."""

    model_config = ConfigDict(extra="forbid")

    id: int
    booking_id: int
    amount_toman: int
    currency: str
    status: str
    provider_name: str
    provider_reference: str | None
    tracking_code: str
    card_pan_masked: str
    created_at: datetime
    verified_at: datetime | None


class PaymentCallbackOut(Schema):
    """Standardized response schema for payment gateway callback outcome (Task T-021 / ADR-006)."""

    model_config = ConfigDict(extra="forbid")

    booking_id: int | None = Field(default=None, description="Booking ID associated with transaction.")
    booking_status: str = Field(..., description="Resulting booking status (CONFIRMED, EXPIRED, CANCELLED).")
    payment_status: str = Field(..., description="Terminal payment transaction status (SUCCESS, FAILED, TIMEOUT).")
    refund_required: bool = Field(..., description="Whether payment must be refunded to customer bank card.")
    tracking_code: str = Field(default="", description="Gateway tracking/reference code if settled.")
    message: str = Field(default="", description="Descriptive status message.")


class WalletPayIn(Schema):
    """Payload to pay for a pending booking using the customer's in-app wallet."""

    model_config = ConfigDict(extra="forbid")

    booking_id: int = Field(..., gt=0, description="ID of the pending booking to pay for.")
    idempotency_key: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Client-generated unique idempotency token.",
    )


class FinancialReportPaymentRowOut(Schema):
    """Single payment transaction row in the admin financial report."""

    model_config = ConfigDict(extra="forbid")

    id: int
    booking_id: int
    customer_id: int
    provider_name: str
    amount_toman: int
    status: str
    created_at: datetime


class FinancialReportWalletRowOut(Schema):
    """Single wallet ledger row in the admin financial report."""

    model_config = ConfigDict(extra="forbid")

    id: int
    user_id: int
    type: str
    amount_toman: int
    balance_after_toman: int
    reason: str
    booking_id: int | None
    created_at: datetime


class FinancialReportPaymentsSectionOut(Schema):
    """Aggregated payments section of the admin financial report."""

    model_config = ConfigDict(extra="forbid")

    total_toman: int
    count: int
    counts_by_status: dict[str, int]
    rows: list[FinancialReportPaymentRowOut]


class FinancialReportWalletSectionOut(Schema):
    """Aggregated wallet ledger section of the admin financial report."""

    model_config = ConfigDict(extra="forbid")

    total_credit_toman: int
    total_debit_toman: int
    count: int
    rows: list[FinancialReportWalletRowOut]


class FinancialReportSubscriptionsSectionOut(Schema):
    """Aggregated subscriptions section of the admin financial report (post-MVP placeholder)."""

    model_config = ConfigDict(extra="forbid")

    total_toman: int
    count: int
    rows: list[Any]


class FinancialReportOut(Schema):
    """Read-only admin financial report response (Task T-040 / FR-40 / UC-10)."""

    model_config = ConfigDict(extra="forbid")

    payments: FinancialReportPaymentsSectionOut
    wallet: FinancialReportWalletSectionOut
    subscriptions: FinancialReportSubscriptionsSectionOut

