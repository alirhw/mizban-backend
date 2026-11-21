"""Factories for panoramas app (Space, PanoramaImage, TablePin)."""
import factory

from apps.panoramas.models import PanoramaImage, PanoramaStatus, Space, TablePin
from apps.venues.tests.factories import VenueFactory


class SpaceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Space

    venue = factory.SubFactory(VenueFactory)
    name = factory.Sequence(lambda n: f"Space {n}")
    description = factory.Sequence(lambda n: f"Description for space {n}")
    display_order = factory.Sequence(lambda n: n)
    is_active = True


class PanoramaImageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PanoramaImage

    space = factory.SubFactory(SpaceFactory)
    status = PanoramaStatus.UPLOADED
    width = 4096
    height = 2048
    file_size_bytes = 1024 * 1024 * 2


class TablePinFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TablePin
        skip_postgeneration_save = True

    venue = factory.SubFactory(VenueFactory)
    space = factory.SubFactory(SpaceFactory, venue=factory.SelfAttribute("..venue"))
    table_number = factory.Sequence(lambda n: f"T{n}")
    capacity = 4
    pitch = 10.5
    yaw = -45.0
    description = "Near the window"
    reservation_fee_toman = 50_000
    is_smoking = False
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
