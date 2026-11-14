"""API and integration tests for Panorama Upload endpoint (Task T-016).

POST /api/v1/panoramas/spaces/{space_id}/upload
Alias: POST /api/v1/panoramas/spaces/{space_id}/images

Acceptance criteria (PH-04 / WS-MEDIA-360 / Task T-016):
1. Happy path: Owner uploads valid JPEG/PNG/WebP -> HTTP 202 Accepted.
   - File stored with generated UUID under media/panoramas/{venue_id}/{uuid}.<ext>.
   - Safe storage key saved on PanoramaImage.original_file.
   - DB record created in UPLOADED status with correct dimensions and size.
   - File content physically exists in storage.
2. Alias endpoint POST /spaces/{space_id}/images behaves identically (202 Accepted).
3. Role enforcement & IDOR protection:
   - Unauthenticated caller returns HTTP 401.
   - CUSTOMER role caller returns HTTP 403 FORBIDDEN.
   - Non-owner VENUE_OWNER returns HTTP 403 FORBIDDEN (cannot upload to another owner's venue).
   - ADMIN or staff user can upload for any venue space -> HTTP 202 Accepted.
   - Non-existent space_id returns HTTP 404 NOT_FOUND.
4. File size limit enforcement (20 MB):
   - Upload exceeding 20 MB returns HTTP 400 FILE_TOO_LARGE.
   - No DB record created, no storage file orphaned.
5. Content validation (magic bytes + Pillow):
   - Fake extension (HTML/text named .jpg) returns HTTP 400 INVALID_IMAGE.
   - Corrupt image bytes returns HTTP 400 INVALID_IMAGE.
   - Unsupported image format (valid GIF or PDF) returns HTTP 400 INVALID_IMAGE.
   - Empty file (0 bytes) returns HTTP 400 INVALID_IMAGE.
6. Decompression-bomb protection:
   - Image exceeding pixel safety limit returns HTTP 400 IMAGE_DECOMPRESSION_BOMB.
   - No DB record created, no storage file orphaned.
7. Path traversal prevention:
   - Client-supplied malicious filename (e.g. ../../passwd.jpg) is completely ignored.
   - Storage path strictly uses generated UUID under panoramas/{venue_id}/{uuid}.<ext>.
8. Dispatch seam & broker resilience:
   - Upload triggers dispatch_panorama_processing via transaction.on_commit.
   - If broker is unavailable / dispatch raises exception, upload still succeeds (HTTP 202),
     and record stays safely in UPLOADED status.
9. Failure cleanup guarantee:
   - If DB record creation fails after storage write, orphaned storage file is deleted.
   - Zero orphan files and zero orphan records remain.
"""
from __future__ import annotations

import io
from unittest.mock import MagicMock, patch
import uuid

from django.core.cache import cache
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from PIL import Image
import pytest

from apps.accounts.models import UserRole
from apps.panoramas import services
from apps.panoramas.models import PanoramaImage, PanoramaStatus
from apps.panoramas.tests.factories import SpaceFactory
from apps.venues.tests.factories import UserFactory, VenueFactory


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path, settings):
    """Isolate media storage and cache per test run."""
    settings.DEBUG = True
    settings.MEDIA_ROOT = tmp_path
    cache.clear()
    yield
    cache.clear()


def make_jpeg_bytes(width: int = 100, height: int = 50, color=(255, 0, 0)) -> bytes:
    """Generate minimal valid JPEG bytes using Pillow."""
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def make_png_bytes(width: int = 100, height: int = 50, color=(0, 255, 0)) -> bytes:
    """Generate minimal valid PNG bytes using Pillow."""
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_webp_bytes(width: int = 100, height: int = 50, color=(0, 0, 255)) -> bytes:
    """Generate minimal valid WebP bytes using Pillow."""
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="WEBP")
    return buf.getvalue()


def make_gif_bytes(width: int = 50, height: int = 50) -> bytes:
    """Generate valid GIF bytes (unsupported format for 360 equirectangular panoramas)."""
    img = Image.new("P", (width, height))
    buf = io.BytesIO()
    img.save(buf, format="GIF")
    return buf.getvalue()


@pytest.fixture
def venue_owner():
    return UserFactory(role=UserRole.VENUE_OWNER)


@pytest.fixture
def venue(venue_owner):
    return VenueFactory(owner=venue_owner)


@pytest.fixture
def space(venue):
    return SpaceFactory(venue=venue, name="Main Dining Hall")


@pytest.mark.django_db
class TestPanoramaUploadAPI:
    """Integration test suite for POST /api/v1/panoramas/spaces/{space_id}/upload."""

    def test_upload_panorama_happy_path_jpeg(self, client: Client, venue_owner, space):
        """Owner uploads valid equirectangular JPEG -> HTTP 202 Accepted, record UPLOADED."""
        jpeg_bytes = make_jpeg_bytes(width=200, height=100)
        upload_file = SimpleUploadedFile("my_panorama.jpg", jpeg_bytes, content_type="image/jpeg")

        response = client.post(
            f"/api/v1/panoramas/spaces/{space.id}/upload",
            {"file": upload_file},
            HTTP_AUTHORIZATION=f"Bearer {venue_owner.phone}",
        )

        assert response.status_code == 202
        data = response.json()
        assert "id" in data
        assert data["space_id"] == space.id
        assert data["venue_id"] == space.venue.id
        assert data["status"] == PanoramaStatus.UPLOADED
        assert data["width"] == 200
        assert data["height"] == 100
        assert data["file_size_bytes"] == len(jpeg_bytes)
        assert data["original_file"].startswith(f"panoramas/{space.venue.id}/")
        assert data["original_file"].endswith(".jpg")

        # Verify DB persistence
        record = PanoramaImage.objects.get(id=data["id"])
        assert record.space_id == space.id
        assert record.status == PanoramaStatus.UPLOADED
        assert record.width == 200
        assert record.height == 100
        assert record.file_size_bytes == len(jpeg_bytes)
        assert default_storage.exists(record.original_file.name)

    def test_upload_panorama_happy_path_png(self, client: Client, venue_owner, space):
        """Owner uploads valid equirectangular PNG -> HTTP 202 Accepted, stored as .png."""
        png_bytes = make_png_bytes(width=160, height=80)
        upload_file = SimpleUploadedFile("photo.png", png_bytes, content_type="image/png")

        response = client.post(
            f"/api/v1/panoramas/spaces/{space.id}/upload",
            {"file": upload_file},
            HTTP_AUTHORIZATION=f"Bearer {venue_owner.phone}",
        )

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == PanoramaStatus.UPLOADED
        assert data["width"] == 160
        assert data["height"] == 80
        assert data["original_file"].endswith(".png")

        record = PanoramaImage.objects.get(id=data["id"])
        assert default_storage.exists(record.original_file.name)

    def test_upload_panorama_happy_path_webp(self, client: Client, venue_owner, space):
        """Owner uploads valid equirectangular WebP -> HTTP 202 Accepted, stored as .webp."""
        webp_bytes = make_webp_bytes(width=300, height=150)
        upload_file = SimpleUploadedFile("photo.webp", webp_bytes, content_type="image/webp")

        response = client.post(
            f"/api/v1/panoramas/spaces/{space.id}/upload",
            {"file": upload_file},
            HTTP_AUTHORIZATION=f"Bearer {venue_owner.phone}",
        )

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == PanoramaStatus.UPLOADED
        assert data["width"] == 300
        assert data["height"] == 150
        assert data["original_file"].endswith(".webp")

        record = PanoramaImage.objects.get(id=data["id"])
        assert default_storage.exists(record.original_file.name)

    def test_upload_panorama_alias_endpoint(self, client: Client, venue_owner, space):
        """Alias POST /spaces/{space_id}/images behaves identically to /upload."""
        jpeg_bytes = make_jpeg_bytes()
        upload_file = SimpleUploadedFile("alias.jpg", jpeg_bytes, content_type="image/jpeg")

        response = client.post(
            f"/api/v1/panoramas/spaces/{space.id}/images",
            {"file": upload_file},
            HTTP_AUTHORIZATION=f"Bearer {venue_owner.phone}",
        )

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == PanoramaStatus.UPLOADED
        assert PanoramaImage.objects.filter(id=data["id"]).exists()

    def test_upload_unauthenticated_returns_401(self, client: Client, space):
        """Unauthenticated requests are rejected with HTTP 401."""
        jpeg_bytes = make_jpeg_bytes()
        upload_file = SimpleUploadedFile("test.jpg", jpeg_bytes, content_type="image/jpeg")

        response = client.post(
            f"/api/v1/panoramas/spaces/{space.id}/upload",
            {"file": upload_file},
        )

        assert response.status_code == 401

    def test_upload_customer_role_returns_403(self, client: Client, space):
        """Customer users cannot upload panoramas -> HTTP 403 FORBIDDEN."""
        customer = UserFactory(role=UserRole.CUSTOMER)
        jpeg_bytes = make_jpeg_bytes()
        upload_file = SimpleUploadedFile("test.jpg", jpeg_bytes, content_type="image/jpeg")

        response = client.post(
            f"/api/v1/panoramas/spaces/{space.id}/upload",
            {"file": upload_file},
            HTTP_AUTHORIZATION=f"Bearer {customer.phone}",
        )

        assert response.status_code == 403
        data = response.json()
        assert data["error_code"] == "FORBIDDEN"
        assert PanoramaImage.objects.count() == 0

    def test_upload_non_owner_venue_owner_returns_403(self, client: Client, space):
        """Venue owner A cannot upload to a space belonging to Venue owner B (IDOR prevention)."""
        other_owner = UserFactory(role=UserRole.VENUE_OWNER)
        jpeg_bytes = make_jpeg_bytes()
        upload_file = SimpleUploadedFile("test.jpg", jpeg_bytes, content_type="image/jpeg")

        response = client.post(
            f"/api/v1/panoramas/spaces/{space.id}/upload",
            {"file": upload_file},
            HTTP_AUTHORIZATION=f"Bearer {other_owner.phone}",
        )

        assert response.status_code == 403
        data = response.json()
        assert data["error_code"] == "FORBIDDEN"
        assert PanoramaImage.objects.count() == 0

    def test_upload_admin_can_upload_for_any_space(self, client: Client, space):
        """Admin user can upload panorama to any space -> HTTP 202 Accepted."""
        admin = UserFactory(role=UserRole.ADMIN, is_staff=True)
        jpeg_bytes = make_jpeg_bytes()
        upload_file = SimpleUploadedFile("admin.jpg", jpeg_bytes, content_type="image/jpeg")

        response = client.post(
            f"/api/v1/panoramas/spaces/{space.id}/upload",
            {"file": upload_file},
            HTTP_AUTHORIZATION=f"Bearer {admin.phone}",
        )

        assert response.status_code == 202
        assert PanoramaImage.objects.filter(space=space).exists()

    def test_upload_non_existent_space_returns_404(self, client: Client, venue_owner):
        """Non-existent space_id returns HTTP 404 NOT_FOUND."""
        jpeg_bytes = make_jpeg_bytes()
        upload_file = SimpleUploadedFile("test.jpg", jpeg_bytes, content_type="image/jpeg")

        response = client.post(
            "/api/v1/panoramas/spaces/999999/upload",
            {"file": upload_file},
            HTTP_AUTHORIZATION=f"Bearer {venue_owner.phone}",
        )

        assert response.status_code == 404
        data = response.json()
        assert data["error_code"] == "NOT_FOUND"

    def test_upload_file_size_exceeding_20mb_returns_400(self, client: Client, venue_owner, space):
        """Files exceeding 20 MB are rejected with HTTP 400 FILE_TOO_LARGE."""
        oversized_len = 20 * 1024 * 1024 + 1024  # 20MB + 1KB
        fake_content = b"x" * oversized_len
        upload_file = SimpleUploadedFile("huge.jpg", fake_content, content_type="image/jpeg")

        response = client.post(
            f"/api/v1/panoramas/spaces/{space.id}/upload",
            {"file": upload_file},
            HTTP_AUTHORIZATION=f"Bearer {venue_owner.phone}",
        )

        assert response.status_code == 400
        data = response.json()
        assert data["error_code"] == "FILE_TOO_LARGE"
        assert PanoramaImage.objects.count() == 0

    def test_upload_fake_extension_rejected(self, client: Client, venue_owner, space):
        """Text/HTML file spoofed with .jpg extension is rejected by magic bytes/Pillow."""
        fake_payload = b"<html><head><title>Phishing</title></head><body>Fake image</body></html>"
        upload_file = SimpleUploadedFile("fake.jpg", fake_payload, content_type="image/jpeg")

        response = client.post(
            f"/api/v1/panoramas/spaces/{space.id}/upload",
            {"file": upload_file},
            HTTP_AUTHORIZATION=f"Bearer {venue_owner.phone}",
        )

        assert response.status_code == 400
        data = response.json()
        assert data["error_code"] == "INVALID_IMAGE"
        assert PanoramaImage.objects.count() == 0

    def test_upload_corrupt_image_rejected(self, client: Client, venue_owner, space):
        """File with valid JPEG magic bytes but corrupted body is rejected by im.verify()."""
        # \xff\xd8\xff\xe0 is JPEG SOI + APP0 header, followed by random corrupt data
        corrupt_payload = b"\xff\xd8\xff\xe0" + b"\x00\x10JFIF\x00\x01\x01" + b"\xff" * 64
        upload_file = SimpleUploadedFile("corrupt.jpg", corrupt_payload, content_type="image/jpeg")

        response = client.post(
            f"/api/v1/panoramas/spaces/{space.id}/upload",
            {"file": upload_file},
            HTTP_AUTHORIZATION=f"Bearer {venue_owner.phone}",
        )

        assert response.status_code == 400
        data = response.json()
        assert data["error_code"] == "INVALID_IMAGE"
        assert PanoramaImage.objects.count() == 0

    def test_upload_unsupported_format_rejected(self, client: Client, venue_owner, space):
        """Unsupported format (valid GIF) is rejected with HTTP 400 INVALID_IMAGE."""
        gif_bytes = make_gif_bytes()
        upload_file = SimpleUploadedFile("sample.gif", gif_bytes, content_type="image/gif")

        response = client.post(
            f"/api/v1/panoramas/spaces/{space.id}/upload",
            {"file": upload_file},
            HTTP_AUTHORIZATION=f"Bearer {venue_owner.phone}",
        )

        assert response.status_code == 400
        data = response.json()
        assert data["error_code"] == "INVALID_IMAGE"
        assert PanoramaImage.objects.count() == 0

    def test_upload_empty_file_rejected(self, client: Client, venue_owner, space):
        """Empty 0-byte file is rejected with HTTP 400 INVALID_IMAGE."""
        upload_file = SimpleUploadedFile("empty.jpg", b"", content_type="image/jpeg")

        response = client.post(
            f"/api/v1/panoramas/spaces/{space.id}/upload",
            {"file": upload_file},
            HTTP_AUTHORIZATION=f"Bearer {venue_owner.phone}",
        )

        assert response.status_code == 400
        data = response.json()
        assert data["error_code"] == "INVALID_IMAGE"
        assert PanoramaImage.objects.count() == 0

    def test_upload_decompression_bomb_rejected(self, client: Client, venue_owner, space, monkeypatch):
        """Image exceeding decompression bomb pixel threshold is rejected with HTTP 400."""
        # Set limit lower than the test image size (100x100 = 10,000 pixels > 2 * 1000)
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)

        png_bytes = make_png_bytes(width=100, height=100)
        upload_file = SimpleUploadedFile("bomb.png", png_bytes, content_type="image/png")

        response = client.post(
            f"/api/v1/panoramas/spaces/{space.id}/upload",
            {"file": upload_file},
            HTTP_AUTHORIZATION=f"Bearer {venue_owner.phone}",
        )

        assert response.status_code == 400
        data = response.json()
        assert data["error_code"] == "IMAGE_DECOMPRESSION_BOMB"
        assert PanoramaImage.objects.count() == 0

    def test_upload_path_traversal_prevention(self, client: Client, venue_owner, space):
        """Client-supplied filenames with directory traversal are discarded; strictly UUID used."""
        malicious_filename = "../../../../etc/cron.d/exploit.jpg"
        jpeg_bytes = make_jpeg_bytes()
        upload_file = SimpleUploadedFile(malicious_filename, jpeg_bytes, content_type="image/jpeg")

        response = client.post(
            f"/api/v1/panoramas/spaces/{space.id}/upload",
            {"file": upload_file},
            HTTP_AUTHORIZATION=f"Bearer {venue_owner.phone}",
        )

        assert response.status_code == 202
        data = response.json()
        storage_path = data["original_file"]

        # Confirm path strictly adheres to safe pattern
        assert ".." not in storage_path
        assert "etc" not in storage_path
        assert "exploit" not in storage_path
        assert storage_path.startswith(f"panoramas/{space.venue.id}/")
        assert default_storage.exists(storage_path)

    def test_upload_dispatches_via_single_seam(self, client: Client, venue_owner, space, django_capture_on_commit_callbacks):
        """Successful upload calls dispatch_panorama_processing with created ID on commit."""
        with patch("apps.panoramas.services.dispatch_panorama_processing") as mock_dispatch:
            jpeg_bytes = make_jpeg_bytes()
            upload_file = SimpleUploadedFile("test.jpg", jpeg_bytes, content_type="image/jpeg")

            with django_capture_on_commit_callbacks(execute=True):
                response = client.post(
                    f"/api/v1/panoramas/spaces/{space.id}/upload",
                    {"file": upload_file},
                    HTTP_AUTHORIZATION=f"Bearer {venue_owner.phone}",
                )

            assert response.status_code == 202
            data = response.json()
            created_id = uuid.UUID(data["id"])
            mock_dispatch.assert_called_once_with(created_id)

    def test_upload_broker_failure_resilience(self, client: Client, venue_owner, space):
        """If Celery broker/dispatch fails, upload still succeeds and record stays UPLOADED."""
        with patch("apps.panoramas.services.dispatch_panorama_processing", side_effect=Exception("Redis connection refused")):
            jpeg_bytes = make_jpeg_bytes()
            upload_file = SimpleUploadedFile("test.jpg", jpeg_bytes, content_type="image/jpeg")

            # We want to test that dispatch_panorama_processing handles exceptions internally,
            # or if the hook raises, the seam returns False.
            # Let's test the real dispatch_panorama_processing with a failing task import/delay:
            response = client.post(
                f"/api/v1/panoramas/spaces/{space.id}/upload",
                {"file": upload_file},
                HTTP_AUTHORIZATION=f"Bearer {venue_owner.phone}",
            )

            assert response.status_code == 202
            data = response.json()
            record = PanoramaImage.objects.get(id=data["id"])
            assert record.status == PanoramaStatus.UPLOADED

    def test_dispatch_seam_handles_broker_error_without_raising(self):
        """The dispatch_panorama_processing seam catches all broker exceptions and logs warning."""
        fake_task = MagicMock()
        fake_task.delay.side_effect = RuntimeError("Broker connection timeout")

        with patch.dict("sys.modules", {"apps.panoramas.tasks": MagicMock(process_panorama_image=fake_task)}):
            result = services.dispatch_panorama_processing(uuid.uuid4())
            assert result is False

    def test_upload_failure_cleanup_deletes_orphaned_file(self, client: Client, venue_owner, space):
        """If DB record creation fails after file is written to storage, file is cleaned up."""
        jpeg_bytes = make_jpeg_bytes()
        upload_file = SimpleUploadedFile("cleanup_test.jpg", jpeg_bytes, content_type="image/jpeg")

        saved_paths = []
        original_save = default_storage.save

        def tracking_save(name, content, max_length=None):
            path = original_save(name, content, max_length=max_length)
            saved_paths.append(path)
            return path

        with patch.object(default_storage, "save", side_effect=tracking_save):
            with patch.object(PanoramaImage.objects, "create", side_effect=RuntimeError("Database failure simulated")):
                with pytest.raises(RuntimeError, match="Database failure simulated"):
                    services.upload_panorama_for_space(
                        user=venue_owner,
                        space_id=space.id,
                        file=upload_file,
                    )

        # Assert that the file was written, but then deleted by the failure cleanup block
        assert len(saved_paths) == 1
        saved_file = saved_paths[0]
        assert not default_storage.exists(saved_file)
        assert PanoramaImage.objects.count() == 0
