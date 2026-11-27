"""Celery tasks for panorama image processing (TD-003 / ARCH-003 / Task T-017).

Pipeline flow:
1. Idempotency guard: if record is already READY, no-op (return early without duplicate files).
2. Status transition: UPLOADED / FAILED -> PROCESSING.
3. Conversion via Pillow:
   - Safe opening with Image.MAX_IMAGE_PIXELS decompression-bomb protection.
   - EXIF orientation normalization via ImageOps.exif_transpose.
   - Color mode normalization to RGB.
   - Equirectangular 2:1 aspect ratio verification.
   - Downscaling without upscaling beyond 4096x2048 cap.
   - High-quality WebP generation (max 4096x2048, quality 82).
   - LQIP thumbnail generation (512x256, quality 60).
4. Atomic storage writes: temporary file creation and atomic replacement.
5. Verification: verify output files exist, are readable, and match dimensions BEFORE DB update.
6. DB commit & status transition to READY.
7. Original file deletion ONLY AFTER verified outputs and successful DB commit.
8. Bounded retry and failure handling: on error, mark FAILED with sanitized message,
   preserving original file for re-upload/retry.
"""
from __future__ import annotations

import io
import logging
import os
import time
import uuid

from celery import shared_task
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from PIL import Image, ImageOps, UnidentifiedImageError

from apps.panoramas.models import PanoramaImage, PanoramaStatus

logger = logging.getLogger(__name__)

# Processing parameters (TD-003 / ARCH-003 / Task T-017)
MAX_PANORAMA_WIDTH = 4096
MAX_PANORAMA_HEIGHT = 2048
PANORAMA_QUALITY = 82

THUMB_WIDTH = 512
THUMB_HEIGHT = 256
THUMB_QUALITY = 60

# Roadmap target size: <1.5 MB (log metadata only, never silently reduce quality)
ROADMAP_SIZE_TARGET_BYTES = 1536 * 1024


def convert_equirectangular_image(content: bytes) -> tuple[bytes, bytes, int, int]:
    """Convert raw equirectangular image bytes into optimized WebP and LQIP thumbnail.

    Guarantees:
    - Enforces Pillow decompression-bomb pixel limits.
    - Normalizes EXIF orientation.
    - Normalizes color mode to RGB.
    - Verifies equirectangular 2:1 aspect ratio.
    - Resizes WITHOUT upscaling beyond 4096x2048 cap.
    - Encodes WebP (quality 82) and 512x256 thumbnail (quality 60).

    Returns:
        Tuple of (webp_bytes, thumb_bytes, final_width, final_height).
    Raises:
        ValueError, Image.DecompressionBombError, UnidentifiedImageError on invalid input.
    """
    stream = io.BytesIO(content)
    with Image.open(stream) as opened:
        # 1. EXIF orientation normalization
        im: Image.Image = ImageOps.exif_transpose(opened)

        # 2. Color mode normalization
        if im.mode != "RGB":
            im = im.convert("RGB")

        orig_w, orig_h = im.size
        if orig_w <= 0 or orig_h <= 0:
            raise ValueError(f"Invalid image dimensions: {orig_w}x{orig_h}")

        # 3. Equirectangular aspect ratio check (~2:1)
        aspect = orig_w / float(orig_h)
        if aspect < 1.75 or aspect > 2.25:
            raise ValueError(
                f"Image is not a 2:1 equirectangular panorama: {orig_w}x{orig_h} (aspect {aspect:.2f})"
            )

        # 4. Dimension calculation (No-upscale rule!)
        if orig_w > MAX_PANORAMA_WIDTH or orig_h > MAX_PANORAMA_HEIGHT:
            scale = min(MAX_PANORAMA_WIDTH / orig_w, MAX_PANORAMA_HEIGHT / orig_h)
            final_w = int(round(orig_w * scale))
            final_h = int(round(orig_h * scale))
            im_main = im.resize((final_w, final_h), Image.Resampling.LANCZOS)
        else:
            final_w, final_h = orig_w, orig_h
            im_main = im

        # 5. Encode main WebP asset (quality 82)
        webp_buf = io.BytesIO()
        im_main.save(webp_buf, format="WEBP", quality=PANORAMA_QUALITY, method=4)
        webp_bytes = webp_buf.getvalue()

        # 6. Encode 512x256 LQIP thumbnail (quality 60)
        thumb_w = min(THUMB_WIDTH, final_w)
        thumb_h = min(THUMB_HEIGHT, final_h)
        im_thumb = im_main.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
        thumb_buf = io.BytesIO()
        im_thumb.save(thumb_buf, format="WEBP", quality=THUMB_QUALITY, method=4)
        thumb_bytes = thumb_buf.getvalue()

        return webp_bytes, thumb_bytes, final_w, final_h


def atomic_storage_save(storage_path: str, content: bytes) -> str:
    """Save content to storage using an atomic rename where possible.

    Prevents partial/corrupt files if worker crashes mid-write.
    """
    if hasattr(default_storage, "path"):
        try:
            dest_path = default_storage.path(storage_path)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            tmp_path = f"{dest_path}.tmp_{uuid.uuid4().hex}"
            with open(tmp_path, "wb") as f:
                f.write(content)
            os.replace(tmp_path, dest_path)
            return storage_path
        except (NotImplementedError, OSError):
            pass

    # Fallback for non-local/in-memory storages
    if default_storage.exists(storage_path):
        default_storage.delete(storage_path)
    return default_storage.save(storage_path, ContentFile(content))


def verify_storage_output(
    storage_path: str,
    expected_format: str = "WEBP",
    max_width: int = 4096,
    max_height: int = 2048,
) -> tuple[int, int, int]:
    """Verify that an output file exists in storage, is readable, and matches dimensions."""
    if not default_storage.exists(storage_path):
        raise FileNotFoundError(f"Output file does not exist at {storage_path}")

    with default_storage.open(storage_path, "rb") as f:
        file_bytes = f.read()

    stream = io.BytesIO(file_bytes)
    with Image.open(stream) as im:
        im.verify()

    # Re-open to inspect format and size after verify()
    stream.seek(0)
    with Image.open(stream) as im:
        fmt = (im.format or "").upper()
        if fmt != expected_format:
            raise ValueError(f"Expected format {expected_format}, got {fmt} for {storage_path}")
        if im.width > max_width or im.height > max_height:
            raise ValueError(
                f"Output {storage_path} dimensions {im.width}x{im.height} exceed maximum {max_width}x{max_height}"
            )
        return im.width, im.height, len(file_bytes)


@shared_task(
    bind=True,
    name="panoramas.process_panorama_image",
    max_retries=3,
    default_retry_delay=60,
)
def process_panorama_image(self, image_id: str | uuid.UUID) -> dict:
    """Asynchronously process an equirectangular panorama upload into WebP and thumbnail (T-017).

    Guarantees:
    - Idempotency: no-op if already READY.
    - Safe conversion with Pillow (orientation, aspect ratio, no-upscale, WebP quality 82, thumb quality 60).
    - Atomic output writes.
    - Verified outputs BEFORE marking READY and BEFORE deleting original.
    - Original file deleted ONLY AFTER verified outputs and DB commit.
    - Bounded retries and failure logging (metadata only).
    """
    start_time = time.monotonic()
    image_uuid = uuid.UUID(str(image_id)) if not isinstance(image_id, uuid.UUID) else image_id

    panorama = PanoramaImage.objects.select_related("space__venue").filter(id=image_uuid).first()
    if not panorama:
        logger.error("PanoramaImage %s not found for processing.", image_uuid)
        return {"status": "NOT_FOUND", "id": str(image_uuid)}

    # 1. Idempotency guard
    if panorama.status == PanoramaStatus.READY:
        logger.info("Panorama %s is already READY. Skipping duplicate processing.", image_uuid)
        return {"status": "ALREADY_READY", "id": str(image_uuid)}

    if panorama.status not in (PanoramaStatus.UPLOADED, PanoramaStatus.PROCESSING, PanoramaStatus.FAILED):
        logger.warning(
            "Panorama %s in unexpected status %s; skipping.", image_uuid, panorama.status
        )
        return {"status": "SKIPPED", "id": str(image_uuid), "current_status": panorama.status}

    # 2. Transition to PROCESSING
    if panorama.status != PanoramaStatus.PROCESSING:
        try:
            panorama.transition_to(PanoramaStatus.PROCESSING, save=True)
        except Exception as trans_err:
            logger.warning("Could not transition %s to PROCESSING: %s", image_uuid, trans_err)

    venue_id = panorama.space.venue_id
    orig_file_path = panorama.original_file.name if panorama.original_file else None

    try:
        # 3. Read original file
        if not orig_file_path or not default_storage.exists(orig_file_path):
            raise FileNotFoundError(f"Original upload file missing for panorama {image_uuid}")

        with default_storage.open(orig_file_path, "rb") as f:
            raw_bytes = f.read()

        # 4. Convert via Pillow
        webp_bytes, thumb_bytes, final_w, final_h = convert_equirectangular_image(raw_bytes)

        # 5. Atomic storage writes
        webp_storage_path = f"panoramas/{venue_id}/{image_uuid}.webp"
        thumb_storage_path = f"panoramas/{venue_id}/{image_uuid}_thumb.webp"

        atomic_storage_save(webp_storage_path, webp_bytes)
        atomic_storage_save(thumb_storage_path, thumb_bytes)

        # 6. Verify outputs exist, are readable, and have expected bounds BEFORE marking anything
        verify_storage_output(webp_storage_path, "WEBP", max_width=MAX_PANORAMA_WIDTH, max_height=MAX_PANORAMA_HEIGHT)
        verify_storage_output(thumb_storage_path, "WEBP", max_width=THUMB_WIDTH, max_height=THUMB_HEIGHT)

        # Check roadmap target size (< 1.5MB)
        if len(webp_bytes) > ROADMAP_SIZE_TARGET_BYTES:
            logger.info(
                "Panorama %s WebP size (%d bytes) exceeds 1.5MB target; quality maintained at %d.",
                image_uuid,
                len(webp_bytes),
                PANORAMA_QUALITY,
            )

        # 7. Database update & status transition to READY
        with transaction.atomic():
            panorama.webp_file.name = webp_storage_path
            panorama.thumb_file.name = thumb_storage_path
            panorama.width = final_w
            panorama.height = final_h
            panorama.file_size_bytes = len(webp_bytes)
            panorama.error_message = ""
            panorama.transition_to(PanoramaStatus.READY, save=False)
            panorama.save(
                update_fields=[
                    "status",
                    "processed_at",
                    "webp_file",
                    "thumb_file",
                    "width",
                    "height",
                    "file_size_bytes",
                    "error_message",
                ]
            )

        # 8. Delete original file ONLY AFTER verified outputs and successful DB commit
        if orig_file_path and default_storage.exists(orig_file_path):
            try:
                default_storage.delete(orig_file_path)
                panorama.original_file = None
                panorama.save(update_fields=["original_file"])
                logger.info("Cleaned up raw original file %s for panorama %s.", orig_file_path, image_uuid)
            except Exception as del_err:
                logger.warning(
                    "Failed to delete original file %s after successful conversion: %s",
                    orig_file_path,
                    del_err,
                )

        duration = time.monotonic() - start_time
        logger.info(
            "Successfully processed panorama %s in %.3fs (WebP: %dx%d, %d bytes; Thumb: %d bytes)",
            image_uuid,
            duration,
            final_w,
            final_h,
            len(webp_bytes),
            len(thumb_bytes),
        )
        return {
            "status": "READY",
            "id": str(image_uuid),
            "width": final_w,
            "height": final_h,
            "file_size_bytes": len(webp_bytes),
            "duration_seconds": round(duration, 3),
        }

    except Exception as exc:
        duration = time.monotonic() - start_time
        is_deterministic = isinstance(
            exc, (ValueError, UnidentifiedImageError, Image.DecompressionBombError, FileNotFoundError)
        )
        sanitized_error = "Image processing failed: " + (
            "Invalid equirectangular format or dimensions"
            if isinstance(exc, (ValueError, UnidentifiedImageError))
            else "Original file missing"
            if isinstance(exc, FileNotFoundError)
            else "Decompression bomb detected"
            if isinstance(exc, Image.DecompressionBombError)
            else "Unexpected error occurred during conversion"
        )

        logger.error(
            "Failed processing panorama %s after %.3fs: %s (exc: %s)",
            image_uuid,
            duration,
            sanitized_error,
            type(exc).__name__,
        )

        # Mark FAILED in database while keeping original file for retry/re-upload
        try:
            panorama.refresh_from_db()
            if panorama.status != PanoramaStatus.FAILED:
                panorama.transition_to(
                    PanoramaStatus.FAILED, error_message=sanitized_error, save=True
                )
        except Exception as db_err:
            logger.error("Failed to set FAILED status on panorama %s: %s", image_uuid, db_err)

        # Bounded retries: retry only for non-deterministic transient errors
        if not is_deterministic and self.request.retries < self.max_retries:
            logger.info(
                "Retrying processing for panorama %s (attempt %d/%d)",
                image_uuid,
                self.request.retries + 1,
                self.max_retries,
            )
            raise self.retry(exc=exc)

        return {
            "status": "FAILED",
            "id": str(image_uuid),
            "error": sanitized_error,
            "duration_seconds": round(duration, 3),
        }
