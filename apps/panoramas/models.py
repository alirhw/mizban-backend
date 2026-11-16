"""Domain models for the panoramas app (Space, PanoramaImage, TablePin).

Task T-015:
- Space model representing a 360 virtual scene / floor-plan subdivision of a Venue (ADR-005).
- PanoramaImage model representing equirectangular 360-degree panorama images with status lifecycle:
  UPLOADED -> PROCESSING -> READY / FAILED (ARCH-003, TD-003).
- TablePin model representing reservable tables pinned to panoramas with spherical coordinates:
  pitch in [-90, 90], yaw in [-180, 180], capacity > 0.
- TablePin deletion protection: confirmed/active bookings cannot be deleted via CASCADE (ADR-005).
"""
from __future__ import annotations

from datetime import timedelta
import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.exceptions import InvalidStatusTransitionError


class Space(models.Model):
    """A physical and visual area within a venue (e.g. Indoor, Terrace, Rooftop).

    ADR-005: Owned by apps/panoramas, serving as the visual walkthrough scene
    and grouping parent for TablePins and PanoramaImages.
    """

    venue = models.ForeignKey(
        "venues.Venue",
        on_delete=models.CASCADE,
        related_name="spaces",
    )
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    active_panorama = models.ForeignKey(
        "PanoramaImage",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="The currently published 360 panorama image for this space.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["venue", "display_order", "name"]

    def __str__(self) -> str:
        return f"{self.venue.name} - {self.name}"

    def delete(self, using=None, keep_parents=False):
        """Prevent deletion if any bookings exist for table pins in this space (ADR-005)."""
        from apps.bookings.models import Booking

        bookings = Booking.objects.filter(table_pin__space=self)
        if bookings.exists():
            raise models.ProtectedError(
                f"Cannot delete Space '{self.name}' because it contains tables with existing booking history. "
                "Deactivate it instead.",
                bookings.all(),
            )
        return super().delete(using=using, keep_parents=keep_parents)

    def deactivate(self) -> None:
        """Soft-deactivate the space so it no longer appears in public listings or bookable slots."""
        self.is_active = False
        self.save(update_fields=["is_active", "updated_at"])


class PanoramaStatus(models.TextChoices):
    UPLOADED = "UPLOADED", "Uploaded"
    PROCESSING = "PROCESSING", "Processing"
    READY = "READY", "Ready"
    FAILED = "FAILED", "Failed"


VALID_PANORAMA_TRANSITIONS: dict[str, set[str]] = {
    PanoramaStatus.UPLOADED: {PanoramaStatus.PROCESSING},
    PanoramaStatus.PROCESSING: {PanoramaStatus.READY, PanoramaStatus.FAILED},
    PanoramaStatus.READY: set(),
    PanoramaStatus.FAILED: {PanoramaStatus.PROCESSING},  # allow retry/re-process
}


class PanoramaImage(models.Model):
    """An equirectangular 360-degree panorama photograph for a Space (TD-003 / ARCH-003).

    Lifecycle:
        UPLOADED: raw image accepted via API (HTTP 202), Celery task queued.
        PROCESSING: Celery worker active; resizing to <= 4096x2048 WebP + 512x256 thumbnail.
        READY: processing succeeded; original file deleted from disk.
        FAILED: conversion failed (corrupted file, wrong aspect ratio).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    space = models.ForeignKey(
        Space,
        on_delete=models.CASCADE,
        related_name="panorama_images",
    )
    status = models.CharField(
        max_length=20,
        choices=PanoramaStatus.choices,
        default=PanoramaStatus.UPLOADED,
        db_index=True,
    )
    original_file = models.FileField(
        upload_to="panoramas/originals/%Y/%m/",
        null=True,
        blank=True,
        help_text="Temporary raw image prior to Celery WebP conversion.",
    )
    webp_file = models.FileField(
        upload_to="panoramas/webp/%Y/%m/",
        null=True,
        blank=True,
        help_text="Final optimized 4K WebP equirectangular asset.",
    )
    thumb_file = models.FileField(
        upload_to="panoramas/thumbs/%Y/%m/",
        null=True,
        blank=True,
        help_text="512x256 LQIP thumbnail for instant first paint.",
    )
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    file_size_bytes = models.PositiveIntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True, help_text="Sanitized error reason if processing failed.")
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Panorama {self.id} for {self.space.name} ({self.status})"

    def transition_to(self, new_status: str, *, error_message: str = "", save: bool = True) -> None:
        """Validate and apply state machine transition (TD-003 / ARCH-003)."""
        allowed = VALID_PANORAMA_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise InvalidStatusTransitionError(
                f"Cannot transition panorama from {self.status} to {new_status}"
            )
        self.status = new_status
        if error_message:
            self.error_message = error_message
        if new_status == PanoramaStatus.READY:
            self.processed_at = timezone.now()
        if save:
            update_fields = ["status", "processed_at"]
            if error_message:
                update_fields.append("error_message")
            self.save(update_fields=update_fields)


class TablePin(models.Model):
    """A reservable table represented as a pin on a 360-degree panorama scene."""

    venue = models.ForeignKey(
        "venues.Venue",
        on_delete=models.CASCADE,
        related_name="table_pins",
    )
    space = models.ForeignKey(
        Space,
        on_delete=models.CASCADE,
        related_name="table_pins",
        null=True,
        blank=True,
    )
    panorama_image = models.ForeignKey(
        PanoramaImage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="table_pins",
        help_text="The panorama image on which this pin coordinate is projected.",
    )
    table_number = models.CharField(max_length=20, help_text="e.g. Table 12, Booth 3")
    capacity = models.PositiveIntegerField(default=2)
    pitch = models.FloatField(
        null=True,
        blank=True,
        help_text="Spherical pitch in degrees [-90.0, 90.0] (vertical angle).",
    )
    yaw = models.FloatField(
        null=True,
        blank=True,
        help_text="Spherical yaw in degrees [-180.0, 180.0] (horizontal angle).",
    )
    description = models.CharField(max_length=200, blank=True, help_text="e.g. By the window")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["venue", "table_number"],
                name="unique_table_number_per_venue",
            ),
            models.CheckConstraint(
                condition=models.Q(pitch__gte=-90.0, pitch__lte=90.0) | models.Q(pitch__isnull=True),
                name="table_pin_pitch_bounds",
            ),
            models.CheckConstraint(
                condition=models.Q(yaw__gte=-180.0, yaw__lte=180.0) | models.Q(yaw__isnull=True),
                name="table_pin_yaw_bounds",
            ),
            models.CheckConstraint(
                condition=models.Q(capacity__gt=0),
                name="table_pin_capacity_positive",
            ),
        ]
        ordering = ["venue", "table_number"]

    def __str__(self) -> str:
        return f"{self.venue.name} - {self.table_number} ({self.capacity}p)"

    def clean(self):
        super().clean()
        if self.pitch is not None and not (-90.0 <= self.pitch <= 90.0):
            raise ValidationError({"pitch": "Pitch must be between -90.0 and 90.0 degrees."})
        if self.yaw is not None and not (-180.0 <= self.yaw <= 180.0):
            raise ValidationError({"yaw": "Yaw must be between -180.0 and 180.0 degrees."})
        if self.capacity <= 0:
            raise ValidationError({"capacity": "Capacity must be greater than 0."})

    def delete(self, using=None, keep_parents=False):
        """Prevent deletion if any bookings exist for this table pin (ADR-005)."""
        if self.bookings.exists():
            raise models.ProtectedError(
                f"Cannot delete TablePin '{self.table_number}' because it has existing bookings. "
                "Deactivate it instead.",
                self.bookings.all(),
            )
        return super().delete(using=using, keep_parents=keep_parents)

    def deactivate(self) -> None:
        """Soft-deactivate the table so it no longer appears in bookable slots."""
        self.is_active = False
        self.save(update_fields=["is_active", "updated_at"])

    def next_bookable_slot(self, now=None):
        """Helper for tests and booking services to get the next bookable slot."""
        from apps.scheduling.services import get_venue_slots_for_date

        if now is None:
            now = timezone.now()

        # Look ahead across the next 7 days for the first bookable slot
        for offset in range(1, 8):
            target_date = (now + timedelta(days=offset)).date()
            slots = get_venue_slots_for_date(self.venue, on_date=target_date, now=now)
            bookable = [s for s in slots if s.is_bookable]
            if bookable:
                return bookable[0]
        return None
