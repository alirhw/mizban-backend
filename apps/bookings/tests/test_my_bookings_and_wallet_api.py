"""PostgreSQL integration tests for GET /api/v1/bookings/my/ and GET /api/v1/wallets/me/ (PH-06-03-PRE)."""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.bookings.models import BookingStatus
from apps.bookings.tests.factories import BookingFactory
from apps.panoramas.tests.factories import TablePinFactory
from apps.venues.tests.factories import UserFactory, VenueFactory
from apps.wallets.models import Wallet
from apps.wallets.services import credit_wallet, debit_wallet, get_or_create_wallet_for_user

pytestmark = pytest.mark.django_db


class TestCustomerMyBookingsEndpoint:
    def test_lists_only_own_bookings_newest_first_with_pagination(self):
        customer_a = UserFactory(role=UserRole.CUSTOMER)
        customer_b = UserFactory(role=UserRole.CUSTOMER)
        venue = VenueFactory(is_approved=True)
        pin = TablePinFactory(venue=venue, table_number="M-1", reservation_fee_toman=90_000)

        now = timezone.now()
        b1 = BookingFactory(
            venue=venue,
            table_pin=pin,
            customer=customer_a,
            status=BookingStatus.CONFIRMED,
            start_at=now + timedelta(days=5),
            end_at=now + timedelta(days=5, hours=1, minutes=30),
            amount_online_toman=90_000,
            amount_in_person_toman=120_000,
        )
        b2 = BookingFactory(
            venue=venue,
            table_pin=pin,
            customer=customer_a,
            status=BookingStatus.PENDING_PAYMENT,
            start_at=now + timedelta(days=3),
            end_at=now + timedelta(days=3, hours=1, minutes=30),
            amount_online_toman=90_000,
            amount_in_person_toman=0,
        )
        b_other = BookingFactory(
            venue=venue,
            table_pin=pin,
            customer=customer_b,
            status=BookingStatus.CONFIRMED,
            start_at=now + timedelta(days=4),
            end_at=now + timedelta(days=4, hours=1, minutes=30),
        )

        client = Client()
        client.force_login(customer_a)
        resp = client.get("/api/v1/bookings/my/")
        assert resp.status_code == 200
        items = resp.json()
        ids = [item["booking_id"] for item in items]
        assert ids == [b2.id, b1.id]
        assert b_other.id not in ids
        assert items[0]["venue_name"] == venue.name
        assert items[0]["venue_slug"] == venue.slug
        assert items[0]["table_number"] == "M-1"
        assert items[0]["jalali_date"] != ""
        assert items[0]["start_jalali"] != ""
        assert items[0]["end_jalali"] != ""

        # Pagination limit & offset
        p1 = client.get("/api/v1/bookings/my/?limit=1&offset=0").json()
        p2 = client.get("/api/v1/bookings/my/?limit=1&offset=1").json()
        assert [p1[0]["booking_id"], p2[0]["booking_id"]] == [b2.id, b1.id]

    def test_permissions_401_and_403_for_venue_owner(self):
        owner = UserFactory(role=UserRole.VENUE_OWNER)
        anon = Client()
        assert anon.get("/api/v1/bookings/my/").status_code == 401

        o_client = Client()
        o_client.force_login(owner)
        assert o_client.get("/api/v1/bookings/my/").status_code == 403

    def test_cancel_eligibility_and_refund_matches_t023_for_all_statuses(self):
        customer = UserFactory(role=UserRole.CUSTOMER)
        venue = VenueFactory(is_approved=True)
        now = timezone.now()

        cases = [
            (BookingStatus.CONFIRMED, now + timedelta(hours=40), True, 80_000),
            (BookingStatus.CONFIRMED, now + timedelta(hours=20), False, 0),
            (BookingStatus.PENDING_PAYMENT, now + timedelta(hours=48), True, 0),
            (BookingStatus.CANCELLED, now + timedelta(hours=48), False, 0),
            (BookingStatus.EXPIRED, now + timedelta(hours=48), False, 0),
            (BookingStatus.COMPLETED, now - timedelta(hours=10), False, 0),
            (BookingStatus.INITIATED, now + timedelta(hours=48), False, 0),
        ]
        expected_by_id = {}
        for idx, (st, start_at, exp_can, exp_ref) in enumerate(cases):
            pin = TablePinFactory(venue=venue, table_number=f"T-{idx}", reservation_fee_toman=80_000)
            b = BookingFactory(
                venue=venue,
                table_pin=pin,
                customer=customer,
                status=st,
                start_at=start_at,
                end_at=start_at + timedelta(hours=1, minutes=30),
                amount_online_toman=80_000,
                amount_in_person_toman=50_000,
            )
            expected_by_id[b.id] = (exp_can, exp_ref)

        client = Client()
        client.force_login(customer)
        resp = client.get("/api/v1/bookings/my/")
        assert resp.status_code == 200
        for item in resp.json():
            exp_can, exp_ref = expected_by_id[item["booking_id"]]
            assert item["is_cancellable"] is exp_can
            assert item["cancel_refund_toman"] == exp_ref

    def test_bounded_constant_query_count(self):
        customer = UserFactory(role=UserRole.CUSTOMER)
        venue = VenueFactory(is_approved=True)
        pin = TablePinFactory(venue=venue)
        now = timezone.now()
        BookingFactory(
            venue=venue,
            table_pin=pin,
            customer=customer,
            start_at=now + timedelta(days=2),
            end_at=now + timedelta(days=2, hours=1, minutes=30),
        )

        client = Client()
        client.force_login(customer)
        with CaptureQueriesContext(connection) as ctx1:
            r1 = client.get("/api/v1/bookings/my/")
        assert r1.status_code == 200

        for idx in range(4):
            BookingFactory(
                venue=venue,
                table_pin=pin,
                customer=customer,
                start_at=now + timedelta(days=idx + 3),
                end_at=now + timedelta(days=idx + 3, hours=1, minutes=30),
            )

        with CaptureQueriesContext(connection) as ctx5:
            r5 = client.get("/api/v1/bookings/my/")
        assert r5.status_code == 200
        assert len(r5.json()) == 5
        assert len(ctx5) == len(ctx1)


class TestCustomerWalletEndpoint:
    def test_no_wallet_customer_returns_zero_without_creating_wallet(self):
        customer = UserFactory(role=UserRole.CUSTOMER)
        client = Client()
        client.force_login(customer)

        resp = client.get("/api/v1/wallets/me/")
        assert resp.status_code == 200
        assert resp.json() == {"balance_toman": 0, "entries": []}
        assert not Wallet.objects.filter(user=customer).exists()

    def test_permissions_401_and_403_for_venue_owner(self):
        owner = UserFactory(role=UserRole.VENUE_OWNER)
        assert Client().get("/api/v1/wallets/me/").status_code == 401

        o_client = Client()
        o_client.force_login(owner)
        assert o_client.get("/api/v1/wallets/me/").status_code == 403

    def test_wallet_balance_ledger_arithmetic_and_20_entry_bound(self):
        customer = UserFactory(role=UserRole.CUSTOMER)
        wallet = get_or_create_wallet_for_user(customer)

        for idx in range(24):
            credit_wallet(
                wallet,
                10_000,
                reason=f"Credit #{idx}",
                idempotency_key=f"c-{customer.id}-{idx}",
            )
        debit_wallet(
            wallet,
            40_000,
            reason="Debit test",
            idempotency_key=f"d-{customer.id}-1",
        )

        client = Client()
        client.force_login(customer)
        resp = client.get("/api/v1/wallets/me/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["balance_toman"] == 200_000  # 24 * 10,000 - 40,000
        assert len(data["entries"]) == 20
        assert data["entries"][0]["direction"] == "debit"
        assert data["entries"][0]["amount_toman"] == 40_000
        assert data["entries"][0]["jalali_date"] != ""
        assert data["entries"][1]["direction"] == "credit"

    def test_wallet_balance_matches_cancel_booking_wallet_balance_toman(self):
        customer = UserFactory(role=UserRole.CUSTOMER)
        venue = VenueFactory(is_approved=True)
        pin = TablePinFactory(venue=venue, reservation_fee_toman=125_000)
        now = timezone.now()
        booking = BookingFactory(
            venue=venue,
            table_pin=pin,
            customer=customer,
            status=BookingStatus.CONFIRMED,
            start_at=now + timedelta(hours=48),
            end_at=now + timedelta(hours=49, minutes=30),
            amount_online_toman=125_000,
            amount_in_person_toman=0,
        )

        client = Client()
        client.force_login(customer)
        cancel_resp = client.post(f"/api/v1/bookings/{booking.id}/cancel/")
        assert cancel_resp.status_code == 200
        cancel_data = cancel_resp.json()
        assert cancel_data["refunded_to_wallet_toman"] == 125_000

        wallet_resp = client.get("/api/v1/wallets/me/")
        assert wallet_resp.status_code == 200
        wallet_data = wallet_resp.json()
        assert wallet_data["balance_toman"] == cancel_data["wallet_balance_toman"] == 125_000
        assert len(wallet_data["entries"]) == 1
        assert wallet_data["entries"][0]["direction"] == "credit"
        assert wallet_data["entries"][0]["amount_toman"] == 125_000
