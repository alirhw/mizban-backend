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
from apps.panoramas.schemas import PanoramaUploadOut

router = Router(tags=["panoramas"])


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
