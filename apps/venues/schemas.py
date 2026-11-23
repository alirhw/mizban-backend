"""Pydantic in/out schemas for the venues app (Task T-009).

Naming (Architecture Spec section 28): PascalCase with an explicit
In/Out suffix, e.g. VenueCreateIn / VenuePublicDetailOut.
Never expose customer or owner phone numbers in public schemas (NFR-005).
"""
from __future__ import annotations

from datetime import datetime, time
from typing import List, Optional

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
    operating_hours: List[OperatingHoursOut] = []
    design_addons: List[DesignAddonOut] = []


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
    operating_hours: List[OperatingHoursOut] = []
    design_addons: List[DesignAddonOut] = []


class VenueCreateIn(Schema):
    name: str
    city: str
    venue_type: str
    address: str
    description: str = ""
    slug: Optional[str] = None


class VenueUpdateIn(Schema):
    """Update schema for venue owners.

    Explicit fields only: is_approved and subscription_status cannot be
    modified by owners (mass assignment prevention).
    """
    name: Optional[str] = None
    city: Optional[str] = None
    venue_type: Optional[str] = None
    address: Optional[str] = None
    description: Optional[str] = None


class VenueApprovalOut(Schema):
    id: int
    slug: str
    is_approved: bool
    message: str


class VenueSubscriptionOut(Schema):
    """Owner read-only subscription status payload (Decision 5 / Task T-025)."""

    model_config = ConfigDict(extra="forbid")

    is_active: bool
    plan_name: Optional[str] = None
    starts_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    jalali_expires_at: Optional[str] = None
    days_remaining: int
    has_ever_subscribed: bool
