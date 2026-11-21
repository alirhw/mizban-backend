"""Tests for TablePin fields: reservation_fee_toman and is_smoking (FR-004 gap fix, pre-T-021).

Verifies:
1. Model constraints:
   - CheckConstraint rejects negative reservation_fee_toman at DB level
   - Model validation (full_clean) rejects negative reservation_fee_toman
   - is_smoking defaults to False
   - Zero and positive fees are permitted
2. Owner API:
   - POST /api/v1/panoramas/spaces/{space_id}/pins with fee 120_000 and is_smoking True returns both fields
   - POST without reservation_fee_toman returns 422 VALIDATION_ERROR
   - POST with negative reservation_fee_toman returns 422 VALIDATION_ERROR
   - PATCH /api/v1/panoramas/pins/{pin_id} updates only provided fields
   - Foreign owner returns 403 FORBIDDEN
   - Unauthenticated returns 401
3. Public API:
   - GET /api/v1/spaces/{space_id}/panorama returns reservation_fee_toman and is_smoking for active pins
   - Inactive pins and unapproved venues return 404 with zero info leakage
4. Booking lock integration:
   - Locking a pin priced at 120_000 creates a Booking with amount_online_toman == 120_000 (not 50_000)
   - Pin left at the 50_000 migration default creates a Booking with amount_online_toman == 50_000
"""
from datetime import date, time, timedelta
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.test import Client
from django.utils import timezone
import pytest

from apps.accounts.models import UserRole
from apps.bookings.services import create_booking_lock
from apps.panoramas.models import PanoramaImage, PanoramaStatus, Space, TablePin
from apps.panoramas.tests.factories import PanoramaImageFactory, SpaceFactory, TablePinFactory
from apps.venues.models import SubscriptionStatus
from apps.venues.tests.factories import UserFactory, VenueFactory


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path, settings):
    settings.DEBUG = True
    settings.MEDIA_ROOT = tmp_path
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def venue_owner():
    return UserFactory(role=UserRole.VENUE_OWNER)


@pytest.fixture
def other_owner():
    return UserFactory(role=UserRole.VENUE_OWNER)


@pytest.fixture
def customer_user():
    return UserFactory(role=UserRole.CUSTOMER)


@pytest.fixture
def venue(venue_owner):
    return VenueFactory(
        owner=venue_owner,
        is_approved=True,
        subscription_status=SubscriptionStatus.ACTIVE,
    )


@pytest.fixture
def space(venue):
    return SpaceFactory(venue=venue, is_active=True)


@pytest.fixture
def ready_panorama(space):
    pano = PanoramaImageFactory(
        space=space,
        status=PanoramaStatus.READY,
        width=4096,
        height=2048,
    )
    fake_webp = b"RIFF\x24\x00\x00\x00WEBPVP8 \x18\x00\x00\x00\x30\x01\x00\x9d\x01\x2a\x01\x00\x01\x00\x02\x00\x34\x25\xa4\x00\x03\x70\x00\xfe\xfb\xfd\xb5\x00"
    pano.webp_file.save("panorama_ready.webp", ContentFile(fake_webp), save=False)
    pano.thumb_file.save("panorama_thumb.webp", ContentFile(fake_webp), save=False)
    pano.save(update_fields=["webp_file", "thumb_file"])
    space.active_panorama = pano
    space.save(update_fields=["active_panorama", "updated_at"])
    return pano


# -----------------------------------------------------------------------------
# 1. Model Constraints
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestTablePinFieldModelConstraints:
    def test_negative_fee_rejected_at_db_level(self, space):
        """Database CheckConstraint table_pin_reservation_fee_non_negative rejects fee < 0."""
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                TablePin.objects.create(
                    venue=space.venue,
                    space=space,
                    table_number="T-NEG",
                    capacity=4,
                    reservation_fee_toman=-1000,
                    is_smoking=False,
                )

    def test_negative_fee_rejected_at_model_validation(self, space):
        """Model full_clean() validator rejects negative reservation_fee_toman."""
        pin = TablePin(
            venue=space.venue,
            space=space,
            table_number="T-NEG2",
            capacity=4,
            reservation_fee_toman=-500,
            is_smoking=False,
        )
        with pytest.raises(ValidationError) as exc:
            pin.full_clean()
        assert "reservation_fee_toman" in exc.value.message_dict

    def test_is_smoking_defaults_to_false(self, space):
        """is_smoking defaults to False when omitted in model creation."""
        pin = TablePin.objects.create(
            venue=space.venue,
            space=space,
            table_number="T-DEFAULT",
            capacity=2,
            reservation_fee_toman=60_000,
        )
        assert pin.is_smoking is False

    def test_zero_fee_allowed(self, space):
        """A fee of 0 Toman is valid (e.g. promotional or zero reservation fee table)."""
        pin = TablePin.objects.create(
            venue=space.venue,
            space=space,
            table_number="T-FREE",
            capacity=2,
            reservation_fee_toman=0,
            is_smoking=True,
        )
        assert pin.reservation_fee_toman == 0
        assert pin.is_smoking is True

    def test_positive_fee_and_smoking_persisted(self, space):
        """Positive fee and is_smoking=True persist cleanly."""
        pin = TablePin.objects.create(
            venue=space.venue,
            space=space,
            table_number="T-VIP",
            capacity=6,
            reservation_fee_toman=150_000,
            is_smoking=True,
        )
        pin.refresh_from_db()
        assert pin.reservation_fee_toman == 150_000
        assert pin.is_smoking is True


# -----------------------------------------------------------------------------
# 2. Owner API (Create / Patch / Scoping / Auth)
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestTablePinOwnerAPI:
    def test_create_pin_with_fee_and_smoking(self, client: Client, venue_owner, space, ready_panorama):
        """Creating a pin with fee 120_000 and is_smoking True returns 201 with both fields."""
        url = f"/api/v1/panoramas/spaces/{space.id}/pins"
        auth = {"HTTP_AUTHORIZATION": f"Bearer {venue_owner.phone}"}
        payload = {
            "table_number": "VIP-1",
            "capacity": 4,
            "pitch": 12.0,
            "yaw": 45.0,
            "panorama_image_id": str(ready_panorama.id),
            "description": "VIP table by balcony",
            "reservation_fee_toman": 120_000,
            "is_smoking": True,
            "is_active": True,
        }
        resp = client.post(url, payload, content_type="application/json", **auth)
        assert resp.status_code == 201
        data = resp.json()
        assert data["table_number"] == "VIP-1"
        assert data["reservation_fee_toman"] == 120_000
        assert data["is_smoking"] is True

        pin = TablePin.objects.get(id=data["id"])
        assert pin.reservation_fee_toman == 120_000
        assert pin.is_smoking is True

    def test_create_pin_without_fee_returns_422(self, client: Client, venue_owner, space):
        """POST without reservation_fee_toman returns 422 VALIDATION_ERROR."""
        url = f"/api/v1/panoramas/spaces/{space.id}/pins"
        auth = {"HTTP_AUTHORIZATION": f"Bearer {venue_owner.phone}"}
        payload = {
            "table_number": "T-NOFEE",
            "capacity": 2,
            "pitch": 0.0,
            "yaw": 0.0,
        }
        resp = client.post(url, payload, content_type="application/json", **auth)
        assert resp.status_code == 422
        assert resp.json()["error_code"] == "VALIDATION_ERROR"

    def test_create_pin_with_negative_fee_returns_422(self, client: Client, venue_owner, space):
        """POST with negative reservation_fee_toman returns 422 VALIDATION_ERROR."""
        url = f"/api/v1/panoramas/spaces/{space.id}/pins"
        auth = {"HTTP_AUTHORIZATION": f"Bearer {venue_owner.phone}"}
        payload = {
            "table_number": "T-NEGFEE",
            "capacity": 2,
            "pitch": 0.0,
            "yaw": 0.0,
            "reservation_fee_toman": -50_000,
        }
        resp = client.post(url, payload, content_type="application/json", **auth)
        assert resp.status_code == 422
        assert resp.json()["error_code"] == "VALIDATION_ERROR"

    def test_patch_fee_and_smoking_updates_only_those_fields(self, client: Client, venue_owner, space):
        """PATCH fee and is_smoking updates only those fields, preserving coordinates and metadata."""
        pin = TablePinFactory(
            venue=space.venue,
            space=space,
            table_number="T-ORIG",
            capacity=4,
            pitch=25.0,
            yaw=-60.0,
            description="Original description",
            reservation_fee_toman=50_000,
            is_smoking=False,
        )
        url = f"/api/v1/panoramas/pins/{pin.id}"
        auth = {"HTTP_AUTHORIZATION": f"Bearer {venue_owner.phone}"}

        resp = client.patch(
            url,
            {"reservation_fee_toman": 180_000, "is_smoking": True},
            content_type="application/json",
            **auth,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["reservation_fee_toman"] == 180_000
        assert data["is_smoking"] is True
        assert data["table_number"] == "T-ORIG"
        assert data["capacity"] == 4
        assert data["pitch"] == 25.0
        assert data["yaw"] == -60.0
        assert data["description"] == "Original description"

        pin.refresh_from_db()
        assert pin.reservation_fee_toman == 180_000
        assert pin.is_smoking is True

    def test_patch_only_fee_preserves_smoking(self, client: Client, venue_owner, space):
        """PATCH only reservation_fee_toman does not alter is_smoking."""
        pin = TablePinFactory(
            venue=space.venue,
            space=space,
            reservation_fee_toman=50_000,
            is_smoking=True,
        )
        url = f"/api/v1/panoramas/pins/{pin.id}"
        auth = {"HTTP_AUTHORIZATION": f"Bearer {venue_owner.phone}"}

        resp = client.patch(url, {"reservation_fee_toman": 95_000}, content_type="application/json", **auth)
        assert resp.status_code == 200
        pin.refresh_from_db()
        assert pin.reservation_fee_toman == 95_000
        assert pin.is_smoking is True

    def test_patch_negative_fee_returns_422(self, client: Client, venue_owner, space):
        """PATCH with negative reservation_fee_toman returns 422."""
        pin = TablePinFactory(venue=space.venue, space=space, reservation_fee_toman=50_000)
        url = f"/api/v1/panoramas/pins/{pin.id}"
        auth = {"HTTP_AUTHORIZATION": f"Bearer {venue_owner.phone}"}

        resp = client.patch(url, {"reservation_fee_toman": -1}, content_type="application/json", **auth)
        assert resp.status_code == 422

    def test_foreign_owner_cannot_patch_pin(self, client: Client, other_owner, space):
        """Owner B cannot PATCH Owner A's pin -> HTTP 403."""
        pin = TablePinFactory(venue=space.venue, space=space, reservation_fee_toman=50_000)
        url = f"/api/v1/panoramas/pins/{pin.id}"
        auth = {"HTTP_AUTHORIZATION": f"Bearer {other_owner.phone}"}

        resp = client.patch(url, {"reservation_fee_toman": 200_000}, content_type="application/json", **auth)
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "FORBIDDEN"

    def test_unauthenticated_request_returns_401(self, client: Client, space):
        """Unauthenticated requests return HTTP 401."""
        resp = client.post(
            f"/api/v1/panoramas/spaces/{space.id}/pins",
            {"table_number": "T1", "reservation_fee_toman": 50_000},
            content_type="application/json",
        )
        assert resp.status_code == 401


# -----------------------------------------------------------------------------
# 3. Public API (GET /api/v1/spaces/{space_id}/panorama)
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestTablePinPublicAPI:
    def test_public_panorama_returns_fee_and_smoking(self, client: Client, space, ready_panorama):
        """Public panorama endpoint exposes reservation_fee_toman and is_smoking for active pins."""
        pin1 = TablePinFactory(
            venue=space.venue,
            space=space,
            panorama_image=ready_panorama,
            table_number="T1",
            reservation_fee_toman=110_000,
            is_smoking=False,
            is_active=True,
        )
        pin2 = TablePinFactory(
            venue=space.venue,
            space=space,
            panorama_image=ready_panorama,
            table_number="T2",
            reservation_fee_toman=75_000,
            is_smoking=True,
            is_active=True,
        )
        # Inactive pin should be excluded
        TablePinFactory(
            venue=space.venue,
            space=space,
            panorama_image=ready_panorama,
            table_number="T-INACTIVE",
            reservation_fee_toman=200_000,
            is_active=False,
        )

        resp = client.get(f"/api/v1/spaces/{space.id}/panorama")
        assert resp.status_code == 200
        data = resp.json()
        pins = {p["table_number"]: p for p in data["pins"]}

        assert "T1" in pins
        assert pins["T1"]["reservation_fee_toman"] == 110_000
        assert pins["T1"]["is_smoking"] is False

        assert "T2" in pins
        assert pins["T2"]["reservation_fee_toman"] == 75_000
        assert pins["T2"]["is_smoking"] is True

        assert "T-INACTIVE" not in pins

    def test_unapproved_venue_returns_404_no_leak(self, client: Client, space, ready_panorama):
        """Unapproved venue returns 404 with zero info leakage."""
        space.venue.is_approved = False
        space.venue.save(update_fields=["is_approved"])

        TablePinFactory(venue=space.venue, space=space, reservation_fee_toman=100_000)
        resp = client.get(f"/api/v1/spaces/{space.id}/panorama")
        assert resp.status_code == 404


# -----------------------------------------------------------------------------
# 4. Booking Lock Integration
# -----------------------------------------------------------------------------


@pytest.mark.django_db
class TestTablePinBookingLockIntegration:
    def test_locking_pin_priced_at_120k_creates_booking_with_120k(self, customer_user, space):
        """Locking a pin priced at 120_000 creates Booking with amount_online_toman == 120_000."""
        pin = TablePinFactory(
            venue=space.venue,
            space=space,
            table_number="T-120K",
            capacity=4,
            reservation_fee_toman=120_000,
            is_smoking=False,
            is_active=True,
        )
        future_date = date(2026, 12, 1)
        slot_time = time(18, 0)
        now_dt = timezone.make_aware(timezone.datetime(2026, 11, 21, 10, 0))

        booking = create_booking_lock(
            user=customer_user,
            table_pin=pin,
            slot_date=future_date,
            slot_start_time=slot_time,
            addon_ids=[],
            now=now_dt,
        )
        assert booking.amount_online_toman == 120_000
        assert booking.amount_online_toman != 50_000

    def test_locking_pin_with_migration_default_creates_booking_with_50k(self, customer_user, space):
        """Pin left at migration default (50,000) books at 50,000."""
        pin = TablePinFactory(
            venue=space.venue,
            space=space,
            table_number="T-DEF",
            capacity=2,
            reservation_fee_toman=50_000,
            is_smoking=False,
            is_active=True,
        )
        future_date = date(2026, 12, 1)
        slot_time = time(20, 0)
        now_dt = timezone.make_aware(timezone.datetime(2026, 11, 21, 10, 0))

        booking = create_booking_lock(
            user=customer_user,
            table_pin=pin,
            slot_date=future_date,
            slot_start_time=slot_time,
            addon_ids=[],
            now=now_dt,
        )
        assert booking.amount_online_toman == 50_000
