"""Targeted regression tests for core helpers and VenueAdmin actions (Task T-029)."""
from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest
from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory

from apps.accounts.models import UserRole
from apps.venues.admin import VenueAdmin
from apps.venues.models import Venue
from apps.venues.tests.factories import UserFactory, VenueFactory
from core.jalali import jalali_slot_window, parse_jalali_datetime, resolve_date, to_jalali
from core.utils import normalize_phone, utcnow

pytestmark = pytest.mark.django_db


def test_core_jalali_helpers_and_naive_guard():
    naive = datetime(2026, 11, 25, 10, 0)
    with pytest.raises(ValueError):
        to_jalali(naive)

    assert resolve_date(datetime(2026, 11, 25, 10, 0, tzinfo=UTC)) == date(2026, 11, 25)
    assert resolve_date(date(2026, 11, 25)) == date(2026, 11, 25)


def test_parse_jalali_datetime_returns_aware_utc():
    # 1405/09/04 12:30 Asia/Tehran (+03:30) == 2026-11-25 09:00 UTC
    utc_dt = parse_jalali_datetime("1405/09/04 12:30")
    assert utc_dt.tzinfo == UTC
    assert utc_dt == datetime(2026, 11, 25, 9, 0, tzinfo=UTC)


def test_jalali_slot_window_returns_tehran_day_utc_bounds():
    start, end = jalali_slot_window("1405/09/04")
    assert start.tzinfo == UTC
    assert end.tzinfo == UTC
    assert start == datetime(2026, 11, 24, 20, 30, tzinfo=UTC)
    assert end > start
    assert end.date() == date(2026, 11, 25)


def test_core_utils_utcnow_and_normalize_phone():
    now = utcnow()
    assert now.tzinfo is not None
    assert normalize_phone("00989123456789") == "09123456789"
    assert normalize_phone("989123456789") == "09123456789"


def test_venue_admin_display_save_delete_and_bulk_actions():
    admin_user = UserFactory(role=UserRole.ADMIN, is_staff=True)
    venue = VenueFactory(is_approved=False)
    site = AdminSite()
    model_admin = VenueAdmin(Venue, site)
    model_admin.message_user = MagicMock()
    req = RequestFactory().post("/admin/venues/venue/")
    req.user = admin_user

    assert model_admin.has_active_subscription_display(venue) is False

    model_admin.approve_selected_venues(req, Venue.objects.filter(pk=venue.pk))
    venue.refresh_from_db()
    assert venue.is_approved is True

    model_admin.reject_selected_venues(req, Venue.objects.filter(pk=venue.pk))
    venue.refresh_from_db()
    assert venue.is_approved is False

    venue.city = "شیراز"
    model_admin.save_model(req, venue, form=MagicMock(), change=True)
    venue.refresh_from_db()
    assert venue.city == "شیراز"

    model_admin.delete_model(req, venue)
    assert not Venue.objects.filter(pk=venue.pk).exists()
