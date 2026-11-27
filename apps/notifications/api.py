"""Django Ninja router for the notifications app (FR-36, BR-10, BR-16).

Views stay thin (ARCH-001): authenticate, validate via schemas.py,
delegate to services.py, and return typed schemas.
"""
from __future__ import annotations

from typing import Any

from ninja import Router

from apps.accounts.auth import auth
from apps.notifications import services
from apps.notifications.schemas import MarkAllReadOut, NotificationOut, UnreadCountOut

router = Router(tags=["notifications"])


@router.get("/", response=list[NotificationOut], auth=auth, summary="List my notifications")
def list_notifications(
    request: Any,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return the authenticated user's own notifications, newest first."""
    return services.list_my_notifications(request.auth, limit=limit, offset=offset)


@router.get("/unread-count", response=UnreadCountOut, auth=auth, summary="Unread notifications count")
def get_unread_count(request: Any) -> dict[str, int]:
    """Return the number of unread notifications for the authenticated user."""
    return {"unread_count": services.unread_count(request.auth)}


@router.post(
    "/{notification_id}/read",
    response=NotificationOut,
    auth=auth,
    summary="Mark a notification as read",
)
def read_notification(request: Any, notification_id: int) -> dict[str, Any]:
    """Mark one of the authenticated user's notifications as read."""
    notification = services.mark_as_read(request.auth, notification_id)
    return services.serialize_notification(notification)


@router.post("/read-all", response=MarkAllReadOut, auth=auth, summary="Mark all notifications as read")
def read_all_notifications(request: Any) -> dict[str, int]:
    """Mark all unread notifications for the authenticated user as read."""
    return {"marked": services.mark_all_as_read(request.auth)}
