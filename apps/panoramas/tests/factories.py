"""Factories for panoramas app (TablePin, Space)."""
import factory

from apps.panoramas.models import Space, TablePin
from apps.venues.tests.factories import VenueFactory


class SpaceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Space

    venue = factory.SubFactory(VenueFactory)
    name = factory.Sequence(lambda n: f"Space {n}")


class TablePinFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TablePin
        skip_postgeneration_save = True

    venue = factory.SubFactory(VenueFactory)
    space = factory.SubFactory(SpaceFactory, venue=factory.SelfAttribute("..venue"))
    table_number = factory.Sequence(lambda n: f"T{n}")
    capacity = 4
    is_active = True

    @factory.post_generation
    def operating_hours(obj, create, extracted, **kwargs):
        if not create:
            return
        from apps.venues.models import OperatingHours

        if not obj.venue.operating_hours.exists():
            for w in range(7):
                OperatingHours.objects.get_or_create(
                    venue=obj.venue,
                    weekday=w,
                    defaults={"open_time": "08:00", "close_time": "23:00"},
                )
