"""Domain QuerySets for venues (Architecture Spec section 11)."""
from django.db import models


class VenueQuerySet(models.QuerySet):
    """Query helpers for the Venue model.

    Public visibility is BR-005: a venue may be listed and booked only
    when a platform admin has approved it AND its subscription is
    active. Every public catalogue query must go through ``public()``
    so the rule lives in exactly one place (workflows in T-009 build
    on this; the matching single-object check is
    ``Venue.is_publicly_visible``).
    """

    def public(self):
        return self.filter(
            is_approved=True,
            subscription_status="ACTIVE",
        )
