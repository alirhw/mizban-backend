"""Pydantic in/out schemas for the panoramas app (Tasks T-016 & T-018)."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any
from uuid import UUID

from ninja import Schema
from pydantic import ConfigDict, Field, StrictInt, field_validator


class PanoramaUploadOut(Schema):
    """Response returned when an equirectangular panorama image is uploaded (HTTP 202 Accepted)."""

    id: UUID
    space_id: int
    venue_id: int
    status: str
    original_file: str
    file_size_bytes: int
    width: int | None = None
    height: int | None = None
    created_at: datetime
    message: str = "Panorama image uploaded successfully and queued for processing."


class TablePinCreateIn(Schema):
    """Payload to drop/create a new table pin in a space (Task T-018)."""

    model_config = ConfigDict(extra="forbid")

    table_number: str
    capacity: StrictInt = Field(default=2, ge=0)
    pitch: float | None = None
    yaw: float | None = None
    panorama_image_id: UUID | None = None
    description: str = ""
    reservation_fee_toman: StrictInt = Field(ge=0, le=9_223_372_036_854_775_807)
    is_smoking: bool = False
    is_active: bool = True

    @field_validator("pitch")
    @classmethod
    def validate_pitch(cls, v: float | None) -> float | None:
        if v is not None:
            if math.isnan(v) or math.isinf(v):
                raise ValueError("Pitch cannot be NaN or infinite.")
            if not (-90.0 <= v <= 90.0):
                raise ValueError("Pitch must be between -90.0 and 90.0 degrees inclusive.")
        return v

    @field_validator("yaw")
    @classmethod
    def validate_yaw(cls, v: float | None) -> float | None:
        if v is not None:
            if math.isnan(v) or math.isinf(v):
                raise ValueError("Yaw cannot be NaN or infinite.")
            if not (-180.0 <= v <= 180.0):
                raise ValueError("Yaw must be between -180.0 and 180.0 degrees inclusive.")
        return v

    @field_validator("capacity")
    @classmethod
    def validate_capacity(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Capacity must be strictly positive (greater than 0).")
        return v

    @field_validator("table_number")
    @classmethod
    def validate_table_number(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Table number cannot be empty or blank.")
        return s

    @field_validator("reservation_fee_toman")
    @classmethod
    def validate_reservation_fee(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Reservation fee must be non-negative (>= 0).")
        return v


class TablePinUpdateIn(Schema):
    """Payload to update an existing table pin (Task T-018)."""

    model_config = ConfigDict(extra="forbid")

    table_number: str | None = None
    capacity: StrictInt | None = Field(default=None, ge=0)
    pitch: float | None = None
    yaw: float | None = None
    panorama_image_id: UUID | None = None
    description: str | None = None
    reservation_fee_toman: StrictInt | None = Field(
        default=None,
        ge=0,
        le=9_223_372_036_854_775_807,
    )
    is_smoking: bool | None = None
    is_active: bool | None = None

    @field_validator("pitch")
    @classmethod
    def validate_pitch(cls, v: float | None) -> float | None:
        if v is not None:
            if math.isnan(v) or math.isinf(v):
                raise ValueError("Pitch cannot be NaN or infinite.")
            if not (-90.0 <= v <= 90.0):
                raise ValueError("Pitch must be between -90.0 and 90.0 degrees inclusive.")
        return v

    @field_validator("yaw")
    @classmethod
    def validate_yaw(cls, v: float | None) -> float | None:
        if v is not None:
            if math.isnan(v) or math.isinf(v):
                raise ValueError("Yaw cannot be NaN or infinite.")
            if not (-180.0 <= v <= 180.0):
                raise ValueError("Yaw must be between -180.0 and 180.0 degrees inclusive.")
        return v

    @field_validator("capacity")
    @classmethod
    def validate_capacity(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("Capacity must be strictly positive (greater than 0).")
        return v

    @field_validator("table_number")
    @classmethod
    def validate_table_number(cls, v: str | None) -> str | None:
        if v is not None:
            s = v.strip()
            if not s:
                raise ValueError("Table number cannot be empty or blank.")
            return s
        return v

    @field_validator("reservation_fee_toman")
    @classmethod
    def validate_reservation_fee(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("Reservation fee must be non-negative (>= 0).")
        return v


class TablePinOut(Schema):
    """Response returned when an owner creates, views, or updates a table pin."""

    id: int
    venue_id: int
    space_id: int | None
    panorama_image_id: UUID | None
    table_number: str
    capacity: int
    pitch: float | None
    yaw: float | None
    description: str
    reservation_fee_toman: int
    is_smoking: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PublicTablePinOut(Schema):
    """Publicly visible pin placed in a 360 panorama scene."""

    id: int
    table_number: str
    capacity: int
    pitch: float | None
    yaw: float | None
    description: str
    reservation_fee_toman: int
    is_smoking: bool


class PublicPanoramaOut(Schema):
    """Public response for GET /api/v1/spaces/{space_id}/panorama/ (Task T-018).

    Only returned when:
    - Venue is publicly visible under BR-005 (approved + subscription active)
    - Space is active
    - Active READY panorama image exists
    Otherwise HTTP 404 is returned.
    """

    space_id: int
    space_name: str
    venue_id: int
    venue_name: str
    panorama_image_id: UUID
    image_url: str
    thumbnail_url: str | None = None
    width: int | None = None
    height: int | None = None
    pins: list[PublicTablePinOut]


# ==============================================================================
# Space Schemas (Task T-018b)
# ==============================================================================

class SpaceCreateIn(Schema):
    """Payload to create a new space under a venue (Task T-018b)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    display_order: int = 0
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Space name cannot be empty or blank.")
        if len(s) > 100:
            raise ValueError("Space name cannot exceed 100 characters.")
        return s

    @field_validator("display_order")
    @classmethod
    def validate_display_order(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Display order must be an integer greater than or equal to 0.")
        return v


class SpaceUpdateIn(Schema):
    """Payload to update an existing space (Task T-018b)."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    display_order: int | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        if v is not None:
            s = v.strip()
            if not s:
                raise ValueError("Space name cannot be empty or blank.")
            if len(s) > 100:
                raise ValueError("Space name cannot exceed 100 characters.")
            return s
        return v

    @field_validator("display_order")
    @classmethod
    def validate_display_order(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("Display order must be an integer greater than or equal to 0.")
        return v


class SpacePublicOut(Schema):
    """Public representation of a Space within an approved, active venue (BR-005)."""

    id: int
    venue_id: int
    name: str
    description: str
    display_order: int
    is_active: bool
    active_panorama_id: UUID | None = None
    panorama_status: str | None = None

    @staticmethod
    def resolve_panorama_status(obj: Any) -> str | None:
        if getattr(obj, "active_panorama_id", None) and getattr(obj, "active_panorama", None):
            return obj.active_panorama.status
        return None


class SpaceOut(SpacePublicOut):
    """Full representation of a Space for venue owners and detail views."""

    created_at: datetime
    updated_at: datetime
