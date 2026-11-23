"""Pydantic in/out schemas for the scheduling app.

Naming (Architecture Spec section 28): PascalCase with an explicit
In/Out suffix, e.g. SlotOut.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from ninja import Field, Schema
from pydantic import ConfigDict

from core.jalali import format_jalali


class SlotOut(Schema):
    """Public representation of a generated slot."""

    start: datetime
    end: datetime
    is_bookable: bool
    disabled_reason: Optional[str] = None
    start_jalali: str = ""
    end_jalali: str = ""

    @staticmethod
    def resolve_start_jalali(obj) -> str:
        return format_jalali(obj.start)

    @staticmethod
    def resolve_end_jalali(obj) -> str:
        return format_jalali(obj.end)


class BlockedSlotCreateIn(Schema):
    """Owner request payload for blocking one generated slot on a TablePin (FR-011)."""

    model_config = ConfigDict(extra="forbid")

    start_at: datetime = Field(..., description="Exact slot start instant (UTC) from availability API")
    reason: str = Field(default="", max_length=255, description="Optional owner-private reason")


class BlockedSlotOut(Schema):
    """Owner response payload for a BlockedSlot (FR-011)."""

    model_config = ConfigDict(extra="forbid")

    id: int
    pin_id: int
    start_at: datetime
    end_at: datetime
    jalali_start_at: str
    reason: str

    @staticmethod
    def resolve_pin_id(obj) -> int:
        return obj.table_pin_id
