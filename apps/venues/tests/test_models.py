"""Model and constraint tests for the venue catalogue (task T-008).

These tests assert DATABASE-level invariants (unique/check/unique
together), not just model clean() behaviour - per the T-008 spec:
"relying only on model clean()" is a listed mistake.
"""
import datetime

import pytest
from django.db import IntegrityError, transaction

from apps.venues.models import OperatingHours, SubscriptionStatus, Venue

from .factories import (
    DesignAddonFactory,
    OperatingHoursFactory,
    SubscriptionFactory,
    VenueFactory,
    activate_test_subscription,
)

pytestmark = pytest.mark.django_db


def test_venue_slug_is_unique():
    VenueFactory(slug="cafe-diba")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            VenueFactory(slug="cafe-diba")


def test_design_addon_negative_fee_violates_check_constraint():
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            DesignAddonFactory(fee=-1)


def test_design_addon_zero_fee_is_allowed():
    addon = DesignAddonFactory(fee=0)
    assert addon.fee == 0


def test_operating_hours_unique_per_venue_and_weekday():
    venue = VenueFactory()
    OperatingHoursFactory(venue=venue, weekday=OperatingHours.Weekday.SATURDAY)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            OperatingHoursFactory(venue=venue, weekday=OperatingHours.Weekday.SATURDAY)


def test_operating_hours_same_weekday_allowed_for_different_venues():
    OperatingHoursFactory(weekday=OperatingHours.Weekday.FRIDAY)
    OperatingHoursFactory(weekday=OperatingHours.Weekday.FRIDAY)
    assert OperatingHours.objects.filter(weekday=OperatingHours.Weekday.FRIDAY).count() == 2


def test_operating_hours_may_cross_midnight():
    hours = OperatingHoursFactory(
        open_time=datetime.time(18, 0),
        close_time=datetime.time(2, 0),
    )
    assert hours.close_time < hours.open_time
    assert hours.crosses_midnight is True


@pytest.mark.parametrize(
    ("is_approved", "subscription_status", "expected_public"),
    [
        (True, SubscriptionStatus.ACTIVE, True),
        (True, SubscriptionStatus.INACTIVE, False),
        (True, SubscriptionStatus.EXPIRED, False),
        (False, SubscriptionStatus.ACTIVE, False),
        (False, SubscriptionStatus.INACTIVE, False),
        (False, SubscriptionStatus.EXPIRED, False),
    ],
)
def test_public_visibility_rule_br005(is_approved, subscription_status, expected_public):
    venue = VenueFactory(
        is_approved=is_approved,
        subscription_status=subscription_status,
    )
    if subscription_status == SubscriptionStatus.ACTIVE:
        activate_test_subscription(venue)
    assert venue.is_publicly_visible is expected_public
    assert Venue.objects.public().filter(pk=venue.pk).exists() is expected_public


def test_subscription_defaults_to_inactive():
    subscription = SubscriptionFactory()
    assert subscription.status == SubscriptionStatus.INACTIVE
    assert subscription.started_at is None
    assert subscription.expires_at is None
