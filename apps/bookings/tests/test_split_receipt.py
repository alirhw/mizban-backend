"""Tests for read-only split receipt service and API endpoint (Task T-024 / BR-003 / ARCH-005).

Covers:
1. Happy path with add-ons: online section = amount_online_toman, in-person lines match
   BookingAddon snapshots and sum to amount_in_person_toman, grand_total_toman = online + in-person,
   header includes venue/table/UTC/Jalali fields.
2. Booking without add-ons: empty in-person items list, total_in_person_toman = 0,
   grand_total_toman = total_online_toman.
3. Snapshot integrity: raising DesignAddon.fee after booking does NOT change the receipt.
4. Consistency guard: corrupting stored Booking.amount_in_person_toman raises
   ReceiptDataInconsistencyError (HTTP 500, error_code=RECEIPT_DATA_INCONSISTENCY).
5. Availability: INITIATED, PENDING_PAYMENT, EXPIRED, CANCELLED return 409 RECEIPT_NOT_AVAILABLE;
   CONFIRMED and COMPLETED return 200.
6. Payment display & safety: exposes only provider_name and card_pan_masked from SUCCESS
   PaymentTransaction; asserts no full PAN, no provider_reference, no redirect_url,
   no idempotency_key, no tracking_code, no raw gateway payload in serialised response.
7. Payment display when no SUCCESS transaction exists: provider_name=None, card_pan_masked=None.
8. Authorization: unauthenticated -> 401; foreign customer -> 403; venue owner / staff -> 403;
   unknown booking -> 404.
9. Trailing-slash tolerance on /receipt/ and /receipt.
10. Bounded query count (no N+1) proven with django_assert_num_queries on PostgreSQL.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone
from pydantic import ValidationError as PydanticValidationError

from apps.billing.models import PaymentStatus, PaymentTransaction
from apps.bookings.models import Booking, BookingStatus
from apps.bookings.schemas import SplitReceiptOut
from apps.bookings.services import create_booking_lock, get_split_receipt
from apps.panoramas.tests.factories import TablePinFactory
from apps.venues.models import DesignAddon
from apps.venues.tests.factories import DesignAddonFactory, UserFactory
from core.exceptions import ReceiptDataInconsistencyError, ReceiptNotAvailableError
from core.testing import authenticate_client


@pytest.fixture(autouse=True)
def setup_test_env(settings):
    settings.DEBUG = True
    yield


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def customer():
    return UserFactory(role="CUSTOMER")


@pytest.fixture
def other_customer():
    return UserFactory(role="CUSTOMER")


@pytest.fixture
def pin():
    return TablePinFactory(reservation_fee_toman=65_000, table_number="VIP-07")


def _make_confirmed_booking_with_addons(
    *,
    customer,
    pin,
    addon_specs: Sequence[tuple[str, int]] = (),
    status: str = BookingStatus.CONFIRMED,
    with_success_payment: bool = True,
):
    """Create a booking via create_booking_lock (real snapshot path), optionally attach payment, and set status."""
    now = timezone.now()
    slot_dt = (now + timedelta(hours=48)).replace(minute=0, second=0, microsecond=0)
    addons = [
        DesignAddonFactory(venue=pin.venue, title=title, fee=fee, is_active=True)
        for title, fee in addon_specs
    ]
    booking = create_booking_lock(
        user=customer,
        table_pin=pin,
        slot_date=slot_dt.date(),
        slot_start_time=slot_dt.time(),
        addon_ids=[a.id for a in addons],
        now=now,
    )
    if status != BookingStatus.PENDING_PAYMENT:
        Booking.objects.filter(pk=booking.pk).update(status=status)
        booking.refresh_from_db()

    payment = None
    if with_success_payment:
        payment = PaymentTransaction.objects.create(
            booking=booking,
            customer=customer,
            amount_toman=booking.amount_online_toman,
            currency="TOMAN",
            status=PaymentStatus.SUCCESS,
            provider_name="sandbox",
            provider_reference=f"SBX-SECRET-REF-{booking.id}",
            idempotency_key=f"pay-idem-{booking.id}",
            redirect_url=f"https://sandbox.invalid/pay/SBX-SECRET-REF-{booking.id}",
            tracking_code=f"TRK-INTERNAL-{booking.id}",
            card_pan_masked="603799******1234",
            verified_at=now,
        )
    return booking, addons, payment


# ==============================================================================
# 1. Happy Path With Add-Ons
# ==============================================================================


@pytest.mark.django_db
def test_split_receipt_happy_path_with_addons(client, customer, pin):
    booking, addons, _payment = _make_confirmed_booking_with_addons(
        customer=customer,
        pin=pin,
        addon_specs=[
            ("Rose Bouquet", 120_000),
            ("Candle Table Setup", 85_000),
        ],
    )

    authenticate_client(client, customer)
    resp = client.get(
        f"/api/v1/bookings/{booking.id}/receipt/",
    )
    assert resp.status_code == 200
    data = resp.json()

    # Header fields (including Jalali presentation + aware UTC instants)
    assert data["booking_id"] == booking.id
    assert data["status"] == BookingStatus.CONFIRMED
    assert data["venue_name"] == pin.venue.name
    assert data["venue_slug"] == pin.venue.slug
    assert data["table_number"] == "VIP-07"
    assert data["jalali_date"] == booking.jalali_date
    assert data["jalali_start_datetime"] == booking.jalali_start_datetime
    assert data["jalali_end_datetime"] == booking.jalali_end_datetime
    assert data["start_at"] is not None
    assert data["end_at"] is not None

    # Section 1: Paid online (table fee only, 100% platform share)
    paid_online = data["paid_online"]
    assert paid_online["amount_online_toman"] == 65_000
    assert "online" in paid_online["label"].lower()
    assert paid_online["provider_name"] == "sandbox"
    assert paid_online["card_pan_masked"] == "603799******1234"

    # Section 2: Payable in person (itemised BookingAddon snapshots)
    in_person = data["payable_in_person"]
    assert "in person" in in_person["label"].lower()
    assert len(in_person["items"]) == 2
    items_by_title = {item["title"]: item for item in in_person["items"]}
    assert items_by_title["Rose Bouquet"]["unit_fee_toman"] == 120_000
    assert items_by_title["Rose Bouquet"]["line_total_toman"] == 120_000
    assert items_by_title["Candle Table Setup"]["unit_fee_toman"] == 85_000
    assert items_by_title["Candle Table Setup"]["line_total_toman"] == 85_000
    assert in_person["total_in_person_toman"] == 205_000

    # Totals
    assert data["total_online_toman"] == 65_000
    assert data["total_in_person_toman"] == 205_000
    assert data["grand_total_toman"] == 270_000


# ==============================================================================
# 2. Booking Without Add-Ons
# ==============================================================================


@pytest.mark.django_db
def test_split_receipt_without_addons(client, customer, pin):
    booking, _addons, _payment = _make_confirmed_booking_with_addons(
        customer=customer,
        pin=pin,
        addon_specs=[],
    )

    authenticate_client(client, customer)
    resp = client.get(
        f"/api/v1/bookings/{booking.id}/receipt/",
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["paid_online"]["amount_online_toman"] == 65_000
    assert data["payable_in_person"]["items"] == []
    assert data["payable_in_person"]["total_in_person_toman"] == 0
    assert data["total_online_toman"] == 65_000
    assert data["total_in_person_toman"] == 0
    assert data["grand_total_toman"] == 65_000


# ==============================================================================
# 3. Snapshot Integrity (DesignAddon price changes after booking)
# ==============================================================================


@pytest.mark.django_db
def test_split_receipt_snapshot_integrity_after_addon_price_change(client, customer, pin):
    booking, addons, _payment = _make_confirmed_booking_with_addons(
        customer=customer,
        pin=pin,
        addon_specs=[("Birthday Cake", 150_000)],
    )

    # Venue raises the DesignAddon fee after booking was confirmed
    DesignAddon.objects.filter(pk=addons[0].pk).update(fee=400_000)

    authenticate_client(client, customer)
    resp = client.get(
        f"/api/v1/bookings/{booking.id}/receipt/",
    )
    assert resp.status_code == 200
    data = resp.json()

    assert len(data["payable_in_person"]["items"]) == 1
    assert data["payable_in_person"]["items"][0]["unit_fee_toman"] == 150_000
    assert data["payable_in_person"]["items"][0]["line_total_toman"] == 150_000
    assert data["payable_in_person"]["total_in_person_toman"] == 150_000
    assert data["total_in_person_toman"] == 150_000
    assert data["grand_total_toman"] == 65_000 + 150_000


# ==============================================================================
# 4. Consistency Guard (Corrupted stored amount_in_person_toman)
# ==============================================================================


@pytest.mark.django_db
def test_split_receipt_consistency_guard_raises_domain_error_on_mismatch(client, customer, pin):
    booking, _addons, _payment = _make_confirmed_booking_with_addons(
        customer=customer,
        pin=pin,
        addon_specs=[("Flower Arch", 100_000)],
    )

    # Corrupt stored amount_in_person_toman so it disagrees with BookingAddon snapshot sum (100,000)
    Booking.objects.filter(pk=booking.pk).update(amount_in_person_toman=999_000)

    # Service-level check
    with pytest.raises(ReceiptDataInconsistencyError) as exc_info:
        get_split_receipt(booking.id, actor=customer)
    assert exc_info.value.error_code == "RECEIPT_DATA_INCONSISTENCY"
    assert exc_info.value.details["computed_in_person_toman"] == 100_000
    assert exc_info.value.details["stored_in_person_toman"] == 999_000

    # API-level check
    authenticate_client(client, customer)
    resp = client.get(
        f"/api/v1/bookings/{booking.id}/receipt/",
    )
    assert resp.status_code == 500
    body = resp.json()
    assert body["error_code"] == "RECEIPT_DATA_INCONSISTENCY"


# ==============================================================================
# 5. Availability Rules (CONFIRMED / COMPLETED vs non-settled statuses)
# ==============================================================================


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status",
    [
        BookingStatus.INITIATED,
        BookingStatus.PENDING_PAYMENT,
        BookingStatus.EXPIRED,
        BookingStatus.CANCELLED,
    ],
)
def test_split_receipt_unavailable_for_non_settled_statuses(client, customer, pin, status):
    booking, _addons, _payment = _make_confirmed_booking_with_addons(
        customer=customer,
        pin=pin,
        status=status,
        with_success_payment=False,
    )

    with pytest.raises(ReceiptNotAvailableError) as exc_info:
        get_split_receipt(booking.id, actor=customer)
    assert exc_info.value.error_code == "RECEIPT_NOT_AVAILABLE"
    assert exc_info.value.status_code == 409

    authenticate_client(client, customer)
    resp = client.get(
        f"/api/v1/bookings/{booking.id}/receipt/",
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "RECEIPT_NOT_AVAILABLE"


@pytest.mark.django_db
@pytest.mark.parametrize("status", [BookingStatus.CONFIRMED, BookingStatus.COMPLETED])
def test_split_receipt_available_for_confirmed_and_completed(client, customer, pin, status):
    booking, _addons, _payment = _make_confirmed_booking_with_addons(
        customer=customer,
        pin=pin,
        status=status,
    )

    authenticate_client(client, customer)
    resp = client.get(
        f"/api/v1/bookings/{booking.id}/receipt/",
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == status


# ==============================================================================
# 6. Payment Display & Data Safety (No Full PAN / No Raw Gateway Payload)
# ==============================================================================


@pytest.mark.django_db
def test_split_receipt_payment_display_exposes_only_safe_fields(client, customer, pin):
    booking, _addons, payment = _make_confirmed_booking_with_addons(
        customer=customer,
        pin=pin,
        with_success_payment=True,
    )
    # Also attach a FAILED transaction to verify only SUCCESS transaction is read
    PaymentTransaction.objects.create(
        booking=booking,
        customer=customer,
        amount_toman=booking.amount_online_toman,
        currency="TOMAN",
        status=PaymentStatus.FAILED,
        provider_name="other_failed_provider",
        provider_reference=f"SBX-FAILED-REF-{booking.id}",
        idempotency_key=f"pay-failed-{booking.id}",
        card_pan_masked="502229******9999",
        error_message="RAW_GATEWAY_DECLINE_PAYLOAD_SECRET",
    )

    authenticate_client(client, customer)
    resp = client.get(
        f"/api/v1/bookings/{booking.id}/receipt/",
    )
    assert resp.status_code == 200
    raw_text = resp.content.decode("utf-8")
    data = resp.json()

    # Exact safe fields exposed on paid_online
    assert set(data["paid_online"].keys()) == {
        "label",
        "description",
        "amount_online_toman",
        "provider_name",
        "card_pan_masked",
    }
    assert data["paid_online"]["provider_name"] == "sandbox"
    assert data["paid_online"]["card_pan_masked"] == "603799******1234"

    # Sensitive / internal gateway fields must NOT leak anywhere in the serialised body
    assert payment.provider_reference not in raw_text
    assert payment.redirect_url not in raw_text
    assert payment.idempotency_key not in raw_text
    assert payment.tracking_code not in raw_text
    assert "RAW_GATEWAY_DECLINE_PAYLOAD_SECRET" not in raw_text
    assert "other_failed_provider" not in raw_text
    assert "502229******9999" not in raw_text


@pytest.mark.django_db
def test_split_receipt_without_success_payment_returns_null_payment_fields(client, customer, pin):
    booking, _addons, _payment = _make_confirmed_booking_with_addons(
        customer=customer,
        pin=pin,
        with_success_payment=False,
    )

    authenticate_client(client, customer)
    resp = client.get(
        f"/api/v1/bookings/{booking.id}/receipt/",
    )
    assert resp.status_code == 200
    paid_online = resp.json()["paid_online"]
    assert paid_online["amount_online_toman"] == 65_000
    assert paid_online["provider_name"] is None
    assert paid_online["card_pan_masked"] is None


# ==============================================================================
# 7. Authorization & Not Found (401 / 403 / 404)
# ==============================================================================


@pytest.mark.django_db
def test_split_receipt_unauthenticated_returns_401(client, customer, pin):
    booking, _addons, _payment = _make_confirmed_booking_with_addons(
        customer=customer,
        pin=pin,
    )
    resp = client.get(f"/api/v1/bookings/{booking.id}/receipt/")
    assert resp.status_code == 401


@pytest.mark.django_db
def test_split_receipt_foreign_customer_returns_403(client, customer, other_customer, pin):
    booking, _addons, _payment = _make_confirmed_booking_with_addons(
        customer=customer,
        pin=pin,
    )
    authenticate_client(client, other_customer)
    resp = client.get(
        f"/api/v1/bookings/{booking.id}/receipt/",
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_split_receipt_venue_owner_and_staff_cannot_access_customer_receipt_403(client, customer, pin):
    booking, _addons, _payment = _make_confirmed_booking_with_addons(
        customer=customer,
        pin=pin,
    )
    # Venue owner
    authenticate_client(client, pin.venue.owner)
    resp_owner = client.get(
        f"/api/v1/bookings/{booking.id}/receipt/",
    )
    assert resp_owner.status_code == 403

    # Platform staff / admin
    staff_user = UserFactory(role="ADMIN", is_staff=True)
    authenticate_client(client, staff_user)
    resp_staff = client.get(
        f"/api/v1/bookings/{booking.id}/receipt/",
    )
    assert resp_staff.status_code == 403


@pytest.mark.django_db
def test_split_receipt_unknown_booking_returns_404(client, customer):
    authenticate_client(client, customer)
    resp = client.get(
        "/api/v1/bookings/999999/receipt/",
    )
    assert resp.status_code == 404


# ==============================================================================
# 8. Trailing-Slash Tolerance
# ==============================================================================


@pytest.mark.django_db
def test_split_receipt_trailing_slash_tolerance(client, customer, pin):
    booking, _addons, _payment = _make_confirmed_booking_with_addons(
        customer=customer,
        pin=pin,
    )
    authenticate_client(client, customer)
    resp_with_slash = client.get(
        f"/api/v1/bookings/{booking.id}/receipt/",
    )
    authenticate_client(client, customer)
    resp_without_slash = client.get(
        f"/api/v1/bookings/{booking.id}/receipt",
    )
    assert resp_with_slash.status_code == 200
    assert resp_without_slash.status_code == 200
    assert resp_with_slash.json() == resp_without_slash.json()


# ==============================================================================
# 9. Bounded Query Count (No N+1) on PostgreSQL
# ==============================================================================


@pytest.mark.django_db
def test_split_receipt_bounded_query_count_no_n_plus_one(
    client, customer, pin, django_assert_num_queries
):
    booking, _addons, _payment = _make_confirmed_booking_with_addons(
        customer=customer,
        pin=pin,
        addon_specs=[
            ("Addon 1", 10_000),
            ("Addon 2", 20_000),
            ("Addon 3", 30_000),
            ("Addon 4", 40_000),
            ("Addon 5", 50_000),
        ],
    )

    # Service call: 3 constant queries (Booking+Venue+TablePin, BookingAddon+DesignAddon, SUCCESS PaymentTransaction)
    with django_assert_num_queries(3):
        result = get_split_receipt(booking.id, actor=customer)
    assert len(result.payable_in_person.items) == 5
    assert result.total_in_person_toman == 150_000

    # HTTP endpoint: 5 constant queries (2 Django session/user auth queries + 3 bounded receipt queries)
    authenticate_client(client, customer)
    with django_assert_num_queries(5):
        resp = client.get(f"/api/v1/bookings/{booking.id}/receipt/")
    assert resp.status_code == 200
    assert len(resp.json()["payable_in_person"]["items"]) == 5


# ==============================================================================
# 10. Schema Strictness (extra="forbid")
# ==============================================================================


def test_split_receipt_schema_forbids_extra_fields():
    now = timezone.now()
    with pytest.raises(PydanticValidationError):
        SplitReceiptOut(
            booking_id=1,
            status="CONFIRMED",
            venue_name="Cafe Test",
            venue_slug="cafe-test",
            table_number="T1",
            start_at=now,
            end_at=now + timedelta(minutes=90),
            slot_date=now.date(),
            slot_start_time=now.time(),
            jalali_date="1405/01/01",
            jalali_start_datetime="1405/01/01 19:00",
            jalali_end_datetime="1405/01/01 20:30",
            paid_online={
                "label": "Paid online",
                "description": "Table fee",
                "amount_online_toman": 50_000,
            },
            payable_in_person={
                "label": "Payable in person",
                "items": [],
                "total_in_person_toman": 0,
            },
            total_online_toman=50_000,
            total_in_person_toman=0,
            grand_total_toman=50_000,
            unexpected_extra_field="should_fail",
        )
