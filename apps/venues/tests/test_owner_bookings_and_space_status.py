"""PostgreSQL tests for owner bookings list and SpaceOut.panorama_status (Task PH-06-02-PRE)."""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.bookings.models import BookingStatus
from apps.bookings.tests.factories import BookingFactory
from apps.panoramas.models import PanoramaImage, PanoramaStatus, Space
from apps.panoramas.tests.factories import TablePinFactory
from apps.venues.tests.factories import UserFactory, VenueFactory

pytestmark = pytest.mark.django_db


class TestOwnerVenueBookingsEndpoint:
    def test_owner_lists_own_bookings_with_masked_phone_and_nearest_first(self):
        owner = UserFactory(role=UserRole.VENUE_OWNER)
        venue = VenueFactory(owner=owner, is_approved=True)
        pin = TablePinFactory(venue=venue, table_number="T-12", reservation_fee_toman=75_000)

        customer = UserFactory(role=UserRole.CUSTOMER, phone="09123456789")
        now = timezone.now()
        later = BookingFactory(
            venue=venue,
            table_pin=pin,
            customer=customer,
            status=BookingStatus.CONFIRMED,
            start_at=now + timedelta(days=4),
            end_at=now + timedelta(days=4, hours=1, minutes=30),
            amount_online_toman=75_000,
            amount_in_person_toman=120_000,
        )
        sooner = BookingFactory(
            venue=venue,
            table_pin=pin,
            customer=customer,
            status=BookingStatus.PENDING_PAYMENT,
            start_at=now + timedelta(days=2),
            end_at=now + timedelta(days=2, hours=1, minutes=30),
            amount_online_toman=75_000,
            amount_in_person_toman=0,
        )

        client = Client()
        client.force_login(owner)
        resp = client.get(f"/api/v1/venues/owner/venues/{venue.id}/bookings/")
        assert resp.status_code == 200
        raw_body = resp.content.decode("utf-8")
        assert "09123456789" not in raw_body

        items = resp.json()
        assert len(items) == 2
        assert items[0]["booking_id"] == sooner.id
        assert items[1]["booking_id"] == later.id
        assert items[0]["customer_phone_masked"] is None
        assert items[1]["customer_phone_masked"] == "0912***789"
        assert items[0]["table_number"] == "T-12"
        assert items[0]["status"] == BookingStatus.PENDING_PAYMENT
        assert items[0]["amount_online_toman"] == 75_000
        assert items[0]["amount_in_person_toman"] == 0
        assert items[0]["jalali_date"] != ""
        assert items[0]["start_jalali"] != ""
        assert items[0]["end_jalali"] != ""

    def test_empty_venue_returns_empty_list(self):
        owner = UserFactory(role=UserRole.VENUE_OWNER)
        venue = VenueFactory(owner=owner)
        client = Client()
        client.force_login(owner)
        resp = client.get(f"/api/v1/venues/owner/venues/{venue.id}/bookings/")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_permissions_401_403_404(self):
        owner = UserFactory(role=UserRole.VENUE_OWNER)
        other_owner = UserFactory(role=UserRole.VENUE_OWNER)
        customer = UserFactory(role=UserRole.CUSTOMER)
        venue = VenueFactory(owner=owner)

        anon = Client()
        assert anon.get(f"/api/v1/venues/owner/venues/{venue.id}/bookings/").status_code == 401

        c_client = Client()
        c_client.force_login(customer)
        assert c_client.get(f"/api/v1/venues/owner/venues/{venue.id}/bookings/").status_code == 403

        o_client = Client()
        o_client.force_login(other_owner)
        assert o_client.get(f"/api/v1/venues/owner/venues/{venue.id}/bookings/").status_code == 403

        owner_client = Client()
        owner_client.force_login(owner)
        assert owner_client.get("/api/v1/venues/owner/venues/9999999/bookings/").status_code == 404

    def test_bounded_constant_query_count(self):
        owner = UserFactory(role=UserRole.VENUE_OWNER)
        venue = VenueFactory(owner=owner)
        pin = TablePinFactory(venue=venue)
        customer = UserFactory(role=UserRole.CUSTOMER)
        now = timezone.now()
        BookingFactory(
            venue=venue,
            table_pin=pin,
            customer=customer,
            start_at=now + timedelta(days=1),
            end_at=now + timedelta(days=1, hours=1, minutes=30),
        )

        client = Client()
        client.force_login(owner)
        with CaptureQueriesContext(connection) as ctx1:
            r1 = client.get(f"/api/v1/venues/owner/venues/{venue.id}/bookings/")
        assert r1.status_code == 200

        for idx in range(4):
            BookingFactory(
                venue=venue,
                table_pin=pin,
                customer=customer,
                start_at=now + timedelta(days=idx + 2),
                end_at=now + timedelta(days=idx + 2, hours=1, minutes=30),
            )

        with CaptureQueriesContext(connection) as ctx5:
            r5 = client.get(f"/api/v1/venues/owner/venues/{venue.id}/bookings/")
        assert r5.status_code == 200
        assert len(r5.json()) == 5
        assert len(ctx5) == len(ctx1)


class TestSpaceOutPanoramaStatus:
    def test_panorama_status_values_and_constant_queries(self):
        owner = UserFactory(role=UserRole.VENUE_OWNER)
        venue = VenueFactory(owner=owner, is_approved=True)

        Space.objects.create(venue=venue, name="No Pano", display_order=1, is_active=True)
        s_ready = Space.objects.create(venue=venue, name="Ready", display_order=2, is_active=True)
        p_ready = PanoramaImage.objects.create(
            id=uuid.uuid4(),
            space=s_ready,
            status=PanoramaStatus.READY,
        )
        s_ready.active_panorama = p_ready
        s_ready.save(update_fields=["active_panorama"])

        client = Client()
        client.force_login(owner)
        with CaptureQueriesContext(connection) as ctx2:
            r2 = client.get(f"/api/v1/venues/{venue.id}/spaces")
        assert r2.status_code == 200
        by_name = {item["name"]: item["panorama_status"] for item in r2.json()}
        assert by_name["No Pano"] is None
        assert by_name["Ready"] == PanoramaStatus.READY

        # Add PROCESSING and FAILED spaces -> query count must stay constant
        for name, st in [
            ("Proc", PanoramaStatus.PROCESSING),
            ("Fail", PanoramaStatus.FAILED),
            ("Up", PanoramaStatus.UPLOADED),
        ]:
            sp = Space.objects.create(venue=venue, name=name, display_order=3, is_active=True)
            pano = PanoramaImage.objects.create(id=uuid.uuid4(), space=sp, status=st)
            sp.active_panorama = pano
            sp.save(update_fields=["active_panorama"])

        with CaptureQueriesContext(connection) as ctx5:
            r5 = client.get(f"/api/v1/venues/{venue.id}/spaces")
        assert r5.status_code == 200
        by_name5 = {item["name"]: item["panorama_status"] for item in r5.json()}
        assert by_name5["Proc"] == PanoramaStatus.PROCESSING
        assert by_name5["Fail"] == PanoramaStatus.FAILED
        assert by_name5["Up"] == PanoramaStatus.UPLOADED
        assert len(ctx5) == len(ctx2)
