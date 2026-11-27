"""Pydantic in/out schemas for the venues app (Task T-009).

Naming (Architecture Spec section 28): PascalCase with an explicit
In/Out suffix, e.g. VenueCreateIn / VenuePublicDetailOut.
Never expose customer or owner phone numbers in public schemas (NFR-005).
"""
from __future__ import annotations

from datetime import date, datetime, time

from ninja import Schema
from pydantic import ConfigDict, Field, StrictInt, field_validator


class OperatingHoursOut(Schema):
    id: int
    weekday: int
    open_time: time
    close_time: time
    crosses_midnight: bool


class DesignAddonOut(Schema):
    id: int
    title: str
    fee: int
    is_active: bool


class _DesignAddonInBase(Schema):
    """Shared validation for design add-on create and update payloads."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    fee: StrictInt = Field(ge=0, le=9_223_372_036_854_775_807)

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Design add-on title cannot be blank.")
        return cleaned


class DesignAddonCreateIn(_DesignAddonInBase):
    """Owner payload for creating a design add-on (FR-32 / T-035)."""

    is_active: bool = True


class DesignAddonUpdateIn(_DesignAddonInBase):
    """Owner payload for replacing a design add-on (FR-32 / T-035)."""

    is_active: bool


class VenuePublicItemOut(Schema):
    """Public catalogue listing item.

    Privacy rule: Never exposes owner phone number or internal flags.
    """
    id: int
    name: str
    slug: str
    city: str
    venue_type: str
    address: str
    description: str


class VenuePublicDetailOut(VenuePublicItemOut):
    """Public catalogue detail view."""
    operating_hours: list[OperatingHoursOut] = []
    design_addons: list[DesignAddonOut] = []


class VenueOwnerOut(Schema):
    """Owner view of a venue with management metadata."""
    id: int
    name: str
    slug: str
    city: str
    venue_type: str
    address: str
    description: str
    is_approved: bool
    review_status: str
    rejection_reason: str
    submitted_for_review_at: datetime | None
    subscription_status: str
    is_publicly_visible: bool
    created_at: datetime
    updated_at: datetime
    operating_hours: list[OperatingHoursOut] = []
    design_addons: list[DesignAddonOut] = []


class VenueCreateIn(Schema):
    model_config = ConfigDict(extra="forbid")

    name: str
    city: str
    venue_type: str
    address: str
    description: str = ""
    slug: str | None = None


class VenueUpdateIn(Schema):
    """Update schema for venue owners.

    Explicit fields only: is_approved and subscription_status cannot be
    modified by owners (mass assignment prevention).
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    city: str | None = None
    venue_type: str | None = None
    address: str | None = None
    description: str | None = None


class VenueRejectIn(Schema):
    """Admin payload for rejecting a venue with a reason (FR-37 / T-036)."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Rejection reason cannot be blank.")
        return cleaned


class VenueApprovalOut(Schema):
    id: int
    slug: str
    is_approved: bool
    review_status: str
    rejection_reason: str = ""
    message: str


class VenueSubscriptionOut(Schema):
    """Owner read-only subscription status payload (Decision 5 / Task T-025)."""

    model_config = ConfigDict(extra="forbid")

    is_active: bool
    plan_name: str | None = None
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    jalali_expires_at: str | None = None
    days_remaining: int
    has_ever_subscribed: bool


class OwnerBookingOut(Schema):
    """Read-only owner booking list item with server-masked customer phone (PH-06-02-PRE)."""

    model_config = ConfigDict(extra="forbid")

    booking_id: int
    status: str
    table_number: str
    slot_date: date
    jalali_date: str
    slot_start_time: time
    start_at: datetime
    end_at: datetime
    start_jalali: str
    end_jalali: str
    amount_online_toman: int
    amount_in_person_toman: int
    customer_phone_masked: str
    created_at: datetime
