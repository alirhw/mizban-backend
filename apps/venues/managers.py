"""Domain QuerySets for venues (Architecture Spec section 11)."""
from django.db import models
from django.utils import timezone


class VenueQuerySet(models.QuerySet):
    """Query helpers for the Venue model.

    Public visibility is BR-005: a venue may be listed and booked only
    when a platform admin has approved it AND its subscription is
    active (at least one VenueSubscription with expires_at > now).
    Every public catalogue query must go through ``public()`` so the
    rule lives in one place; the matching single-object check is
    ``Venue.has_active_subscription`` / ``Venue.is_publicly_visible``.
    """

    def public(self, now=None):
        current_time = now or timezone.now()
        return self.filter(
            is_approved=True,
            venue_subscriptions__starts_at__lte=current_time,
            venue_subscriptions__expires_at__gt=current_time,
        ).distinct()
