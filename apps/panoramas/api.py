"""Django Ninja router for the panoramas app (Task T-016).

Mounted centrally in config/api.py under /api/v1/panoramas.
Views stay thin (Architecture Spec section 14 & ARCH-001):
- authenticate via auth bridge
- validate parameters
- delegate file validation, storage, and DB operations to services.py
- return typed schemas
Never perform raw ORM writes or heavy processing directly in views.
"""
from __future__ import annotations

from ninja import File, Router, UploadedFile
from ninja.errors import HttpError
from ninja.responses import Status

from apps.accounts.auth import auth
from apps.panoramas import services
from apps.panoramas.schemas import (
    PanoramaUploadOut,
    PublicPanoramaOut,
    SpaceCreateIn,
    SpaceOut,
    SpacePublicOut,
    SpaceUpdateIn,
    TablePinCreateIn,
    TablePinOut,
    TablePinUpdateIn,
)

router = Router(tags=["panoramas"])
spaces_router = Router(tags=["spaces"])
venue_spaces_router = Router(tags=["venue-spaces"])


@router.post(
    "/spaces/{space_id}/upload",
    response={202: PanoramaUploadOut},
    auth=auth,
    summary="Upload 360 panorama equirectangular image",
)
def upload_panorama_image(
    request,
    space_id: int,
    file: UploadedFile = File(...),
):
    """Upload a raw 360-degree panorama image for a space (Task T-016).

    Guarantees:
    - Authenticated venue owners only (and only for venues they own).
    - Enforces 20 MB size limit.
    - Validates magic bytes and verifies image with Pillow.
    - Stores file with generated UUID under media/panoramas/{venue_id}/{uuid}.<ext>.
    - Creates PanoramaImage in UPLOADED status.
    - Dispatches processing via transaction.on_commit seam.
    - Returns HTTP 202 Accepted.
    """
    panorama = services.upload_panorama_for_space(
        user=request.auth,
        space_id=space_id,
        file=file,
    )
    return Status(
        202,
        {
            "id": panorama.id,
            "space_id": panorama.space_id,
            "venue_id": panorama.space.venue.id,
            "status": panorama.status,
            "original_file": panorama.original_file.name if panorama.original_file else "",
            "file_size_bytes": panorama.file_size_bytes or 0,
            "width": panorama.width,
            "height": panorama.height,
            "created_at": panorama.created_at,
            "message": "Panorama image uploaded successfully and queued for processing.",
        },
    )


@router.post(
    "/spaces/{space_id}/images",
    response={202: PanoramaUploadOut},
    auth=auth,
    summary="Upload 360 panorama equirectangular image (alias)",
)
def upload_panorama_image_alias(
    request,
    space_id: int,
    file: UploadedFile = File(...),
):
    """Alias for /spaces/{space_id}/upload."""
    return upload_panorama_image(request, space_id=space_id, file=file)


# ==============================================================================
# Owner TablePin Endpoints (Task T-018)
# ==============================================================================

@router.post(
    "/spaces/{space_id}/pins",
    response={201: TablePinOut},
    auth=auth,
    summary="Create and place a table pin in a space (Owner)",
)
def create_table_pin(request, space_id: int, payload: TablePinCreateIn):
    """Create and place a table pin within a space (Task T-018).

    - Only accessible by venue owner (or admin).
    - pitch bounds: [-90.0, 90.0]
    - yaw bounds: [-180.0, 180.0]
    - capacity > 0
    - Venue derived server-side from space.venue.
    """
    pin = services.create_table_pin_for_space(user=request.auth, space_id=space_id, data=payload)
    return Status(201, pin)


@router.get(
    "/spaces/{space_id}/pins",
    response={200: list[TablePinOut]},
    auth=auth,
    summary="List all table pins in a space (Owner)",
)
def list_table_pins(request, space_id: int):
    """List all table pins in a space for the venue owner."""
    return services.list_table_pins_for_space(user=request.auth, space_id=space_id)


@router.get(
    "/pins/{pin_id}",
    response={200: TablePinOut},
    auth=auth,
    summary="Get table pin details (Owner)",
)
def get_table_pin(request, pin_id: int):
    """Retrieve details for a single table pin."""
    return services.get_table_pin(user=request.auth, pin_id=pin_id)


@router.put(
    "/pins/{pin_id}",
    response={200: TablePinOut},
    auth=auth,
    summary="Update table pin (Owner)",
)
def update_table_pin(request, pin_id: int, payload: TablePinUpdateIn):
    """Update coordinates, table number, capacity, or status of a table pin."""
    return services.update_table_pin(user=request.auth, pin_id=pin_id, data=payload)


@router.patch(
    "/pins/{pin_id}",
    response={200: TablePinOut},
    auth=auth,
    summary="Partial update table pin (Owner)",
)
def patch_table_pin(request, pin_id: int, payload: TablePinUpdateIn):
    """Partial update of table pin fields."""
    return services.update_table_pin(user=request.auth, pin_id=pin_id, data=payload)


@router.post(
    "/pins/{pin_id}/deactivate",
    response={200: TablePinOut},
    auth=auth,
    summary="Deactivate a table pin (Owner)",
)
def deactivate_table_pin(request, pin_id: int):
    """Soft-deactivate a table pin so it cannot be booked (ADR-005)."""
    return services.deactivate_table_pin(user=request.auth, pin_id=pin_id)


@router.delete(
    "/pins/{pin_id}",
    response={204: None},
    auth=auth,
    summary="Delete a table pin (Owner)",
)
def delete_table_pin(request, pin_id: int):
    """Delete a table pin (Task T-018).

    Guarded by T-015 / ADR-005 PROTECT rule:
    Pins with existing bookings cannot be deleted (returns 409 TABLE_PIN_PROTECTED).
    Pins without bookings are deleted cleanly (returns 204).
    """
    services.delete_table_pin(user=request.auth, pin_id=pin_id)
    return Status(204, None)


# ==============================================================================
# Public Panorama Read Endpoints (Task T-018 / BR-005)
# ==============================================================================

@router.get(
    "/spaces/{space_id}/panorama",
    response={200: PublicPanoramaOut},
    auth=None,
    summary="Get public 360 panorama and active pins for a space",
)
def get_public_panorama(request, space_id: int):
    """Public panorama scene and active pins (Task T-018 / BR-005).

    Returns 200 with WebP image URL and active pins if:
    - Venue is approved and subscription is ACTIVE
    - Space is active
    - A READY panorama image exists
    Otherwise returns 404 with zero info leak.
    """
    return services.get_public_panorama_for_space(space_id=space_id)


@spaces_router.get(
    "/{space_id}/panorama",
    response={200: PublicPanoramaOut},
    auth=None,
    summary="Get public 360 panorama and active pins for a space (direct /spaces route)",
)
def get_public_panorama_under_spaces(request, space_id: int):
    """Alias for /api/v1/spaces/{space_id}/panorama."""
    return services.get_public_panorama_for_space(space_id=space_id)


# ==============================================================================
# Space Endpoints (Task T-018b)
# ==============================================================================

# ------------------------------------------------------------------------------
# 1. Venue-scoped space routes (mounted under /api/v1/venues)
# ------------------------------------------------------------------------------

@venue_spaces_router.post(
    "/{identifier}/spaces",
    response={201: SpaceOut},
    auth=auth,
    summary="Create space for a venue (Owner)",
)
@venue_spaces_router.post(
    "/{identifier}/spaces/",
    response={201: SpaceOut},
    auth=auth,
    summary="Create space for a venue (Owner) (slash)",
    include_in_schema=False,
)
def create_space_endpoint(request, identifier: str, payload: SpaceCreateIn):
    """Create a new space for an owned venue (Task T-018b).

    Guarantees:
    - Authenticated venue owners only (and only for venues they own).
    - Rejects client-spoofed venue id.
    - Rejects extra fields and validates name non-empty and display_order >= 0.
    """
    if not identifier.isdigit():
        from django.http import Http404
        raise Http404("Venue not found.")
    venue_id = int(identifier)
    space = services.create_space_for_venue(
        user=request.auth,
        venue_id=venue_id,
        data=payload,
    )
    return Status(201, space)


@venue_spaces_router.get(
    "/{identifier}/spaces",
    response={200: list[SpaceOut]},
    auth=None,
    summary="List spaces for a venue (Owner or Public)",
)
@venue_spaces_router.get(
    "/{identifier}/spaces/",
    response={200: list[SpaceOut]},
    auth=None,
    summary="List spaces for a venue (Owner or Public) (slash)",
    include_in_schema=False,
)
def list_spaces_for_venue_endpoint(request, identifier: str):
    """List spaces for a venue (Task T-018b).

    Dual behavior:
    1. If identifier is an integer venue_id:
       - Requires authenticated venue owner/admin (401 unauthenticated, 403 foreign).
       - Returns all spaces (active and inactive) for that venue.
    2. If identifier is a slug:
       - Public endpoint gated by BR-005.
       - Returns active spaces only for approved venues with active subscription.
       - Otherwise returns 404 with zero info leak.
    """
    user = auth(request)
    if identifier.isdigit():
        if user is None:
            raise HttpError(401, "Unauthorized")
        return services.list_owner_spaces(user=user, venue_id=int(identifier))
    return services.list_public_spaces(slug=identifier)


# ------------------------------------------------------------------------------
# 2. Direct space routes (mounted under /api/v1/spaces)
# ------------------------------------------------------------------------------

@spaces_router.get(
    "/{space_id}",
    response={200: SpaceOut},
    auth=None,
    summary="Get space detail (Dual-purpose: Owner or Public under BR-005)",
)
@spaces_router.get(
    "/{space_id}/",
    response={200: SpaceOut},
    auth=None,
    summary="Get space detail (Dual-purpose) (slash)",
    include_in_schema=False,
)
def get_space_detail_endpoint(request, space_id: int):
    """Retrieve space detail (Task T-018b).

    - Owner/Admin: returns the space regardless of active status or BR-005.
    - Public: returns the space ONLY IF venue satisfies BR-005 and space is active.
      Otherwise returns 404 with zero info leak.
    """
    user = auth(request)
    return services.get_space_detail(user=user, space_id=space_id)


@spaces_router.patch(
    "/{space_id}",
    response={200: SpaceOut},
    auth=auth,
    summary="Partial update space (Owner)",
)
@spaces_router.patch(
    "/{space_id}/",
    response={200: SpaceOut},
    auth=auth,
    summary="Partial update space (Owner) (slash)",
    include_in_schema=False,
)
def patch_space_endpoint(request, space_id: int, payload: SpaceUpdateIn):
    """Partial update of space fields (Task T-018b)."""
    return services.update_space(user=request.auth, space_id=space_id, data=payload)


@spaces_router.put(
    "/{space_id}",
    response={200: SpaceOut},
    auth=auth,
    summary="Update space (Owner)",
)
@spaces_router.put(
    "/{space_id}/",
    response={200: SpaceOut},
    auth=auth,
    summary="Update space (Owner) (slash)",
    include_in_schema=False,
)
def put_space_endpoint(request, space_id: int, payload: SpaceUpdateIn):
    """Full/partial update of space fields (Task T-018b)."""
    return services.update_space(user=request.auth, space_id=space_id, data=payload)


@spaces_router.post(
    "/{space_id}/deactivate",
    response={200: SpaceOut},
    auth=auth,
    summary="Deactivate a space (Owner)",
)
@spaces_router.post(
    "/{space_id}/deactivate/",
    response={200: SpaceOut},
    auth=auth,
    summary="Deactivate a space (Owner) (slash)",
    include_in_schema=False,
)
def deactivate_space_endpoint(request, space_id: int):
    """Soft-deactivate a space (sets is_active=False)."""
    return services.deactivate_space(user=request.auth, space_id=space_id)


@spaces_router.delete(
    "/{space_id}",
    response={200: SpaceOut, 204: None},
    auth=auth,
    summary="Delete or deactivate a space (Owner)",
)
@spaces_router.delete(
    "/{space_id}/",
    response={200: SpaceOut, 204: None},
    auth=auth,
    summary="Delete or deactivate a space (Owner) (slash)",
    include_in_schema=False,
)
def delete_space_endpoint(request, space_id: int):
    """Delete or deactivate a space following T-015 / ADR-005 policy (Task T-018b).

    - If pins with bookings exist -> 409 TABLE_PIN_PROTECTED (space remains).
    - If pins or panoramas exist (no bookings) -> deactivates space, returns 200 with SpaceOut (space remains).
    - If no pins and no panoramas -> hard-deletes space, returns 204 No Content.
    """
    space, hard_deleted = services.delete_space(user=request.auth, space_id=space_id)
    if hard_deleted:
        return Status(204, None)
    return Status(200, space)
