"""Domain models for the notifications app (FR-36, BR-10, BR-16)."""
from __future__ import annotations

from django.conf import settings
from django.db import models


class NotificationType(models.TextChoices):
    BOOKING_CONFIRMED = "BOOKING_CONFIRMED", "Booking Confirmed"
    BOOKING_CANCELLED = "BOOKING_CANCELLED", "Booking Cancelled"
    VENUE_APPROVED = "VENUE_APPROVED", "Venue Approved"
    VENUE_REJECTED = "VENUE_REJECTED", "Venue Rejected"


class Notification(models.Model):
    """In-app notification row referencing a booking or venue."""

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    type = models.CharField(max_length=32, choices=NotificationType.choices)
    booking = models.ForeignKey(
        "bookings.Booking",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notifications",
    )
    venue = models.ForeignKey(
        "venues.Venue",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notifications",
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["recipient", "is_read", "-created_at"],
                name="idx_notif_recipient_read",
            ),
        ]

    def __str__(self) -> str:
        return f"Notification({self.pk}, type={self.type}, recipient_id={self.recipient_id})"
