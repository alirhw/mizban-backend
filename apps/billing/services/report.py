"""Read-only admin financial reporting service (Task T-040 / FR-40 / UC-10)."""
from __future__ import annotations

import re
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.billing.models import PaymentStatus, PaymentTransaction
from apps.wallets.models import WalletTransaction, WalletTransactionType
from core.jalali import TEHRAN

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_iso_date(value: str | None, field_name: str) -> date | None:
    """Validate and parse a strict YYYY-MM-DD date string."""
    if value is None:
        return None
    if not isinstance(value, str) or not _ISO_DATE_RE.match(value):
        raise DjangoValidationError(
            {field_name: f"Invalid date format for {field_name}. Expected YYYY-MM-DD."}
        )
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DjangoValidationError(
            {field_name: f"Invalid calendar date for {field_name}."}
        ) from exc


def get_financial_report(
    admin_user: Any,
    *,
    from_date: str | None = None,
    to_date: str | None = None,
    payment_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Return read-only platform financial report for ADMIN users (FR-40, UC-10).

    - Enforces UserRole.ADMIN (is_staff alone does not qualify).
    - Converts Tehran local date bounds to a half-open UTC range once.
    - Computes all totals and counts in the database over the full filtered range.
    """
    if getattr(admin_user, "role", None) != UserRole.ADMIN:
        raise PermissionDenied("Only platform administrators can view the financial report.")

    if payment_status is not None and payment_status not in PaymentStatus.values:
        raise DjangoValidationError({"payment_status": "Invalid payment status."})

    parsed_from = _parse_iso_date(from_date, "from_date")
    parsed_to = _parse_iso_date(to_date, "to_date")
    if parsed_from is not None and parsed_to is not None and parsed_from > parsed_to:
        raise DjangoValidationError({"from_date": "from_date must not be after to_date."})

    start_utc = (
        datetime.combine(parsed_from, time.min, tzinfo=TEHRAN).astimezone(UTC)
        if parsed_from is not None
        else None
    )
    end_utc = (
        datetime.combine(parsed_to + timedelta(days=1), time.min, tzinfo=TEHRAN).astimezone(UTC)
        if parsed_to is not None
        else None
    )

    date_filters: dict[str, datetime] = {}
    if start_utc is not None:
        date_filters["created_at__gte"] = start_utc
    if end_utc is not None:
        date_filters["created_at__lt"] = end_utc
    else:
        date_filters["created_at__lte"] = timezone.now()

    clamped_limit = max(1, min(int(limit), 100))
    clamped_offset = max(0, int(offset))

    # Payments section (sums SUCCESS only; counts_by_status covers full date range)
    pay_range_qs = PaymentTransaction.objects.filter(**date_filters)
    total_toman = int(
        pay_range_qs.filter(status=PaymentStatus.SUCCESS).aggregate(
            total=Coalesce(Sum("amount_toman"), 0)
        )["total"]
        or 0
    )
    counts_by_status: dict[str, int] = {status: 0 for status in PaymentStatus.values}
    for row in pay_range_qs.values("status").annotate(cnt=Count("id")):
        counts_by_status[row["status"]] = int(row["cnt"])
    list_qs = (
        pay_range_qs.filter(status=payment_status)
        if payment_status is not None
        else pay_range_qs
    )
    pay_count = list_qs.count()
    pay_rows = list(
        list_qs.order_by("-created_at", "-id").values(
            "id",
            "booking_id",
            "customer_id",
            "provider_name",
            "amount_toman",
            "status",
            "created_at",
        )[clamped_offset : clamped_offset + clamped_limit]
    )

    # Wallet section
    wallet_range_qs = WalletTransaction.objects.filter(**date_filters)
    wallet_agg = wallet_range_qs.aggregate(
        total_credit=Coalesce(
            Sum("amount_toman", filter=Q(type=WalletTransactionType.CREDIT)), 0
        ),
        total_debit=Coalesce(
            Sum("amount_toman", filter=Q(type=WalletTransactionType.DEBIT)), 0
        ),
        total_count=Count("id"),
    )
    wallet_rows = [
        {
            "id": r["id"],
            "user_id": r["wallet__user_id"],
            "type": r["type"],
            "amount_toman": r["amount_toman"],
            "balance_after_toman": r["balance_after_toman"],
            "reason": r["reason"],
            "booking_id": r["booking_id"],
            "created_at": r["created_at"],
        }
        for r in wallet_range_qs.order_by("-created_at", "-id").values(
            "id",
            "wallet__user_id",
            "type",
            "amount_toman",
            "balance_after_toman",
            "reason",
            "booking_id",
            "created_at",
        )[clamped_offset : clamped_offset + clamped_limit]
    ]

    return {
        "payments": {
            "total_toman": total_toman,
            "count": pay_count,
            "counts_by_status": counts_by_status,
            "rows": pay_rows,
        },
        "wallet": {
            "total_credit_toman": int(wallet_agg["total_credit"] or 0),
            "total_debit_toman": int(wallet_agg["total_debit"] or 0),
            "count": int(wallet_agg["total_count"] or 0),
            "rows": wallet_rows,
        },
        "subscriptions": {
            "total_toman": 0,
            "count": 0,
            "rows": [],
        },
    }
