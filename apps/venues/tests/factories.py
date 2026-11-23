"""Factories for venues tests (task T-008).

There is no shared UserFactory in apps/accounts/tests (its tests call
``User.objects.create_user`` directly), so a minimal one is defined
here for the venues suite. If a project-wide factory module appears
later, this should be replaced by an import from it.
"""
import factory
from django.contrib.auth import get_user_model

from apps.venues.models import (
    DesignAddon,
    OperatingHours,
    Subscription,
    SubscriptionPlan,
    Venue,
)

User = get_user_model()


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    phone = factory.Sequence(lambda n: f"0912000{n:04d}")
    role = "VENUE_OWNER"


class VenueFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Venue

    owner = factory.SubFactory(UserFactory)
    name = factory.Sequence(lambda n: f"Venue {n}")
    slug = factory.Sequence(lambda n: f"venue-{n}")
    city = "Tehran"
    venue_type = "CAFE"
    address = "1 Example Street"


class OperatingHoursFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OperatingHours

    venue = factory.SubFactory(VenueFactory)
    weekday = OperatingHours.Weekday.MONDAY
    open_time = "09:00"
    close_time = "23:00"


class DesignAddonFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DesignAddon

    venue = factory.SubFactory(VenueFactory)
    title = factory.Sequence(lambda n: f"Addon {n}")
    fee = 150_000


class SubscriptionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Subscription

    venue = factory.SubFactory(VenueFactory)
    plan_name = "Monthly"


class SubscriptionPlanFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SubscriptionPlan

    name = factory.Sequence(lambda n: f"Plan {n}")
    duration_days = 30
    price_toman = 500_000
    is_active = True


def activate_test_subscription(venue, *, duration_days=30, activated_by=None, note="", now=None):
    """Helper to activate a VenueSubscription via the real activation service in tests."""
    from apps.venues.services import activate_subscription

    admin_user = activated_by or UserFactory(role="ADMIN", is_staff=True)
    plan = SubscriptionPlanFactory(duration_days=duration_days)
    return activate_subscription(
        venue=venue,
        plan=plan,
        activated_by=admin_user,
        note=note,
        now=now,
    )
