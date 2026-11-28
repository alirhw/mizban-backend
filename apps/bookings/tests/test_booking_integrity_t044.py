"""Reproduction and integrity tests for booking initiation (Task T-044)."""
from __future__ import annotations

import json
from datetime import time, timedelta

import pytest
from django.core.cache import cache
from django.test import Client
from django.utils import timezone as dj_timezone

from apps.accounts.models import UserRole
from apps.bookings.models import Booking
from apps.bookings.services import create_booking_lock
from apps.panoramas.tests.factories import SpaceFactory, TablePinFactory
from apps.venues.models import OperatingHours
from apps.venues.tests.factories import (
    DesignAddonFactory,
    UserFactory,
    VenueFactory,
    activate_test_subscription,
)
from core.exceptions import SlotAlreadyReservedError
from core.jalali import TEHRAN
from core.testing import authenticate_client

pytestmark = [
    pytest.mark.django_db,
]


@pytest.fixture(autouse=True)
def _clear_cache(settings):
    settings.DEBUG = True
    cache.clear()
    yield
    cache.clear()


def _future_bookable_date_and_hours(venue):
    now_tehran = dj_timezone.now().astimezone(TEHRAN)
    target_date = (now_tehran + timedelta(days=3)).date()
    OperatingHours.objects.create(
        venue=venue,
        weekday=target_date.weekday(),
        open_time=time(10, 0),
        close_time=time(16, 0),
    )
    return target_date


def _post_initiate(client: Client, user, payload: dict):
    authenticate_client(client, user)
    return client.post(
        "/api/v1/bookings/initiate/",
        data=json.dumps(payload),
        content_type="application/json",
    )


def test_overlapping_booking_intervals_rejected_on_same_table():
    """B1a: Overlapping intervals (10:15-11:45 and 10:30-12:00) on the same pin must conflict."""
    pin = TablePinFactory()
    now = dj_timezone.now()
    target_date = (now.astimezone(TEHRAN) + timedelta(days=3)).date()
    user_a = UserFactory(role=UserRole.CUSTOMER)
    user_b = UserFactory(role=UserRole.CUSTOMER)

    first = create_booking_lock(
        user=user_a,
        table_pin=pin,
        slot_date=target_date,
        slot_start_time=time(10, 15),
        now=now,
    )
    assert first.pk is not None

    with pytest.raises(SlotAlreadyReservedError):
        create_booking_lock(
            user=user_b,
            table_pin=pin,
            slot_date=target_date,
            slot_start_time=time(10, 30),
            now=now,
        )


def test_initiate_booking_rejects_venue_with_no_operating_hours():
    """B1b: An approved + subscribed venue with no operating hours is not bookable (400 INVALID_SLOT)."""
    venue = VenueFactory(is_approved=True)
    activate_test_subscription(venue)
    space = SpaceFactory(venue=venue, is_active=True)
    pin = TablePinFactory(venue=venue, space=space, is_active=True)
    venue.operating_hours.all().delete()
    assert not venue.operating_hours.exists()
    customer = UserFactory(role=UserRole.CUSTOMER)
    target_date = (dj_timezone.now().astimezone(TEHRAN) + timedelta(days=3)).date()

    client = Client()
    res = _post_initiate(
        client,
        customer,
        {
            "table_pin_id": pin.pk,
            "slot_date": target_date.isoformat(),
            "slot_start_time": "10:00",
            "addon_ids": [],
        },
    )
    assert res.status_code == 400
    assert res.json()["error_code"] == "INVALID_SLOT"
    assert Booking.objects.count() == 0


def test_initiate_booking_rejects_deactivated_space_and_allows_active_space():
    """M2: A deactivated space's pin returns 400 TABLE_NOT_BOOKABLE; an active space's pin books."""
    venue = VenueFactory(is_approved=True)
    activate_test_subscription(venue)
    target_date = _future_bookable_date_and_hours(venue)

    inactive_space = SpaceFactory(venue=venue, is_active=True)
    inactive_pin = TablePinFactory(venue=venue, space=inactive_space, is_active=True)
    inactive_space.deactivate()

    active_space = SpaceFactory(venue=venue, is_active=True)
    active_pin = TablePinFactory(venue=venue, space=active_space, is_active=True)

    customer = UserFactory(role=UserRole.CUSTOMER)
    client = Client()

    res_inactive = _post_initiate(
        client,
        customer,
        {
            "table_pin_id": inactive_pin.pk,
            "slot_date": target_date.isoformat(),
            "slot_start_time": "10:00",
            "addon_ids": [],
        },
    )
    assert res_inactive.status_code == 400
    assert res_inactive.json()["error_code"] == "TABLE_NOT_BOOKABLE"
    assert Booking.objects.count() == 0

    res_active = _post_initiate(
        client,
        customer,
        {
            "table_pin_id": active_pin.pk,
            "slot_date": target_date.isoformat(),
            "slot_start_time": "10:00",
            "addon_ids": [],
        },
    )
    assert res_active.status_code == 201


def test_initiate_booking_rejects_invalid_other_venue_and_inactive_addon_ids():
    """m13: Nonexistent, other-venue, and inactive addon IDs return 400 without creating a Booking."""
    venue_a = VenueFactory(is_approved=True)
    activate_test_subscription(venue_a)
    target_date = _future_bookable_date_and_hours(venue_a)
    space_a = SpaceFactory(venue=venue_a, is_active=True)
    pin_a = TablePinFactory(venue=venue_a, space=space_a, is_active=True)

    other_venue = VenueFactory(is_approved=True)
    other_addon = DesignAddonFactory(venue=other_venue, fee=50_000, is_active=True)
    inactive_addon = DesignAddonFactory(venue=venue_a, fee=40_000, is_active=False)
    valid_addon = DesignAddonFactory(venue=venue_a, fee=60_000, is_active=True)

    customer = UserFactory(role=UserRole.CUSTOMER)
    client = Client()

    for bad_addon_id in [999_999, other_addon.pk, inactive_addon.pk]:
        res = _post_initiate(
            client,
            customer,
            {
                "table_pin_id": pin_a.pk,
                "slot_date": target_date.isoformat(),
                "slot_start_time": "10:00",
                "addon_ids": [bad_addon_id],
            },
        )
        assert res.status_code == 400
        assert res.json()["error_code"] == "INVALID_ADDON"
        assert Booking.objects.count() == 0

    ok_res = _post_initiate(
        client,
        customer,
        {
            "table_pin_id": pin_a.pk,
            "slot_date": target_date.isoformat(),
            "slot_start_time": "10:00",
            "addon_ids": [valid_addon.pk],
        },
    )
    assert ok_res.status_code == 201
    assert ok_res.json()["amount_in_person_toman"] == 60_000


def test_expired_overlapping_lock_does_not_block_new_booking():
    """REQ-LOCK-005 + B1a: An expired off-grid lock is marked EXPIRED and does not block an overlapping slot."""
    from apps.bookings.models import BookingStatus

    pin = TablePinFactory()
    now = dj_timezone.now()
    target_date = (now.astimezone(TEHRAN) + timedelta(days=3)).date()
    user_a = UserFactory(role=UserRole.CUSTOMER)
    user_b = UserFactory(role=UserRole.CUSTOMER)

    expired_lock = create_booking_lock(
        user=user_a,
        table_pin=pin,
        slot_date=target_date,
        slot_start_time=time(10, 15),
        now=now,
    )
    later = now + timedelta(minutes=11)
    new_lock = create_booking_lock(
        user=user_b,
        table_pin=pin,
        slot_date=target_date,
        slot_start_time=time(10, 30),
        now=later,
    )
    expired_lock.refresh_from_db()
    assert expired_lock.status == BookingStatus.EXPIRED
    assert new_lock.status == BookingStatus.PENDING_PAYMENT
