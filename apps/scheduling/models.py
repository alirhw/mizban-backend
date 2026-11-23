"""Domain models for the scheduling app (Task T-026 / FR-011)."""
from __future__ import annotations

from django.conf import settings
from django.db import models

from core.jalali import format_jalali


class BlockedSlot(models.Model):
    """An owner-created manual block over a single generated table slot (FR-011 / BR-001).

    Invariants:
    - Applies to ONE TablePin and ONE concrete generated slot window [start_at, end_at).
    - Stored in aware UTC (ARCH-006).
    - reason is owner-private and never exposed in public availability or booking responses.
    """

    table_pin = models.ForeignKey(
        "panoramas.TablePin",
        on_delete=models.CASCADE,
        related_name="blocked_slots",
    )
    start_at = models.DateTimeField(help_text="Slot start instant in aware UTC.")
    end_at = models.DateTimeField(help_text="Slot end instant in aware UTC.")
    reason = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Optional owner-private reason (never exposed publicly).",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_blocked_slots",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_at__gt=models.F("start_at")),
                name="blocked_slot_end_after_start",
            ),
            models.UniqueConstraint(
                fields=["table_pin", "start_at"],
                name="unique_blocked_slot_pin_start",
            ),
        ]
        indexes = [
            models.Index(fields=["table_pin", "start_at"], name="idx_blocked_slot_pin_start"),
        ]
        ordering = ["start_at"]

    @property
    def pin_id(self) -> int:
        return self.table_pin_id

    @property
    def jalali_start_at(self) -> str:
        """Jalali presentation of start_at (ARCH-006)."""
        return format_jalali(self.start_at)

    def __str__(self) -> str:
        return f"BlockedSlot #{self.pk or 'new'} - {self.table_pin} @ {self.jalali_start_at}"
