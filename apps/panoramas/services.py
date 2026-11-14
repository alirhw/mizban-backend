"""Service layer for the panoramas app (Task T-016).

Architecture rules:
- ARCH-001: All business logic, DB mutations, file validation, and permissions live here.
- ARCH-002: All state-affecting writes execute inside transaction.atomic().
- ARCH-003: No heavy image processing in the request/response cycle. The upload
  endpoint returns HTTP 202 Accepted and delegates processing to Celery via a single
  dispatch seam.
- TR-002 / TD-003: Strict 20MB size cap, magic bytes content validation, path-traversal
  prevention via UUID names, and Pillow decompression-bomb protection.
"""
from __future__ import annotations

import io
import logging
from typing import Any, Optional, Tuple
import uuid

from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.http import Http404
from PIL import Image, UnidentifiedImageError

from apps.accounts.models import UserRole
from apps.panoramas.models import PanoramaImage, PanoramaStatus, Space
from core.exceptions import (
    FileTooLargeError,
    ImageDecompressionBombError,
    InvalidImageError,
)

logger = logging.getLogger(__name__)

# Application file size limit: 20 MB (TD-003 / Task T-016)
MAX_PANORAMA_FILE_SIZE = 20 * 1024 * 1024  # 20,971,520 bytes

# Allowed MIME types and canonical extensions for 360 equirectangular images
ALLOWED_MIME_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def detect_image_type_from_magic_bytes(header: bytes) -> Tuple[str, str]:
    """Detect image MIME type and canonical extension from raw magic bytes.

    Never trusts client MIME type or extension (path-traversal and spoofing prevention).
    Returns (mime_type, extension) or raises InvalidImageError.
    """
    if not header:
        raise InvalidImageError("File is empty or contains no readable data.")

    # 1. Try python-magic if available
    try:
        import magic
        mime = magic.from_buffer(header, mime=True)
        if mime in ALLOWED_MIME_EXTENSIONS:
            return mime, ALLOWED_MIME_EXTENSIONS[mime]
    except Exception:
        # Fallback to direct binary signature inspection (e.g. if libmagic dll path issues on Windows)
        pass

    # 2. Invariant binary signature inspection
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "image/webp", ".webp"

    raise InvalidImageError(
        "Uploaded file does not match allowed image formats. Only equirectangular JPEG, PNG, or WebP are accepted."
    )


def validate_image_with_pillow(content: bytes) -> Tuple[int, int]:
    """Validate image integrity and dimension safety using Pillow.

    Enforces:
    - Integrity verification via im.verify() (detects corrupt files or faked extensions).
    - Decompression-bomb limits (Image.MAX_IMAGE_PIXELS).
    - Format validation (JPEG, PNG, WEBP only).

    Returns (width, height) on success, or raises DomainError subclasses.
    """
    # 1. Verify structure
    try:
        stream = io.BytesIO(content)
        im = Image.open(stream)
        im.verify()
    except Image.DecompressionBombError as exc:
        logger.warning("Rejected decompression bomb upload: %s", exc)
        raise ImageDecompressionBombError(
            "Uploaded image exceeds safe pixel limits (decompression bomb detected)."
        ) from exc
    except (UnidentifiedImageError, SyntaxError, ValueError, OSError, IOError) as exc:
        logger.warning("Rejected corrupt/invalid image upload: %s", exc)
        raise InvalidImageError("File content is corrupted or not a valid image.") from exc

    # 2. Read dimensions and format (im.verify closes the image stream, so re-open)
    try:
        stream.seek(0)
        im = Image.open(stream)
        width, height = im.size
        format_name = (im.format or "").upper()
        if format_name not in ("JPEG", "PNG", "WEBP"):
            raise InvalidImageError(f"Unsupported image format: {format_name}.")
        return width, height
    except Image.DecompressionBombError as exc:
        raise ImageDecompressionBombError(
            "Uploaded image exceeds safe pixel limits (decompression bomb detected)."
        ) from exc
    except Exception as exc:
        if isinstance(exc, (InvalidImageError, ImageDecompressionBombError)):
            raise
        raise InvalidImageError("Unable to read image dimensions.") from exc


def authorize_space_owner(user: Any, space_id: int) -> Space:
    """Authorize that caller is the owner (or admin) of the venue containing space_id.

    Raises:
        PermissionDenied: if caller is not an owner/admin or does not own the venue.
        Http404: if space does not exist.
    """
    if not (getattr(user, "is_staff", False) or getattr(user, "role", None) in (UserRole.VENUE_OWNER, UserRole.ADMIN)):
        raise PermissionDenied("Only venue owners or admins can upload panorama images.")

    space = Space.objects.select_related("venue").filter(id=space_id).first()
    if not space:
        raise Http404("Space not found.")

    if space.venue.owner_id != user.id and not (user.is_staff or user.role == UserRole.ADMIN):
        raise PermissionDenied("You do not own the venue for this space.")

    return space


def dispatch_panorama_processing(panorama_image_id: uuid.UUID) -> bool:
    """Single dispatch seam for triggering asynchronous panorama processing (ARCH-003 / Task T-016 / T-017).

    Called within a transaction.on_commit() hook after an image is stored and
    committed in UPLOADED status.

    T-016 provides this seam. T-017 will wire this seam to the actual Celery
    task `process_panorama_image.delay(str(panorama_image_id))`.

    If the broker is unreachable or dispatch fails, this seam catches the error,
    logs a warning, and returns False so the upload still succeeds with the
    PanoramaImage remaining safely in UPLOADED status.
    """
    try:
        from apps.panoramas import tasks
        task_func = getattr(tasks, "process_panorama_image", None)
        if task_func is not None and hasattr(task_func, "delay"):
            task_func.delay(str(panorama_image_id))
            logger.info("Enqueued panorama processing for image_id=%s", panorama_image_id)
        else:
            logger.info(
                "Dispatch seam: task process_panorama_image not wired (T-017 pending) for image_id=%s",
                panorama_image_id,
            )
        return True
    except Exception as exc:
        logger.warning(
            "Failed to dispatch panorama processing for image_id=%s (broker unavailable?): %s",
            panorama_image_id,
            exc,
        )
        return False


def upload_panorama_for_space(
    user: Any,
    space_id: int,
    file: UploadedFile,
) -> PanoramaImage:
    """Validate, store, and record a 360 panorama upload (Task T-016).

    Guarantees:
    - Caller must be the venue owner of the space (IDOR prevention).
    - File size <= 20 MB.
    - Magic bytes and Pillow verification.
    - Storage under controlled path `panoramas/{venue_id}/{uuid}.<ext>` (no client filename).
    - Database record created in UPLOADED status.
    - Asynchronous processing dispatched via transaction.on_commit seam.
    - Failure cleanup: zero orphan files and zero orphan records on error.
    """
    # 1. Authorize owner
    space = authorize_space_owner(user, space_id)

    # 2. Enforce 20 MB size limit
    if file.size > MAX_PANORAMA_FILE_SIZE:
        raise FileTooLargeError(
            f"File size ({file.size} bytes) exceeds maximum allowed limit of 20MB."
        )

    # Read bytes safely in chunks
    content = file.read()
    if len(content) > MAX_PANORAMA_FILE_SIZE:
        raise FileTooLargeError("File stream exceeds maximum allowed limit of 20MB.")
    if len(content) == 0:
        raise InvalidImageError("Uploaded file is empty.")

    # 3. Content validation: Magic bytes + Pillow
    mime_type, ext = detect_image_type_from_magic_bytes(content[:2048])
    width, height = validate_image_with_pillow(content)

    # 4. Generate safe UUID storage key (path-traversal prevention)
    image_uuid = uuid.uuid4()
    storage_path = f"panoramas/{space.venue_id}/{image_uuid}{ext}"

    # 5. Store file and create database record with failure cleanup
    saved_path: Optional[str] = None
    try:
        saved_path = default_storage.save(storage_path, ContentFile(content))

        with transaction.atomic():
            panorama = PanoramaImage.objects.create(
                id=image_uuid,
                space=space,
                status=PanoramaStatus.UPLOADED,
                original_file=saved_path,
                width=width,
                height=height,
                file_size_bytes=len(content),
            )
            # Dispatch via on_commit hook
            transaction.on_commit(lambda: dispatch_panorama_processing(panorama.id))

        return panorama

    except Exception:
        # Failure cleanup: delete storage file if DB write or transaction failed
        if saved_path and default_storage.exists(saved_path):
            try:
                default_storage.delete(saved_path)
                logger.warning("Cleaned up orphaned storage file at %s after failure.", saved_path)
            except Exception as cleanup_exc:
                logger.error("Failed to delete orphaned storage file %s: %s", saved_path, cleanup_exc)
        raise
