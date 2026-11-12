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

    venue = factory.SubFactory(VenueFactory)
    space = factory.SubFactory(SpaceFactory, venue=factory.SelfAttribute("..venue"))
    table_number = factory.Sequence(lambda n: f"T{n}")
    capacity = 4
    is_active = True
