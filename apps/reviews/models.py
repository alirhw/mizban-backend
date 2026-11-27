"""Domain models for the reviews app (FR-24/FR-25, BR-09/BR-13)."""
from __future__ import annotations

from django.db import models


class Review(models.Model):
    """Customer review tied 1:1 to a completed booking."""

    booking = models.ForeignKey(
        "bookings.Booking",
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    rating = models.IntegerField()
    text = models.TextField()
    is_visible = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["booking"],
                name="unique_review_per_booking",
            ),
            models.CheckConstraint(
                condition=models.Q(rating__gte=1, rating__lte=5),
                name="review_rating_between_1_and_5",
            ),
        ]

    def __str__(self) -> str:
        return f"Review #{self.pk} (booking={self.booking_id}, rating={self.rating})"
