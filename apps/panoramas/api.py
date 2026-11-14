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
from ninja.responses import Status

from apps.accounts.auth import auth
from apps.panoramas import services
from apps.panoramas.schemas import (
    PanoramaUploadOut,
    PublicPanoramaOut,
    TablePinCreateIn,
    TablePinOut,
    TablePinUpdateIn,
)

router = Router(tags=["panoramas"])
spaces_router = Router(tags=["spaces"])


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
