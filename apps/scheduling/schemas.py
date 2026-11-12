"""Pydantic in/out schemas for the scheduling app.

Naming (Architecture Spec section 28): PascalCase with an explicit
In/Out suffix, e.g. SlotOut.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from ninja import Schema

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
