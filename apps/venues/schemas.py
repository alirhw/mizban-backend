"""Pydantic in/out schemas for the venues app (Task T-009).

Naming (Architecture Spec section 28): PascalCase with an explicit
In/Out suffix, e.g. VenueCreateIn / VenuePublicDetailOut.
Never expose customer or owner phone numbers in public schemas (NFR-005).
"""
from __future__ import annotations

from datetime import date, datetime, time

from ninja import Schema
from pydantic import ConfigDict


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
    subscription_status: str
    is_publicly_visible: bool
    created_at: datetime
    updated_at: datetime
    operating_hours: list[OperatingHoursOut] = []
    design_addons: list[DesignAddonOut] = []


class VenueCreateIn(Schema):
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
    name: str | None = None
    city: str | None = None
    venue_type: str | None = None
    address: str | None = None
    description: str | None = None


class VenueApprovalOut(Schema):
    id: int
    slug: str
    is_approved: bool
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
