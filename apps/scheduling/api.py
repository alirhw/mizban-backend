"""Django Ninja router for the scheduling app (Slot generation, lead-time rules, BlockedSlot).

Mounted centrally in config/api.py under /api/v1/scheduling.
Views stay thin (Architecture Spec section 14): authenticate, validate
via schemas.py, delegate to services.py, map domain errors.
"""
from __future__ import annotations

from typing import List, Optional

from django.shortcuts import get_object_or_404
from ninja import Query, Router
from ninja.responses import Status

from apps.accounts.auth import auth
from apps.panoramas.models import TablePin
from apps.scheduling import services
from apps.scheduling.schemas import BlockedSlotCreateIn, BlockedSlotOut, SlotOut
from apps.venues.models import Venue

router = Router(tags=["scheduling"])


@router.get("/venues/{venue_id}/slots", response=List[SlotOut], summary="Get venue slots for a date")
def get_slots(
    request,
    venue_id: int,
    date: str = Query(..., description="Target date (YYYY-MM-DD or Jalali YYYY/MM/DD)"),
    table_pin_id: Optional[int] = Query(
        None, description="Optional table pin ID to filter available slots for that table"
    ),
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


@router.post(
    "/pins/{pin_id}/blocked-slots/",
    response={201: BlockedSlotOut},
    auth=auth,
    summary="Block a single slot on a table pin (FR-011)",
)
@router.post(
    "/pins/{pin_id}/blocked-slots",
    response={201: BlockedSlotOut},
    auth=auth,
    summary="Block a single slot on a table pin (trailing-slash alias)",
    include_in_schema=False,
)
def create_blocked_slot_endpoint(request, pin_id: int, payload: BlockedSlotCreateIn):
    """Create an owner-manual slot block (returns 201 BlockedSlotOut)."""
    block = services.create_blocked_slot(
        user=request.auth,
        pin_id=pin_id,
        start_at=payload.start_at,
        reason=payload.reason,
    )
    return Status(201, block)


@router.get(
    "/pins/{pin_id}/blocked-slots/",
    response=List[BlockedSlotOut],
    auth=auth,
    summary="List upcoming blocked slots for a table pin (FR-011)",
)
@router.get(
    "/pins/{pin_id}/blocked-slots",
    response=List[BlockedSlotOut],
    auth=auth,
    summary="List upcoming blocked slots (trailing-slash alias)",
    include_in_schema=False,
)
def list_blocked_slots_endpoint(request, pin_id: int):
    """List upcoming blocked slots for an owner's table pin ordered by start_at."""
    return services.list_blocked_slots(user=request.auth, pin_id=pin_id)


@router.delete(
    "/blocked-slots/{block_id}/",
    response={204: None},
    auth=auth,
    summary="Unblock (hard-delete) a blocked slot (FR-011)",
)
@router.delete(
    "/blocked-slots/{block_id}",
    response={204: None},
    auth=auth,
    summary="Unblock a blocked slot (trailing-slash alias)",
    include_in_schema=False,
)
def delete_blocked_slot_endpoint(request, block_id: int):
    """Hard-delete a BlockedSlot owned by the caller."""
    services.delete_blocked_slot(user=request.auth, block_id=block_id)
    return Status(204, None)
