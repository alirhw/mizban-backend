"""Domain models for the bookings app (Booking, BookingAddon).

Task T-011:
- Booking model with status lifecycle:
  INITIATED -> PENDING_PAYMENT -> CONFIRMED / EXPIRED / CANCELLED -> COMPLETED
- FKs to venue, table_pin, customer.
- Start and end instants in UTC (ARCH-006).
- Partial unique constraints preventing double-booking active statuses (CONFIRMED, PENDING_PAYMENT).
- Indexes for query optimization.
- Jalali presentation helpers.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Any

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.bookings.managers import BookingQuerySet
from core.exceptions import InvalidStatusTransitionError
from core.jalali import TEHRAN, format_jalali


class BookingStatus(models.TextChoices):
    INITIATED = "INITIATED", "Initiated"
    PENDING_PAYMENT = "PENDING_PAYMENT", "Pending Payment"
    CONFIRMED = "CONFIRMED", "Confirmed"
    EXPIRED = "EXPIRED", "Expired"
    CANCELLED = "CANCELLED", "Cancelled"
    COMPLETED = "COMPLETED", "Completed"


# Valid state transitions (Architecture Spec section 7 & Spec 001)
VALID_TRANSITIONS: dict[str, set[str]] = {
    BookingStatus.INITIATED: {
        BookingStatus.PENDING_PAYMENT,
        BookingStatus.EXPIRED,
        BookingStatus.CANCELLED,
    },
    BookingStatus.PENDING_PAYMENT: {
        BookingStatus.CONFIRMED,
        BookingStatus.EXPIRED,
        BookingStatus.CANCELLED,
    },
    BookingStatus.CONFIRMED: {
        BookingStatus.CANCELLED,
        BookingStatus.COMPLETED,
    },
    BookingStatus.EXPIRED: {
        BookingStatus.CONFIRMED,  # Guarded transition for late payment confirmation when slot is free (ADR-006)
    },
    BookingStatus.CANCELLED: set(),
    BookingStatus.COMPLETED: set(),
}

ACTIVE_BOOKING_STATUSES = [
    BookingStatus.CONFIRMED,
    BookingStatus.PENDING_PAYMENT,
]


class Booking(models.Model):
    """A customer reservation for a specific table pin and slot."""

    venue = models.ForeignKey(
        "venues.Venue",
        on_delete=models.CASCADE,
        related_name="bookings",
    )
    table_pin = models.ForeignKey(
        "panoramas.TablePin",
        on_delete=models.PROTECT,
        related_name="bookings",
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bookings",
    )

    status = models.CharField(
        max_length=20,
        choices=BookingStatus.choices,
        default=BookingStatus.INITIATED,
        db_index=True,
    )

    # Time boundaries in aware UTC (ARCH-006)
    start_at = models.DateTimeField(help_text="Slot start in aware UTC.")
    end_at = models.DateTimeField(help_text="Slot end in aware UTC.")

    # Local convenience fields for query indexing and filtering
    slot_date = models.DateField(help_text="Local date of the slot in Asia/Tehran.")
    slot_start_time = models.TimeField(help_text="Local start time of the slot in Asia/Tehran.")

    # Concurrency lock metadata (TD-004)
    locked_at = models.DateTimeField(null=True, blank=True, help_text="Instant when lock was held.")
    lock_expires_at = models.DateTimeField(null=True, blank=True, help_text="Instant when lock expires (now + 10m).")

    # Financial snapshots in integer Toman (ARCH-005 / BR-003)
    amount_online_toman = models.BigIntegerField(
        default=0,
        help_text="Table reservation fee charged online through gateway (in Toman).",
    )
    amount_in_person_toman = models.BigIntegerField(
        default=0,
        help_text="Addon fees payable to the venue in person (in Toman).",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = BookingQuerySet.as_manager()

    class Meta:
        constraints = [
            # Partial unique constraint: cannot have two active (CONFIRMED or PENDING_PAYMENT)
            # bookings on the same table for the same slot start instant.
            models.UniqueConstraint(
                fields=["table_pin", "start_at"],
                condition=models.Q(status__in=ACTIVE_BOOKING_STATUSES),
                name="unique_active_booking_table_slot_start",
            ),
            models.UniqueConstraint(
                fields=["table_pin", "slot_date", "slot_start_time"],
                condition=models.Q(status__in=ACTIVE_BOOKING_STATUSES),
                name="unique_active_booking_table_date_time",
            ),
            models.CheckConstraint(
                condition=models.Q(end_at__gt=models.F("start_at")),
                name="booking_end_after_start",
            ),
            models.CheckConstraint(
                condition=models.Q(amount_online_toman__gte=0) & models.Q(amount_in_person_toman__gte=0),
                name="booking_amounts_non_negative",
            ),
        ]
        indexes = [
            models.Index(fields=["table_pin", "slot_date", "slot_start_time"], name="idx_book_pin_date_time"),
            models.Index(fields=["table_pin", "start_at"], name="idx_book_pin_start"),
            models.Index(fields=["customer", "-created_at"], name="idx_book_cust_created"),
            models.Index(fields=["venue", "slot_date"], name="idx_book_venue_date"),
            models.Index(fields=["status", "lock_expires_at"], name="idx_book_stat_exp"),
        ]
        ordering = ["-start_at"]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Support alias kwargs: 'user' for customer, 'table' for table_pin
        if "user" in kwargs and "customer" not in kwargs:
            kwargs["customer"] = kwargs.pop("user")
        if "table" in kwargs and "table_pin" not in kwargs:
            kwargs["table_pin"] = kwargs.pop("table")
        super().__init__(*args, **kwargs)

    # -------------------------------------------------------------------------
    # Compatibility aliases
    # -------------------------------------------------------------------------
    @property
    def user(self):
        return self.customer

    @user.setter
    def user(self, value):
        self.customer = value

    @property
    def table(self):
        return self.table_pin

    @table.setter
    def table(self, value):
        self.table_pin = value

    # -------------------------------------------------------------------------
    # State machine methods
    # -------------------------------------------------------------------------
    def can_transition_to(self, target_status: str | BookingStatus) -> bool:
        """Check if transition to target_status is valid according to state machine."""
        target = str(target_status)
        current = str(self.status)
        if current == target:
            return True
        allowed = VALID_TRANSITIONS.get(current, set())
        return target in allowed

    def transition_to(self, target_status: str | BookingStatus, save: bool = True) -> None:
        """Transition booking to a new status with validation."""
        target = str(target_status)
        if not self.can_transition_to(target):
            raise InvalidStatusTransitionError(
                f"Cannot transition booking from {self.status} to {target}.",
                details={"current_status": self.status, "target_status": target},
            )
        self.status = target
        if save and self.pk:
            self.save(update_fields=["status", "updated_at"])

    # -------------------------------------------------------------------------
    # Jalali presentation helpers (ARCH-006)
    # -------------------------------------------------------------------------
    @property
    def jalali_date(self) -> str:
        """Formatted Jalali date string, e.g. '1404/09/01'."""
        return format_jalali(self.start_at, fmt="%Y/%m/%d")

    @property
    def jalali_start_datetime(self) -> str:
        """Formatted Jalali start datetime, e.g. '1404/09/01 19:00'."""
        return format_jalali(self.start_at)

    @property
    def jalali_end_datetime(self) -> str:
        """Formatted Jalali end datetime, e.g. '1404/09/01 20:30'."""
        return format_jalali(self.end_at)

    # -------------------------------------------------------------------------
    # Synchronization & Auto-derivation
    # -------------------------------------------------------------------------
    def clean(self) -> None:
        super().clean()
        self._sync_instants_and_local_times()

    def save(self, *args: Any, **kwargs: Any) -> None:
        self._sync_instants_and_local_times()
        super().save(*args, **kwargs)

    def _sync_instants_and_local_times(self) -> None:
        # If venue is omitted but table_pin is provided, copy venue from table_pin
        if not getattr(self, "venue_id", None) and getattr(self, "table_pin_id", None):
            self.venue = self.table_pin.venue

        # If start_at is provided, derive local slot_date and slot_start_time
        if getattr(self, "start_at", None):
            local_dt = self.start_at.astimezone(TEHRAN)
            if not self.slot_date:
                self.slot_date = local_dt.date()
            if not self.slot_start_time:
                self.slot_start_time = local_dt.time()
            if not getattr(self, "end_at", None):
                self.end_at = self.start_at + timedelta(minutes=90)
        # Conversely, if slot_date & slot_start_time are provided without start_at
        elif self.slot_date and self.slot_start_time:
            local_dt = datetime.combine(self.slot_date, self.slot_start_time, tzinfo=TEHRAN)
            self.start_at = local_dt.astimezone(dt_timezone.utc)
            if not getattr(self, "end_at", None):
                self.end_at = self.start_at + timedelta(minutes=90)

    def __str__(self) -> str:
        return f"Booking #{self.pk or 'new'} - {self.table_pin} @ {self.jalali_start_datetime} ({self.status})"


class BookingAddon(models.Model):
    """An addon item snapshot attached to a booking (BR-003)."""

    booking = models.ForeignKey(
        Booking,
        on_delete=models.CASCADE,
        related_name="addons",
    )
    design_addon = models.ForeignKey(
        "venues.DesignAddon",
        on_delete=models.PROTECT,
        related_name="booking_addons",
    )
    price_snapshot_toman = models.BigIntegerField(
        help_text="Snapshot of the addon fee at booking time (in Toman). Payable in person.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["booking", "design_addon"]

    def __str__(self) -> str:
        return f"{self.booking} - {self.design_addon.title} ({self.price_snapshot_toman} Toman)"
