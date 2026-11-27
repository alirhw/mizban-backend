"""Pydantic in/out schemas for the reviews app (FR-24/FR-25)."""
from __future__ import annotations

from datetime import datetime

from ninja import Schema
from pydantic import ConfigDict, Field, StrictInt, field_validator


class ReviewCreateIn(Schema):
    """Customer payload for submitting a review for a completed booking."""

    model_config = ConfigDict(extra="forbid")

    booking_id: int
    rating: StrictInt = Field(ge=1, le=5)
    text: str = Field(min_length=1, max_length=1000)

    @field_validator("text")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Review text cannot be blank.")
        return cleaned


class ReviewPublicOut(Schema):
    """Publicly visible review payload (never exposes PII)."""

    model_config = ConfigDict(extra="forbid")

    id: int
    rating: int
    text: str
    reviewer_name: str
    table_number: str
    created_at: datetime


class ReviewMineOut(ReviewPublicOut):
    """Customer's own review payload including booking reference and visibility."""

    model_config = ConfigDict(extra="forbid")

    booking_id: int
    is_visible: bool


class ReviewListOut(Schema):
    """Paginated public review list with aggregate rating summary."""

    model_config = ConfigDict(extra="forbid")

    average_rating: float | None
    review_count: int
    reviews: list[ReviewPublicOut]
