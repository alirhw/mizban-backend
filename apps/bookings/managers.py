"""Domain QuerySets for bookings (Architecture Spec section 11)."""
from django.db import models
from django.utils import timezone


class BookingQuerySet(models.QuerySet):
    """Query helpers for the Booking model (lands in T-011).

    A slot counts as taken when a booking is CONFIRMED, or is still
    inside its 10-minute PENDING_PAYMENT lock window (TD-004). This
    queryset is what the lock service checks - inside a transaction,
    with select_for_update(), never from cache (ARCH-004).
    """

    def active_locks_for_interval(self, table_pin_id, start_at, end_at, now=None):
        """Return active CONFIRMED or unexpired PENDING_PAYMENT bookings overlapping [start_at, end_at)."""
        if now is None:
            now = timezone.now()
        return self.filter(
            table_pin_id=table_pin_id,
            start_at__lt=end_at,
            end_at__gt=start_at,
        ).filter(
            models.Q(status="CONFIRMED")
            | models.Q(status="PENDING_PAYMENT", lock_expires_at__gt=now)
        )
