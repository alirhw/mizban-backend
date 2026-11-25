"""Dev-only HTML views for billing (Sandbox payment simulation page, T-028-PRE)."""
from __future__ import annotations

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from apps.billing.models import PaymentStatus, PaymentTransaction


def sandbox_pay_view(request: HttpRequest, authority: str) -> HttpResponse:
    """Render the dev-only sandbox payment simulation page.

    Strictly impossible in production: returns 404 whenever settings.DEBUG is False,
    for unknown/expired/non-pending authorities, or for any non-sandbox provider.
    """
    if not getattr(settings, "DEBUG", False):
        raise Http404("Sandbox payment page is disabled outside development.")

    tx = (
        PaymentTransaction.objects.select_related("booking", "booking__venue")
        .filter(provider_reference=authority)
        .first()
    )
    if not tx:
        raise Http404("Sandbox transaction not found.")

    if tx.provider_name != "sandbox":
        raise Http404("Sandbox payment page only supports the sandbox provider.")

    if tx.status != PaymentStatus.PENDING:
        raise Http404("Sandbox transaction is no longer pending.")

    now = timezone.now()
    if tx.booking.lock_expires_at and tx.booking.lock_expires_at <= now:
        raise Http404("Booking reservation lock has expired.")

    callback_url = request.GET.get("callback_url", "")

    return render(
        request,
        "billing/sandbox_pay.html",
        {
            "authority": authority,
            "booking_id": tx.booking_id,
            "venue_name": tx.booking.venue.name,
            "amount_toman": tx.amount_toman,
            "callback_url": callback_url,
        },
    )
