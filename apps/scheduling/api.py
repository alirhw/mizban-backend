"""Django Ninja router for the scheduling app (Slot generation, lead-time rules).

Mounted centrally in config/api.py under /api/v1/scheduling.
Views stay thin (Architecture Spec section 14): authenticate, validate
via schemas.py, delegate to services.py, map domain errors.
"""
from __future__ import annotations

from typing import List, Optional

from django.shortcuts import get_object_or_404
from ninja import Query, Router

from apps.panoramas.models import TablePin
from apps.scheduling import services
from apps.scheduling.schemas import SlotOut
from apps.venues.models import Venue

router = Router(tags=["scheduling"])


@router.get("/venues/{venue_id}/slots", response=List[SlotOut], summary="Get venue slots for a date")
def get_slots(
    request,
    venue_id: int,
    date: str = Query(..., description="Target date (YYYY-MM-DD or Jalali YYYY/MM/DD)"),
    table_pin_id: Optional[int] = Query(None, description="Optional table pin ID to filter available slots for that table"),
):
    """Retrieve 90-minute slots for a venue on the requested date.

    Slot availability is computed dynamically (BR-001 / BR-002) and is NEVER cached (ARCH-004).
    If table_pin_id is provided, filters available slots using the T-011 availability filter.
    """
    venue = get_object_or_404(Venue, pk=venue_id)
    table_pin = None
    if table_pin_id is not None:
        table_pin = get_object_or_404(TablePin, pk=table_pin_id, venue=venue)
    return services.get_venue_slots_for_date(venue, on_date=date, table_pin=table_pin)
