"""Pydantic output schemas for the notifications app (FR-36, BR-16)."""
from __future__ import annotations

from datetime import datetime

from ninja import Schema
from pydantic import ConfigDict


class NotificationOut(Schema):
    """Serialized in-app notification with read-time rendered Persian copy."""

    model_config = ConfigDict(extra="forbid")

    id: int
    type: str
    booking_id: int | None
    venue_id: int | None
    title: str
    body: str
    is_read: bool
    created_at: datetime


class UnreadCountOut(Schema):
    """Count of unread notifications for the authenticated user."""

    model_config = ConfigDict(extra="forbid")

    unread_count: int


class MarkAllReadOut(Schema):
    """Number of notifications marked as read."""

    model_config = ConfigDict(extra="forbid")

    marked: int
