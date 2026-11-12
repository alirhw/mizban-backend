"""Factories for bookings app (Booking, BookingAddon)."""
from datetime import datetime, timedelta, timezone

import factory

from apps.bookings.models import Booking, BookingAddon, BookingStatus
from apps.panoramas.tests.factories import TablePinFactory
from apps.venues.tests.factories import DesignAddonFactory, UserFactory, VenueFactory


class BookingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Booking

    table_pin = factory.SubFactory(TablePinFactory)
    venue = factory.LazyAttribute(lambda o: o.table_pin.venue)
    customer = factory.SubFactory(UserFactory, role="CUSTOMER")
    status = BookingStatus.CONFIRMED

    start_at = factory.LazyFunction(
        lambda: datetime(2026, 1, 10, 15, 30, tzinfo=timezone.utc)
    )
    end_at = factory.LazyAttribute(lambda o: o.start_at + timedelta(minutes=90))
    amount_online_toman = 50_000
    amount_in_person_toman = 0


class BookingAddonFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = BookingAddon

    booking = factory.SubFactory(BookingFactory)
    design_addon = factory.SubFactory(DesignAddonFactory)
    price_snapshot_toman = factory.LazyAttribute(lambda o: o.design_addon.fee)
