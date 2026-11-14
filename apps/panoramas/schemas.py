"""Pydantic in/out schemas for the panoramas app (Task T-016)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from ninja import Schema


class PanoramaUploadOut(Schema):
    """Response returned when an equirectangular panorama image is uploaded (HTTP 202 Accepted)."""

    id: UUID
    space_id: int
    venue_id: int
    status: str
    original_file: str
    file_size_bytes: int
    width: Optional[int] = None
    height: Optional[int] = None
    created_at: datetime
    message: str = "Panorama image uploaded successfully and queued for processing."
