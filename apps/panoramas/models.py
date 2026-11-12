"""Domain models for the panoramas app (Space, PanoramaImage, TablePin).

Starter models for visual table pins and spaces (Architecture Spec section 6).
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from django.db import models
from django.utils import timezone


class Space(models.Model):
    """A physical space within a venue (e.g. Indoor, Terrace, Rooftop)."""

    venue = models.ForeignKey(
        "venues.Venue",
        on_delete=models.CASCADE,
        related_name="spaces",
    )
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["venue", "name"]

    def __str__(self) -> str:
        return f"{self.venue.name} - {self.name}"


class TablePin(models.Model):
    """A reservable table represented as a pin on a 360-degree panorama."""

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
    table_number = models.CharField(max_length=20, help_text="e.g. Table 12, Booth 3")
    capacity = models.PositiveIntegerField(default=2)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["venue", "table_number"],
                name="unique_table_number_per_venue",
            ),
        ]
        ordering = ["venue", "table_number"]

    def __str__(self) -> str:
        return f"{self.venue.name} - {self.table_number} ({self.capacity}p)"

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
