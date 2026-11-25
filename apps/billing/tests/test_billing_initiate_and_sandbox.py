"""Integration tests for POST /api/v1/billing/initiate/ and dev-only sandbox page (Task T-028-PRE)."""
from __future__ import annotations

from datetime import timedelta
import json
import uuid

import pytest
from django.test import Client, override_settings
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.venues.tests.factories import UserFactory
from apps.billing.models import PaymentStatus, PaymentTransaction
from apps.bookings.models import BookingStatus
from apps.bookings.tests.factories import BookingFactory

pytestmark = pytest.mark.django_db


def _pending_booking(customer=None, amount_online_toman: int = 85_000):
    now = timezone.now()
    customer = customer or UserFactory(role=UserRole.CUSTOMER)
    return BookingFactory(
        customer=customer,
        status=BookingStatus.PENDING_PAYMENT,
        amount_online_toman=amount_online_toman,
        amount_in_person_toman=0,
        locked_at=now,
        lock_expires_at=now + timedelta(minutes=10),
    )


class TestPaymentInitiateEndpoint:
    def test_initiate_happy_path(self):
        customer = UserFactory(role=UserRole.CUSTOMER)
        booking = _pending_booking(customer=customer, amount_online_toman=85_000)

        client = Client()
        client.force_login(customer)
        resp = client.post(
            "/api/v1/billing/initiate/",
            data=json.dumps(
                {
                    "booking_id": booking.id,
                    "idempotency_key": f"idem-{uuid.uuid4().hex}",
                    "callback_url": "http://127.0.0.1:3000/bookings/callback",
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["booking_id"] == booking.id
        assert data["amount_toman"] == 85_000
        assert data["currency"] == "TOMAN"
        assert data["status"] == PaymentStatus.PENDING
        assert data["provider_name"] == "sandbox"
        assert data["provider_reference"].startswith("SBX-")
        assert data["redirect_url"].startswith(
            f"http://127.0.0.1:8001/billing/sandbox/pay/{data['provider_reference']}/"
        )

    def test_unauthenticated_returns_401(self):
        booking = _pending_booking()
        client = Client()
        resp = client.post(
            "/api/v1/billing/initiate/",
            data=json.dumps(
                {
                    "booking_id": booking.id,
                    "idempotency_key": f"idem-{uuid.uuid4().hex}",
                    "callback_url": "http://127.0.0.1:3000/cb",
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 401

    def test_non_owner_returns_403(self):
        owner = UserFactory(role=UserRole.CUSTOMER)
        other = UserFactory(role=UserRole.CUSTOMER)
        booking = _pending_booking(customer=owner)

        client = Client()
        client.force_login(other)
        resp = client.post(
            "/api/v1/billing/initiate/",
            data=json.dumps(
                {
                    "booking_id": booking.id,
                    "idempotency_key": f"idem-{uuid.uuid4().hex}",
                    "callback_url": "http://127.0.0.1:3000/cb",
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_non_customer_returns_403(self):
        venue_owner = UserFactory(role=UserRole.VENUE_OWNER)
        booking = _pending_booking()

        client = Client()
        client.force_login(venue_owner)
        resp = client.post(
            "/api/v1/billing/initiate/",
            data=json.dumps(
                {
                    "booking_id": booking.id,
                    "idempotency_key": f"idem-{uuid.uuid4().hex}",
                    "callback_url": "http://127.0.0.1:3000/cb",
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_unknown_booking_returns_404(self):
        customer = UserFactory(role=UserRole.CUSTOMER)
        client = Client()
        client.force_login(customer)
        resp = client.post(
            "/api/v1/billing/initiate/",
            data=json.dumps(
                {
                    "booking_id": 9999999,
                    "idempotency_key": f"idem-{uuid.uuid4().hex}",
                    "callback_url": "http://127.0.0.1:3000/cb",
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_non_payable_booking_status_returns_domain_error(self):
        customer = UserFactory(role=UserRole.CUSTOMER)
        booking = BookingFactory(
            customer=customer,
            status=BookingStatus.CONFIRMED,
            amount_online_toman=85_000,
        )
        client = Client()
        client.force_login(customer)
        resp = client.post(
            "/api/v1/billing/initiate/",
            data=json.dumps(
                {
                    "booking_id": booking.id,
                    "idempotency_key": f"idem-{uuid.uuid4().hex}",
                    "callback_url": "http://127.0.0.1:3000/cb",
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert resp.json()["error_code"] == "INVALID_STATUS_TRANSITION"

    def test_idempotent_reinitiate_returns_same_transaction(self):
        customer = UserFactory(role=UserRole.CUSTOMER)
        booking = _pending_booking(customer=customer)
        key = f"idem-{uuid.uuid4().hex}"
        payload = json.dumps(
            {
                "booking_id": booking.id,
                "idempotency_key": key,
                "callback_url": "http://127.0.0.1:3000/cb",
            }
        )

        client = Client()
        client.force_login(customer)
        r1 = client.post("/api/v1/billing/initiate/", data=payload, content_type="application/json")
        r2 = client.post("/api/v1/billing/initiate/", data=payload, content_type="application/json")

        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["transaction_id"] == r2.json()["transaction_id"]
        assert PaymentTransaction.objects.filter(idempotency_key=key).count() == 1

    def test_tampered_amount_is_rejected_and_ignored(self):
        customer = UserFactory(role=UserRole.CUSTOMER)
        booking = _pending_booking(customer=customer, amount_online_toman=85_000)

        client = Client()
        client.force_login(customer)
        resp = client.post(
            "/api/v1/billing/initiate/",
            data=json.dumps(
                {
                    "booking_id": booking.id,
                    "idempotency_key": f"idem-{uuid.uuid4().hex}",
                    "callback_url": "http://127.0.0.1:3000/cb",
                    "amount_toman": 1,
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 422
        assert PaymentTransaction.objects.filter(booking=booking).count() == 0


class TestDevSandboxPayView:
    def _initiate(self, client: Client, customer, booking, callback_url: str = "http://127.0.0.1:3000/bookings/callback"):
        client.force_login(customer)
        resp = client.post(
            "/api/v1/billing/initiate/",
            data=json.dumps(
                {
                    "booking_id": booking.id,
                    "idempotency_key": f"idem-{uuid.uuid4().hex}",
                    "callback_url": callback_url,
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 201
        return resp.json()

    @override_settings(DEBUG=True)
    def test_sandbox_page_renders_when_debug_true(self):
        customer = UserFactory(role=UserRole.CUSTOMER)
        booking = _pending_booking(customer=customer, amount_online_toman=95_000)
        client = Client()
        data = self._initiate(client, customer, booking)

        resp = client.get(f"/billing/sandbox/pay/{data['provider_reference']}/")
        assert resp.status_code == 200
        html = resp.content.decode("utf-8")
        assert "صفحه‌ی آزمایشی درگاه — فقط محیط توسعه" in html
        assert "پرداخت موفق (تست)" in html
        assert "پرداخت ناموفق (تست)" in html
        assert "95000" in html

    @override_settings(DEBUG=False)
    def test_sandbox_page_returns_404_when_debug_false(self):
        customer = UserFactory(role=UserRole.CUSTOMER)
        booking = _pending_booking(customer=customer)
        client = Client()
        data = self._initiate(client, customer, booking)

        resp = client.get(f"/billing/sandbox/pay/{data['provider_reference']}/")
        assert resp.status_code == 404

    @override_settings(DEBUG=True)
    def test_sandbox_success_confirms_booking_and_unlocks_receipt(self):
        customer = UserFactory(role=UserRole.CUSTOMER)
        booking = _pending_booking(customer=customer, amount_online_toman=95_000)
        client = Client()
        data = self._initiate(client, customer, booking)
        authority = data["provider_reference"]

        cb_resp = client.get(
            "/api/v1/billing/callback/",
            data={
                "authority": authority,
                "outcome": "success",
                "callback_url": "http://127.0.0.1:3000/bookings/callback",
            },
            HTTP_ACCEPT="text/html",
        )
        assert cb_resp.status_code == 302
        assert "booking_status=CONFIRMED" in cb_resp["Location"]
        assert "payment_status=SUCCESS" in cb_resp["Location"]

        booking.refresh_from_db()
        assert booking.status == BookingStatus.CONFIRMED

        receipt_resp = client.get(f"/api/v1/bookings/{booking.id}/receipt/")
        assert receipt_resp.status_code == 200
        assert receipt_resp.json()["total_online_toman"] == 95_000

    @override_settings(DEBUG=True)
    def test_sandbox_fail_marks_payment_failed_and_keeps_booking_pending(self):
        customer = UserFactory(role=UserRole.CUSTOMER)
        booking = _pending_booking(customer=customer, amount_online_toman=95_000)
        client = Client()
        data = self._initiate(client, customer, booking)
        authority = data["provider_reference"]

        cb_resp = client.get(
            "/api/v1/billing/callback/",
            data={"authority": authority, "outcome": "fail"},
        )
        assert cb_resp.status_code == 200
        cb_data = cb_resp.json()
        assert cb_data["payment_status"] == PaymentStatus.FAILED
        assert cb_data["booking_status"] == BookingStatus.PENDING_PAYMENT

        booking.refresh_from_db()
        assert booking.status == BookingStatus.PENDING_PAYMENT

    @override_settings(DEBUG=True)
    def test_unknown_authority_returns_404(self):
        client = Client()
        resp = client.get("/billing/sandbox/pay/SBX-UNKNOWN000000000/")
        assert resp.status_code == 404

    @override_settings(DEBUG=True)
    def test_non_sandbox_provider_returns_404(self):
        customer = UserFactory(role=UserRole.CUSTOMER)
        booking = _pending_booking(customer=customer)
        tx = PaymentTransaction.objects.create(
            booking=booking,
            customer=customer,
            amount_toman=booking.amount_online_toman,
            currency="TOMAN",
            status=PaymentStatus.PENDING,
            provider_name="zarinpal",
            provider_reference="ZRN-1234567890",
            idempotency_key=f"idem-{uuid.uuid4().hex}",
        )
        client = Client()
        resp = client.get(f"/billing/sandbox/pay/{tx.provider_reference}/")
        assert resp.status_code == 404

    @override_settings(DEBUG=True)
    def test_debug_callback_ignores_crafted_foreign_callback_url(self):
        customer = UserFactory(role=UserRole.CUSTOMER)
        booking = _pending_booking(customer=customer, amount_online_toman=95_000)
        client = Client()
        data = self._initiate(
            client,
            customer,
            booking,
            callback_url="http://127.0.0.1:3000/bookings/callback",
        )
        authority = data["provider_reference"]

        cb_resp = client.get(
            "/api/v1/billing/callback/",
            data={
                "authority": authority,
                "outcome": "success",
                "callback_url": "https://evil.example/steal",
            },
            HTTP_ACCEPT="text/html",
        )
        assert cb_resp.status_code == 302
        assert cb_resp["Location"].startswith("http://127.0.0.1:3000/bookings/callback?")
        assert "evil.example" not in cb_resp["Location"]

    @override_settings(DEBUG=True)
    def test_debug_callback_blocks_unlisted_foreign_url_when_none_stored(self):
        customer = UserFactory(role=UserRole.CUSTOMER)
        booking = _pending_booking(customer=customer, amount_online_toman=95_000)
        tx = PaymentTransaction.objects.create(
            booking=booking,
            customer=customer,
            amount_toman=booking.amount_online_toman,
            currency="TOMAN",
            status=PaymentStatus.PENDING,
            provider_name="sandbox",
            provider_reference=f"SBX-{uuid.uuid4().hex[:16].upper()}",
            idempotency_key=f"idem-{uuid.uuid4().hex}",
        )
        client = Client()
        cb_resp = client.get(
            "/api/v1/billing/callback/",
            data={
                "authority": tx.provider_reference,
                "outcome": "success",
                "callback_url": "https://evil.example/steal",
            },
            HTTP_ACCEPT="text/html",
        )
        assert cb_resp.status_code == 200
        assert cb_resp.json()["booking_status"] == BookingStatus.CONFIRMED
