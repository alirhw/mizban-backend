"""Pydantic in/out schemas for the bookings app (Task T-013).

Naming (Architecture Spec section 28): PascalCase with an explicit
In/Out suffix, e.g. BookingInitiateIn / BookingInitiateOut.
"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import List, Optional, Union

from ninja import Field, Schema
from pydantic import ConfigDict, field_validator

from core.jalali import resolve_date


def resolve_time(time_input: Union[time, str]) -> time:
    """Parse time string in HH:MM or HH:MM:SS format into time object."""
    if isinstance(time_input, time):
        return time_input
    time_str = str(time_input).strip()
    parts = time_str.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"Invalid time format: '{time_input}'. Expected HH:MM.")
    hour, minute = int(parts[0]), int(parts[1])
    second = int(parts[2]) if len(parts) == 3 else 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        raise ValueError(f"Time values out of range: '{time_input}'.")
    return time(hour, minute, second)


class BookingInitiateIn(Schema):
    """Request payload for initiating a table booking lock."""

    table_pin_id: int = Field(..., description="ID of the TablePin to reserve")
    slot_date: str = Field(..., description="Slot calendar date (YYYY-MM-DD or Jalali YYYY/MM/DD)")
    slot_start_time: str = Field(..., description="Slot start time (HH:MM)")
    venue_id: Optional[int] = Field(None, description="Optional venue ID for boundary validation")
    addon_ids: List[int] = Field(default_factory=list, description="Optional list of DesignAddon IDs")

    @field_validator("table_pin_id")
    @classmethod
    def validate_table_pin_id(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("table_pin_id must be a positive integer.")
        return v

    @field_validator("slot_date")
    @classmethod
    def validate_slot_date(cls, v: str) -> str:
        try:
            resolve_date(v)
        except Exception as e:
            raise ValueError(
                f"Invalid date format: '{v}'. Expected Gregorian YYYY-MM-DD or Jalali YYYY/MM/DD."
            ) from e
        return v

    @field_validator("slot_start_time")
    @classmethod
    def validate_slot_start_time(cls, v: str) -> str:
        try:
            resolve_time(v)
        except Exception as e:
            raise ValueError(f"Invalid time format: '{v}'. Expected HH:MM.") from e
        return v


class BookingInitiateOut(Schema):
    """Response payload returned upon successfully acquiring a booking lock (201 Created)."""

    booking_id: int
    id: int
    status: str
    venue_id: int
    table_pin_id: int
    start_at: datetime
    end_at: datetime
    slot_date: date
    slot_start_time: time
    locked_at: Optional[datetime] = None
    lock_expires_at: Optional[datetime] = None
    amount_online_toman: int
    amount_in_person_toman: int
    start_jalali: str = ""
    end_jalali: str = ""
    jalali_start_datetime: str = ""
    jalali_end_datetime: str = ""
    jalali_date: str = ""

    @staticmethod
    def resolve_booking_id(obj) -> int:
        return obj.id

    @staticmethod
    def resolve_start_jalali(obj) -> str:
        return obj.jalali_start_datetime

    @staticmethod
    def resolve_end_jalali(obj) -> str:
        return obj.jalali_end_datetime


class BookingCancelOut(Schema):
    """Response payload returned upon booking cancellation (200 OK, Task T-023 / BR-004)."""

    model_config = ConfigDict(extra="forbid")

    booking_id: int = Field(..., description="ID of the cancelled booking")
    status: str = Field(..., description="New booking status (CANCELLED)")
    refunded_to_wallet_toman: int = Field(
        ..., description="Amount credited to wallet by this cancellation call (integer Toman)"
    )
    wallet_balance_toman: Optional[int] = Field(
        default=None, description="Customer wallet balance after this operation if a refund occurred"
    )


class CustomerBookingOut(Schema):
    """Read-only customer booking list item with server-derived cancellability (PH-06-03-PRE)."""

    model_config = ConfigDict(extra="forbid")

    booking_id: int
    venue_name: str
    venue_slug: str
    table_number: str
    status: str
    slot_date: date
    jalali_date: str
    slot_start_time: time
    start_at: datetime
    end_at: datetime
    start_jalali: str
    end_jalali: str
    amount_online_toman: int
    amount_in_person_toman: int
    is_cancellable: bool
    cancel_refund_toman: int
    created_at: datetime


class SplitReceiptOnlineSectionOut(Schema):
    """Online payment section of a split receipt (BR-003: 100% platform share)."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(..., description="Section label indicating paid online / platform share")
    description: str = Field(..., description="Line item description for the table reservation fee")
    amount_online_toman: int = Field(..., description="Table reservation fee paid online (integer Toman)")
    provider_name: Optional[str] = Field(
        default=None, description="Gateway provider name from the successful PaymentTransaction, if present"
    )
    card_pan_masked: Optional[str] = Field(
        default=None, description="Masked card PAN (e.g. 603799******1234) if stored on the successful payment"
    )


class SplitReceiptAddonLineOut(Schema):
    """Single itemised design add-on line payable in person at the venue (BR-003)."""

    model_config = ConfigDict(extra="forbid")

    addon_id: int = Field(..., description="ID of the DesignAddon")
    title: str = Field(..., description="Add-on title")
    unit_fee_toman: int = Field(..., description="Price snapshot taken at booking time (integer Toman)")
    line_total_toman: int = Field(..., description="Line total payable in person (integer Toman)")


class SplitReceiptInPersonSectionOut(Schema):
    """In-person payable section of a split receipt (BR-003: venue design add-ons)."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(..., description="Section label indicating payable in person at the venue")
    items: List[SplitReceiptAddonLineOut] = Field(
        default_factory=list, description="Itemised design add-on snapshots"
    )
    total_in_person_toman: int = Field(
        ..., description="Sum of all in-person add-on line totals (integer Toman)"
    )


class SplitReceiptOut(Schema):
    """Read-only split receipt for a confirmed or completed booking (Task T-024 / BR-003 / ARCH-005)."""

    model_config = ConfigDict(extra="forbid")

    booking_id: int
    status: str
    venue_name: str
    venue_slug: str
    table_number: str
    start_at: datetime
    end_at: datetime
    slot_date: date
    slot_start_time: time
    jalali_date: str
    jalali_start_datetime: str
    jalali_end_datetime: str
    paid_online: SplitReceiptOnlineSectionOut
    payable_in_person: SplitReceiptInPersonSectionOut
    total_online_toman: int
    total_in_person_toman: int
    grand_total_toman: int


