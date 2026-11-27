"""Service layer for the notifications app (FR-36, BR-10, BR-16)."""
from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404

from apps.notifications.models import Notification, NotificationType
from core.jalali import format_jalali

logger = logging.getLogger(__name__)


def _clamp_pagination(limit: int, offset: int) -> tuple[int, int]:
    """Clamp pagination parameters to [1, 100] and offset >= 0."""
    clamped_limit = max(1, min(limit, 100))
    clamped_offset = max(0, offset)
    return clamped_limit, clamped_offset


def _booking_details(notification: Notification) -> tuple[str, str, str] | None:
    """Extract safe display fields (venue_name, table_number, jalali_start) from booking."""
    booking = notification.booking
    if booking is None:
        return None
    venue_name = booking.venue.name if booking.venue is not None else "مجموعه"
    table_number = booking.table_pin.table_number if booking.table_pin is not None else "—"
    jalali_start = format_jalali(booking.start_at, fmt="%Y/%m/%d %H:%M")
    return venue_name, table_number, jalali_start


def render_notification_copy(notification: Notification) -> tuple[str, str]:
    """Render Persian (title, body) at read time without exposing phone, email, or last name."""
    notif_type = notification.type

    if notif_type == NotificationType.BOOKING_CONFIRMED:
        details = _booking_details(notification)
        if details is None:
            return ("رزرو جدید تایید شد", "یک رزرو تایید شد.")
        venue_name, table_number, jalali_start = details
        return (
            "رزرو جدید تایید شد",
            f"رزرو میز {table_number} در {venue_name} برای تاریخ {jalali_start} تایید شد.",
        )

    if notif_type == NotificationType.BOOKING_CANCELLED:
        details = _booking_details(notification)
        if details is None:
            return ("رزرو لغو شد", "یک رزرو لغو شد.")
        venue_name, table_number, jalali_start = details
        return (
            "رزرو لغو شد",
            f"رزرو میز {table_number} در {venue_name} برای تاریخ {jalali_start} لغو شد.",
        )

    if notif_type == NotificationType.VENUE_APPROVED:
        venue = notification.venue
        if venue is None:
            return ("مجموعه تایید شد", "مجموعه شما توسط مدیر تایید شد.")
        return ("مجموعه تایید شد", f"مجموعه «{venue.name}» توسط مدیر تایید شد.")

    if notif_type == NotificationType.VENUE_REJECTED:
        venue = notification.venue
        if venue is None:
            return ("مجموعه رد شد", "مجموعه شما توسط مدیر رد شد.")
        reason = (venue.rejection_reason or "").strip()
        if reason:
            return ("مجموعه رد شد", f"مجموعه «{venue.name}» رد شد. دلیل: {reason}")
        return ("مجموعه رد شد", f"مجموعه «{venue.name}» توسط مدیر رد شد.")

    return ("اعلان جدید", "اعلان جدیدی برای شما ثبت شده است.")


def serialize_notification(notification: Notification) -> dict[str, Any]:
    """Serialize a Notification row with read-time rendered Persian copy."""
    title, body = render_notification_copy(notification)
    return {
        "id": notification.id,
        "type": notification.type,
        "booking_id": notification.booking_id,
        "venue_id": notification.venue_id,
        "title": title,
        "body": body,
        "is_read": notification.is_read,
        "created_at": notification.created_at,
    }


def create_notification(
    *,
    recipient: Any,
    type: str,
    booking: Any = None,
    venue: Any = None,
) -> Notification:
    """Create an in-app notification row inside the caller's transaction."""
    notification = Notification.objects.create(
        recipient=recipient,
        type=type,
        booking=booking,
        venue=venue,
    )
    logger.info(
        "Notification created",
        extra={
            "notification_id": notification.id,
            "type": notification.type,
            "recipient_id": notification.recipient_id,
        },
    )
    return notification


def list_my_notifications(
    user: Any,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return the authenticated user's notifications ordered newest first."""
    clamped_limit, clamped_offset = _clamp_pagination(limit, offset)
    rows = list(
        Notification.objects.filter(recipient_id=user.id)
        .select_related("booking__venue", "booking__table_pin", "venue")
        .order_by("-created_at", "-id")[clamped_offset : clamped_offset + clamped_limit]
    )
    return [serialize_notification(notification) for notification in rows]


def unread_count(user: Any) -> int:
    """Return the count of unread notifications for the authenticated user."""
    return Notification.objects.filter(recipient_id=user.id, is_read=False).count()


def mark_as_read(user: Any, notification_id: int) -> Notification:
    """Mark a single notification as read (404 if missing, 403 if owned by another user)."""
    with transaction.atomic():
        notification = (
            Notification.objects.select_for_update(of=("self",))
            .select_related("booking__venue", "booking__table_pin", "venue")
            .filter(pk=notification_id)
            .first()
        )
        if notification is None:
            raise Http404("Notification not found.")
        if notification.recipient_id != user.id:
            raise PermissionDenied("You cannot mark another user's notification as read.")
        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=["is_read"])
        return notification


def mark_all_as_read(user: Any) -> int:
    """Mark all unread notifications for the authenticated user as read."""
    return Notification.objects.filter(recipient_id=user.id, is_read=False).update(is_read=True)
