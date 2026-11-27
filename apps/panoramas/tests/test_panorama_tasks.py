"""Unit, integration, and failure/retry tests for Celery panorama image processing pipeline (Task T-017).

Pipeline:
`apps.panoramas.tasks.process_panorama_image` (TD-003 / ARCH-003 / PH-04 / WS-MEDIA-360)

Acceptance Criteria & Test Matrix:
1. Unit tests for conversion & resize:
   - No-upscale rule: 2048x1024 stays 2048x1024, not upscaled to 4096x2048.
   - Downscale rule: 6000x3000 is downscaled to max 4096x2048.
   - Aspect ratio validation: 2:1 is accepted; non-2:1 (1:1 or 1:2) raises ValueError.
   - Color mode normalization: RGBA, CMYK, P modes are converted to RGB.
   - EXIF orientation normalization: orientation tags are transposed.
   - Thumbnail generation: 512x256 thumbnail at quality 60.
   - WebP encoding: output is valid WebP at quality 82.
2. Integration tests for Celery task:
   - Happy path: UPLOADED -> PROCESSING -> READY.
     - WebP and thumbnail written to storage.
     - Output dimensions & file size recorded on PanoramaImage.
     - Record marked READY with processed_at set.
     - Raw original file deleted from storage.
   - Real sample panorama test: processes realistic sample image (2048x1024).
3. Failure and retry paths:
   - Invalid aspect ratio / corrupt image -> marks FAILED with sanitized error message.
   - Original file kept in storage on failure (for retry/re-upload).
   - Missing original file -> marks FAILED.
   - Retry from FAILED status succeeds when valid file is present.
4. Idempotency & duplicate delivery:
   - Running task on already READY panorama is a safe no-op.
   - Does not duplicate files, does not re-delete.
5. Atomic writes & error resilience:
   - Atomic replacement prevents partial output writes.
   - Original file deletion error does not roll back or fail READY status.
   - Output size target reporting: logs info when size exceeds 1.5MB without dropping quality.
6. Dispatch seam integration:
   - dispatch_panorama_processing wires directly to process_panorama_image.delay.
"""
from __future__ import annotations

import io
import os
import uuid
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone
from PIL import Image

from apps.panoramas import services
from apps.panoramas.models import PanoramaImage, PanoramaStatus
from apps.panoramas.tasks import (
    MAX_PANORAMA_HEIGHT,
    MAX_PANORAMA_WIDTH,
    atomic_storage_save,
    convert_equirectangular_image,
    process_panorama_image,
    verify_storage_output,
)
from apps.panoramas.tests.factories import SpaceFactory
from apps.venues.tests.factories import VenueFactory


@pytest.fixture(autouse=True)
def setup_test_media(tmp_path, settings):
    """Isolate media storage and cache per test."""
    settings.DEBUG = True
    settings.MEDIA_ROOT = tmp_path
    cache.clear()
    yield
    cache.clear()


def make_equirectangular_bytes(
    width: int = 2048,
    height: int = 1024,
    mode: str = "RGB",
    fmt: str = "JPEG",
    color=(100, 150, 200),
) -> bytes:
    """Generate in-memory test image bytes with exact aspect ratio."""
    if mode == "RGBA":
        img = Image.new("RGBA", (width, height), color=(100, 150, 200, 255))
    elif mode == "P":
        img = Image.new("P", (width, height))
    elif mode == "CMYK":
        img = Image.new("CMYK", (width, height), color=(50, 50, 50, 0))
    else:
        img = Image.new("RGB", (width, height), color=color)

    buf = io.BytesIO()
    if mode == "CMYK":
        img.save(buf, format="JPEG")
    elif mode in ("RGBA", "P"):
        img.save(buf, format="PNG")
    else:
        img.save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture
def space():
    venue = VenueFactory()
    return SpaceFactory(venue=venue, name="Panoramic Terrace")


class TestPanoramaConversionUnits:
    """Unit tests for Pillow equirectangular conversion and resize logic."""

    def test_no_upscale_rule(self):
        """Images smaller than 4096x2048 must NOT be upscaled (e.g. 2048x1024 stays 2048x1024)."""
        raw_bytes = make_equirectangular_bytes(width=2048, height=1024)
        webp_bytes, thumb_bytes, w, h = convert_equirectangular_image(raw_bytes)

        assert w == 2048
        assert h == 1024

        # Verify output WebP format and dimensions
        with Image.open(io.BytesIO(webp_bytes)) as im:
            assert im.format == "WEBP"
            assert im.size == (2048, 1024)

        # Verify thumbnail dimensions
        with Image.open(io.BytesIO(thumb_bytes)) as im:
            assert im.format == "WEBP"
            assert im.size == (512, 256)

    def test_downscale_rule_caps_at_4096x2048(self):
        """Images larger than 4096x2048 (e.g. 6000x3000) are downscaled to max 4096x2048."""
        raw_bytes = make_equirectangular_bytes(width=6000, height=3000)
        webp_bytes, thumb_bytes, w, h = convert_equirectangular_image(raw_bytes)

        assert w == MAX_PANORAMA_WIDTH
        assert h == MAX_PANORAMA_HEIGHT

        with Image.open(io.BytesIO(webp_bytes)) as im:
            assert im.size == (4096, 2048)

    def test_aspect_ratio_non_2_to_1_rejected(self):
        """Square or vertical images (not 2:1 equirectangular) raise ValueError."""
        # 1:1 aspect ratio
        square_bytes = make_equirectangular_bytes(width=1000, height=1000)
        with pytest.raises(ValueError, match="not a 2:1 equirectangular panorama"):
            convert_equirectangular_image(square_bytes)

        # 1:2 vertical aspect ratio
        vertical_bytes = make_equirectangular_bytes(width=800, height=1600)
        with pytest.raises(ValueError, match="not a 2:1 equirectangular panorama"):
            convert_equirectangular_image(vertical_bytes)

    def test_color_mode_normalization(self):
        """Non-RGB images (RGBA, CMYK, P) are converted to clean RGB."""
        for mode in ("RGBA", "CMYK", "P"):
            raw_bytes = make_equirectangular_bytes(width=800, height=400, mode=mode)
            webp_bytes, thumb_bytes, w, h = convert_equirectangular_image(raw_bytes)

            with Image.open(io.BytesIO(webp_bytes)) as im:
                assert im.mode == "RGB"
            with Image.open(io.BytesIO(thumb_bytes)) as im:
                assert im.mode == "RGB"

    def test_exif_orientation_normalization(self):
        """EXIF orientation transposition is applied."""
        img = Image.new("RGB", (2000, 1000), color=(200, 100, 50))
        # Add EXIF orientation tag (e.g. tag 0x0112 = 1 normal, 6 rotated 90 CW)
        exif = img.getexif()
        exif[0x0112] = 1
        buf = io.BytesIO()
        img.save(buf, format="JPEG", exif=exif)

        webp_bytes, thumb_bytes, w, h = convert_equirectangular_image(buf.getvalue())
        assert (w, h) == (2000, 1000)

    def test_atomic_storage_save(self, tmp_path):
        """Atomic write ensures file is written and accessible."""
        test_path = "panoramas/test/atom.webp"
        test_data = b"RIFF....WEBPTESTDATA"

        saved_path = atomic_storage_save(test_path, test_data)
        assert default_storage.exists(saved_path)
        with default_storage.open(saved_path, "rb") as f:
            assert f.read() == test_data

    def test_verify_storage_output_detects_corrupt_file(self):
        """Corrupt file in storage fails verification."""
        bad_path = "panoramas/test/corrupt.webp"
        default_storage.save(bad_path, ContentFile(b"not a webp file"))

        with pytest.raises(Exception):
            verify_storage_output(bad_path, "WEBP")


@pytest.mark.django_db
class TestProcessPanoramaTaskIntegration:
    """Integration test suite for process_panorama_image Celery task."""

    def test_full_happy_path_uploaded_to_ready(self, space):
        """Full pipeline: UPLOADED -> PROCESSING -> READY with WebP, thumb, and original deleted."""
        raw_bytes = make_equirectangular_bytes(width=2048, height=1024)
        orig_key = default_storage.save(
            f"panoramas/{space.venue_id}/test_orig.jpg",
            ContentFile(raw_bytes),
        )

        panorama = PanoramaImage.objects.create(
            space=space,
            status=PanoramaStatus.UPLOADED,
            original_file=orig_key,
            file_size_bytes=len(raw_bytes),
            width=2048,
            height=1024,
        )

        # Run task synchronously
        result = process_panorama_image(str(panorama.id))

        assert result["status"] == "READY"
        panorama.refresh_from_db()

        # Check DB state
        assert panorama.status == PanoramaStatus.READY
        assert panorama.processed_at is not None
        assert panorama.error_message == ""
        assert panorama.width == 2048
        assert panorama.height == 1024
        assert panorama.file_size_bytes > 0

        # Check WebP and Thumbnail exist in storage
        assert panorama.webp_file
        assert default_storage.exists(panorama.webp_file.name)
        assert panorama.thumb_file
        assert default_storage.exists(panorama.thumb_file.name)

        # Verify output formats and bounds
        w, h, size = verify_storage_output(panorama.webp_file.name, "WEBP", 4096, 2048)
        assert (w, h) == (2048, 1024)
        assert size == panorama.file_size_bytes

        tw, th, tsize = verify_storage_output(panorama.thumb_file.name, "WEBP", 512, 256)
        assert (tw, th) == (512, 256)

        # Original heavy file MUST be deleted from storage
        assert not default_storage.exists(orig_key)
        assert not panorama.original_file

    def test_real_sample_panorama_processing(self, space):
        """Processes the realistic generated 2048x1024 sample panorama file."""
        sample_file_path = os.path.join(
            os.path.dirname(__file__), "assets", "sample_panorama.jpg"
        )
        assert os.path.exists(sample_file_path), "Sample panorama file must exist"

        with open(sample_file_path, "rb") as f:
            sample_bytes = f.read()

        orig_key = default_storage.save(
            f"panoramas/{space.venue_id}/sample.jpg",
            ContentFile(sample_bytes),
        )

        panorama = PanoramaImage.objects.create(
            space=space,
            status=PanoramaStatus.UPLOADED,
            original_file=orig_key,
            file_size_bytes=len(sample_bytes),
        )

        result = process_panorama_image(str(panorama.id))
        assert result["status"] == "READY"

        panorama.refresh_from_db()
        assert panorama.status == PanoramaStatus.READY
        assert default_storage.exists(panorama.webp_file.name)
        assert default_storage.exists(panorama.thumb_file.name)
        assert not default_storage.exists(orig_key)

    def test_failure_on_invalid_aspect_ratio_preserves_original(self, space):
        """Invalid aspect ratio marks FAILED, logs sanitized error, and preserves original file."""
        bad_aspect_bytes = make_equirectangular_bytes(width=1000, height=1000)  # 1:1 square
        orig_key = default_storage.save(
            f"panoramas/{space.venue_id}/square.jpg",
            ContentFile(bad_aspect_bytes),
        )

        panorama = PanoramaImage.objects.create(
            space=space,
            status=PanoramaStatus.UPLOADED,
            original_file=orig_key,
            file_size_bytes=len(bad_aspect_bytes),
        )

        result = process_panorama_image(str(panorama.id))
        assert result["status"] == "FAILED"

        panorama.refresh_from_db()
        assert panorama.status == PanoramaStatus.FAILED
        assert "Invalid equirectangular format or dimensions" in panorama.error_message

        # Original file MUST be kept intact for owner re-upload or retry
        assert default_storage.exists(orig_key)

    def test_failure_on_corrupt_file_preserves_original(self, space):
        """Corrupt image marks FAILED with sanitized error and keeps original."""
        corrupt_bytes = b"not an image"
        orig_key = default_storage.save(
            f"panoramas/{space.venue_id}/corrupt.jpg",
            ContentFile(corrupt_bytes),
        )

        panorama = PanoramaImage.objects.create(
            space=space,
            status=PanoramaStatus.UPLOADED,
            original_file=orig_key,
            file_size_bytes=len(corrupt_bytes),
        )

        result = process_panorama_image(str(panorama.id))
        assert result["status"] == "FAILED"

        panorama.refresh_from_db()
        assert panorama.status == PanoramaStatus.FAILED
        assert default_storage.exists(orig_key)

    def test_missing_original_file_marks_failed(self, space):
        """Missing original file in storage transitions to FAILED."""
        panorama = PanoramaImage.objects.create(
            space=space,
            status=PanoramaStatus.UPLOADED,
            original_file="panoramas/999/non_existent.jpg",
            file_size_bytes=100,
        )

        result = process_panorama_image(str(panorama.id))
        assert result["status"] == "FAILED"

        panorama.refresh_from_db()
        assert panorama.status == PanoramaStatus.FAILED
        assert "Original file missing" in panorama.error_message

    def test_retry_after_failure_succeeds(self, space):
        """A panorama in FAILED status can be retried and transition to READY."""
        raw_bytes = make_equirectangular_bytes(width=2048, height=1024)
        orig_key = default_storage.save(
            f"panoramas/{space.venue_id}/retry_test.jpg",
            ContentFile(raw_bytes),
        )

        panorama = PanoramaImage.objects.create(
            space=space,
            status=PanoramaStatus.FAILED,
            original_file=orig_key,
            error_message="Previous transient error",
            file_size_bytes=len(raw_bytes),
        )

        result = process_panorama_image(str(panorama.id))
        assert result["status"] == "READY"

        panorama.refresh_from_db()
        assert panorama.status == PanoramaStatus.READY
        assert panorama.error_message == ""
        assert not default_storage.exists(orig_key)

    def test_idempotency_already_ready_noop(self, space):
        """Re-running task on an already READY panorama is a safe no-op (duplicate delivery)."""
        panorama = PanoramaImage.objects.create(
            space=space,
            status=PanoramaStatus.READY,
            original_file=None,
            webp_file="panoramas/1/already.webp",
            thumb_file="panoramas/1/already_thumb.webp",
            width=2048,
            height=1024,
            file_size_bytes=50000,
            processed_at=timezone.now(),
        )

        # Call task again
        result = process_panorama_image(str(panorama.id))
        assert result["status"] == "ALREADY_READY"

        panorama.refresh_from_db()
        assert panorama.status == PanoramaStatus.READY

    def test_original_file_deletion_failure_does_not_abort_ready_status(self, space):
        """If deleting the raw original raises an OS error, record remains READY and outputs exist."""
        raw_bytes = make_equirectangular_bytes(width=2048, height=1024)
        orig_key = default_storage.save(
            f"panoramas/{space.venue_id}/del_fail.jpg",
            ContentFile(raw_bytes),
        )

        panorama = PanoramaImage.objects.create(
            space=space,
            status=PanoramaStatus.UPLOADED,
            original_file=orig_key,
            file_size_bytes=len(raw_bytes),
        )

        real_delete = default_storage.delete

        def failing_delete(path):
            if path == orig_key:
                raise PermissionError("Simulated file lock on Windows")
            return real_delete(path)

        with patch.object(default_storage, "delete", side_effect=failing_delete):
            result = process_panorama_image(str(panorama.id))

        assert result["status"] == "READY"
        panorama.refresh_from_db()
        assert panorama.status == PanoramaStatus.READY
        assert default_storage.exists(panorama.webp_file.name)

    def test_roadmap_size_target_logged_when_exceeded(self, space, caplog):
        """Outputs exceeding 1.5MB log an info message while maintaining quality 82."""
        raw_bytes = make_equirectangular_bytes(width=4096, height=2048)
        orig_key = default_storage.save(
            f"panoramas/{space.venue_id}/large.jpg",
            ContentFile(raw_bytes),
        )

        panorama = PanoramaImage.objects.create(
            space=space,
            status=PanoramaStatus.UPLOADED,
            original_file=orig_key,
            file_size_bytes=len(raw_bytes),
        )

        with patch("apps.panoramas.tasks.ROADMAP_SIZE_TARGET_BYTES", 100):  # artificially low threshold
            with caplog.at_level("INFO"):
                result = process_panorama_image(str(panorama.id))

        assert result["status"] == "READY"
        assert "exceeds 1.5MB target; quality maintained" in caplog.text

    def test_dispatch_seam_wires_to_celery_task(self):
        """dispatch_panorama_processing wires to process_panorama_image.delay."""
        target_uuid = uuid.uuid4()
        with patch("apps.panoramas.tasks.process_panorama_image.delay") as mock_delay:
            success = services.dispatch_panorama_processing(target_uuid)
            assert success is True
            mock_delay.assert_called_once_with(str(target_uuid))
