"""PostgreSQL integration tests for the admin financial report (Task T-040 / FR-40 / UC-10)."""
from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import User, UserRole
from apps.billing.models import PaymentStatus, PaymentTransaction
from apps.billing.tests.factories import PaymentTransactionFactory
from apps.bookings.models import Booking
from apps.bookings.tests.factories import BookingFactory
from apps.venues.tests.factories import UserFactory
from apps.wallets.models import Wallet, WalletTransaction, WalletTransactionType
from apps.wallets.tests.factories import WalletFactory, WalletTransactionFactory
from core.jalali import TEHRAN

pytestmark = pytest.mark.django_db

REPORT_URL = "/api/v1/billing/admin/financial-report/"


def _make_user(**kwargs: Any) -> User:
    return cast(User, UserFactory(**kwargs))


def _make_booking(**kwargs: Any) -> Booking:
    return cast(Booking, BookingFactory(**kwargs))


def _make_payment(**kwargs: Any) -> PaymentTransaction:
    return cast(PaymentTransaction, PaymentTransactionFactory(**kwargs))


def _make_wallet(**kwargs: Any) -> Wallet:
    return cast(Wallet, WalletFactory(**kwargs))


def _make_wallet_tx(**kwargs: Any) -> WalletTransaction:
    return cast(WalletTransaction, WalletTransactionFactory(**kwargs))


def _admin_client() -> tuple[Client, User]:
    admin = _make_user(role=UserRole.ADMIN)
    client = Client()
    client.force_login(admin)
    return client, admin


def test_admin_financial_report_returns_200_with_all_sections() -> None:
    client, _ = _admin_client()

    resp = client.get(REPORT_URL)

    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {"payments", "wallet", "subscriptions"}
    assert set(data["payments"].keys()) == {"total_toman", "count", "counts_by_status", "rows"}
    assert set(data["wallet"].keys()) == {
        "total_credit_toman",
        "total_debit_toman",
        "count",
        "rows",
    }
    assert data["subscriptions"] == {"total_toman": 0, "count": 0, "rows": []}


def test_admin_financial_report_totals_count_success_only() -> None:
    client, _ = _admin_client()
    PaymentTransactionFactory(status=PaymentStatus.SUCCESS, amount_toman=100_000)
    PaymentTransactionFactory(status=PaymentStatus.SUCCESS, amount_toman=150_000)
    PaymentTransactionFactory(status=PaymentStatus.FAILED, amount_toman=200_000)
    PaymentTransactionFactory(status=PaymentStatus.PENDING, amount_toman=300_000)

    resp = client.get(REPORT_URL)

    assert resp.status_code == 200
    payments = resp.json()["payments"]
    assert payments["total_toman"] == 250_000
    assert payments["count"] == 4
    assert payments["counts_by_status"] == {
        PaymentStatus.INITIATED: 0,
        PaymentStatus.PENDING: 1,
        PaymentStatus.SUCCESS: 2,
        PaymentStatus.FAILED: 1,
        PaymentStatus.TIMEOUT: 0,
    }


def test_admin_financial_report_totals_cover_full_filtered_set_not_page() -> None:
    client, _ = _admin_client()
    PaymentTransactionFactory(status=PaymentStatus.SUCCESS, amount_toman=100_000)
    PaymentTransactionFactory(status=PaymentStatus.SUCCESS, amount_toman=200_000)
    PaymentTransactionFactory(status=PaymentStatus.SUCCESS, amount_toman=300_000)

    resp = client.get(REPORT_URL, {"limit": 1})

    assert resp.status_code == 200
    payments = resp.json()["payments"]
    assert payments["total_toman"] == 600_000
    assert payments["count"] == 3
    assert len(payments["rows"]) == 1


def test_admin_financial_report_date_filter_tehran_boundary() -> None:
    client, _ = _admin_client()
    tx_2330_tehran = _make_payment(status=PaymentStatus.SUCCESS, amount_toman=120_000)
    tx_2359_tehran = _make_payment(status=PaymentStatus.SUCCESS, amount_toman=80_000)
    tx_0000_next_tehran = _make_payment(status=PaymentStatus.SUCCESS, amount_toman=50_000)

    PaymentTransaction.objects.filter(pk=tx_2330_tehran.pk).update(
        created_at=datetime(2026, 11, 26, 23, 30, tzinfo=TEHRAN).astimezone(UTC)
    )
    PaymentTransaction.objects.filter(pk=tx_2359_tehran.pk).update(
        created_at=datetime(2026, 11, 26, 20, 29, 59, tzinfo=UTC)
    )
    PaymentTransaction.objects.filter(pk=tx_0000_next_tehran.pk).update(
        created_at=datetime(2026, 11, 26, 20, 30, 0, tzinfo=UTC)
    )

    nov26_resp = client.get(REPORT_URL, {"to_date": "2026-11-26"})
    assert nov26_resp.status_code == 200
    nov26_payments = nov26_resp.json()["payments"]
    assert nov26_payments["total_toman"] == 200_000
    assert nov26_payments["count"] == 2
    assert {row["id"] for row in nov26_payments["rows"]} == {
        tx_2330_tehran.pk,
        tx_2359_tehran.pk,
    }

    nov25_resp = client.get(REPORT_URL, {"to_date": "2026-11-25"})
    assert nov25_resp.status_code == 200
    nov25_payments = nov25_resp.json()["payments"]
    assert nov25_payments["total_toman"] == 0
    assert nov25_payments["count"] == 0
    assert nov25_payments["rows"] == []

    nov27_resp = client.get(REPORT_URL, {"from_date": "2026-11-27"})
    assert nov27_resp.status_code == 200
    nov27_payments = nov27_resp.json()["payments"]
    assert nov27_payments["total_toman"] == 50_000
    assert nov27_payments["count"] == 1
    assert [row["id"] for row in nov27_payments["rows"]] == [tx_0000_next_tehran.pk]


def test_admin_financial_report_missing_date_bounds_return_full_set() -> None:
    client, _ = _admin_client()
    older = _make_payment(status=PaymentStatus.SUCCESS, amount_toman=80_000)
    recent = _make_payment(status=PaymentStatus.SUCCESS, amount_toman=120_000)
    PaymentTransaction.objects.filter(pk=older.pk).update(
        created_at=datetime(2025, 1, 15, 10, 0, tzinfo=UTC)
    )
    PaymentTransaction.objects.filter(pk=recent.pk).update(
        created_at=timezone.now() - timedelta(minutes=5)
    )

    missing_to = client.get(REPORT_URL, {"from_date": "2025-01-01"})
    assert missing_to.status_code == 200
    assert missing_to.json()["payments"]["total_toman"] == 200_000
    assert missing_to.json()["payments"]["count"] == 2

    today_tehran = timezone.now().astimezone(TEHRAN).date().isoformat()
    missing_from = client.get(REPORT_URL, {"to_date": today_tehran})
    assert missing_from.status_code == 200
    assert missing_from.json()["payments"]["total_toman"] == 200_000
    assert missing_from.json()["payments"]["count"] == 2


def test_admin_financial_report_invalid_date_params_return_422() -> None:
    client, _ = _admin_client()

    slash_resp = client.get(REPORT_URL, {"from_date": "2026/11/26"})
    assert slash_resp.status_code == 422

    garbage_resp = client.get(REPORT_URL, {"to_date": "not-a-date"})
    assert garbage_resp.status_code == 422

    inverted_resp = client.get(
        REPORT_URL,
        {"from_date": "2026-11-27", "to_date": "2026-11-26"},
    )
    assert inverted_resp.status_code == 422


def test_admin_financial_report_payment_status_filter_preserves_success_total() -> None:
    client, _ = _admin_client()
    PaymentTransactionFactory(status=PaymentStatus.SUCCESS, amount_toman=100_000)
    failed_tx = _make_payment(status=PaymentStatus.FAILED, amount_toman=50_000)
    PaymentTransactionFactory(status=PaymentStatus.PENDING, amount_toman=25_000)

    resp = client.get(REPORT_URL, {"payment_status": PaymentStatus.FAILED})

    assert resp.status_code == 200
    payments = resp.json()["payments"]
    assert payments["total_toman"] == 100_000
    assert payments["count"] == 1
    assert [row["id"] for row in payments["rows"]] == [failed_tx.pk]
    assert payments["rows"][0]["status"] == PaymentStatus.FAILED
    assert payments["counts_by_status"] == {
        PaymentStatus.INITIATED: 0,
        PaymentStatus.PENDING: 1,
        PaymentStatus.SUCCESS: 1,
        PaymentStatus.FAILED: 1,
        PaymentStatus.TIMEOUT: 0,
    }


def test_admin_financial_report_wallet_totals_and_newest_first_order() -> None:
    client, _ = _admin_client()
    wallet = _make_wallet()
    base_time = timezone.now() - timedelta(hours=3)

    tx1 = _make_wallet_tx(
        wallet=wallet,
        type=WalletTransactionType.CREDIT,
        amount_toman=200_000,
        balance_after_toman=200_000,
    )
    tx2 = _make_wallet_tx(
        wallet=wallet,
        type=WalletTransactionType.DEBIT,
        amount_toman=75_000,
        balance_after_toman=125_000,
    )
    tx3 = _make_wallet_tx(
        wallet=wallet,
        type=WalletTransactionType.CREDIT,
        amount_toman=100_000,
        balance_after_toman=225_000,
    )

    WalletTransaction.objects.filter(pk=tx1.pk).update(created_at=base_time)
    WalletTransaction.objects.filter(pk=tx2.pk).update(created_at=base_time + timedelta(minutes=10))
    WalletTransaction.objects.filter(pk=tx3.pk).update(created_at=base_time + timedelta(minutes=20))

    resp = client.get(REPORT_URL)

    assert resp.status_code == 200
    wallet_data = resp.json()["wallet"]
    assert wallet_data["total_credit_toman"] == 300_000
    assert wallet_data["total_debit_toman"] == 75_000
    assert wallet_data["count"] == 3
    assert [row["id"] for row in wallet_data["rows"]] == [tx3.pk, tx2.pk, tx1.pk]


def test_admin_financial_report_role_authorization() -> None:
    anon_client = Client()
    assert anon_client.get(REPORT_URL).status_code == 401

    for non_admin_user in (
        _make_user(role=UserRole.CUSTOMER),
        _make_user(role=UserRole.VENUE_OWNER),
        _make_user(role=UserRole.CUSTOMER, is_staff=True),
    ):
        client = Client()
        client.force_login(non_admin_user)
        assert client.get(REPORT_URL).status_code == 403

    admin_client, _ = _admin_client()
    assert admin_client.get(REPORT_URL).status_code == 200


def test_admin_financial_report_privacy_excludes_pii_and_card_fields() -> None:
    client, _ = _admin_client()
    customer = _make_user(role=UserRole.CUSTOMER, phone="09123334455")
    booking = _make_booking(customer=customer)
    _make_payment(
        booking=booking,
        customer=customer,
        status=PaymentStatus.SUCCESS,
        amount_toman=90_000,
        card_pan_masked="6037-99**-****-1234",
        tracking_code="TRK-SECRET-999",
    )
    wallet = _make_wallet(user=customer)
    _make_wallet_tx(wallet=wallet, booking=booking, reason="Booking payment")

    resp = client.get(REPORT_URL)

    assert resp.status_code == 200
    raw_body = resp.content.decode("utf-8")
    for forbidden in (
        "09123334455",
        "6037-99**-****-1234",
        "TRK-SECRET-999",
        "card_pan_masked",
        "tracking_code",
        "phone",
        "email",
    ):
        assert forbidden not in raw_body

    assert re.search(r"09\d{9}", raw_body) is None
    assert re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", raw_body) is None

    data = resp.json()
    assert set(data["payments"]["rows"][0].keys()) == {
        "id",
        "booking_id",
        "customer_id",
        "provider_name",
        "amount_toman",
        "status",
        "created_at",
    }
    assert set(data["wallet"]["rows"][0].keys()) == {
        "id",
        "user_id",
        "type",
        "amount_toman",
        "balance_after_toman",
        "reason",
        "booking_id",
        "created_at",
    }


def test_admin_financial_report_pagination_and_limit_clamping() -> None:
    client, _ = _admin_client()
    customer = _make_user(role=UserRole.CUSTOMER)
    booking = _make_booking(customer=customer)
    wallet = _make_wallet(user=customer)

    pay_objs = [
        PaymentTransaction(
            booking=booking,
            customer=customer,
            amount_toman=10_000,
            status=PaymentStatus.SUCCESS,
            provider_name="sandbox",
            provider_reference=f"SBX-{uuid.uuid4().hex[:16].upper()}",
            idempotency_key=f"pay-{i}-{uuid.uuid4().hex}",
        )
        for i in range(105)
    ]
    created_payments = PaymentTransaction.objects.bulk_create(pay_objs)

    wallet_objs = [
        WalletTransaction(
            wallet=wallet,
            type=WalletTransactionType.CREDIT,
            amount_toman=1_000,
            balance_after_toman=(i + 1) * 1_000,
            reason="Bulk credit",
            idempotency_key=f"wtx-{i}-{uuid.uuid4().hex}",
        )
        for i in range(105)
    ]
    created_wallet_txs = WalletTransaction.objects.bulk_create(wallet_objs)

    clamped_resp = client.get(REPORT_URL, {"limit": 150})
    assert clamped_resp.status_code == 200
    clamped_data = clamped_resp.json()
    assert clamped_data["payments"]["count"] == 105
    assert len(clamped_data["payments"]["rows"]) == 100
    assert clamped_data["wallet"]["count"] == 105
    assert len(clamped_data["wallet"]["rows"]) == 100

    paged_resp = client.get(REPORT_URL, {"limit": 2, "offset": 2})
    assert paged_resp.status_code == 200
    paged_data = paged_resp.json()

    expected_pay_ids = [
        tx.pk
        for tx in sorted(created_payments, key=lambda t: (t.created_at, t.pk), reverse=True)[2:4]
    ]
    expected_wallet_ids = [
        tx.pk
        for tx in sorted(created_wallet_txs, key=lambda t: (t.created_at, t.pk), reverse=True)[2:4]
    ]
    assert [row["id"] for row in paged_data["payments"]["rows"]] == expected_pay_ids
    assert [row["id"] for row in paged_data["wallet"]["rows"]] == expected_wallet_ids


def test_admin_financial_report_includes_wallet_paid_success_payments() -> None:
    client, _ = _admin_client()
    PaymentTransactionFactory(
        status=PaymentStatus.SUCCESS,
        provider_name="sandbox",
        amount_toman=100_000,
    )
    PaymentTransactionFactory(
        status=PaymentStatus.SUCCESS,
        provider_name="wallet",
        provider_reference=None,
        redirect_url="",
        amount_toman=150_000,
    )

    resp = client.get(REPORT_URL)

    assert resp.status_code == 200
    payments = resp.json()["payments"]
    assert payments["total_toman"] == 250_000
    assert payments["count"] == 2
    assert {row["provider_name"] for row in payments["rows"]} == {"sandbox", "wallet"}


def test_admin_financial_report_unknown_payment_status_returns_422() -> None:
    client, _ = _admin_client()

    resp = client.get(REPORT_URL, {"payment_status": "BOGUS"})

    assert resp.status_code == 422


def test_admin_financial_report_invalid_calendar_date_triggers_value_error_422() -> None:
    client, _ = _admin_client()

    resp = client.get(REPORT_URL, {"from_date": "2026-02-31"})

    assert resp.status_code == 422
