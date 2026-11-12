"""Django Ninja router for the bookings app (Task T-013).

Mounted centrally in config/api.py under /api/v1/bookings.
Views stay thin (Architecture Spec section 14 & ARCH-001):
- authenticate via auth bridge
- validate via schemas.py
- call services.py
- return typed schemas
Never write raw ORM queries or perform mutations directly in views.
"""
from __future__ import annotations

from ninja import Router
from ninja.responses import Status

from apps.accounts.auth import auth
from apps.bookings import services
from apps.bookings.schemas import BookingInitiateIn, BookingInitiateOut

router = Router(tags=["bookings"])


@router.post(
    "/initiate/",
    response={201: BookingInitiateOut},
    auth=auth,
    summary="Initiate booking lock",
)
def initiate_booking_endpoint(request, payload: BookingInitiateIn):
    """Initiate a 10-minute temporary booking lock on a table pin and slot (TD-004).

    Views stay thin (ARCH-001): authenticate, validate via schemas,
    delegate to services.py, map domain errors.
    """
    booking = services.initiate_booking(
        user=request.auth,
        table_pin_id=payload.table_pin_id,
        slot_date=payload.slot_date,
        slot_start_time=payload.slot_start_time,
        venue_id=payload.venue_id,
        addon_ids=payload.addon_ids,
    )
    return Status(201, booking)
