"""Integration and unit tests for TablePin APIs and Public Panorama Read endpoint (Task T-018).

Endpoints tested:
1. Owner Pin Management:
   - POST   /api/v1/panoramas/spaces/{space_id}/pins (Create pin)
   - GET    /api/v1/panoramas/spaces/{space_id}/pins (List pins)
   - GET    /api/v1/panoramas/pins/{pin_id}          (Get pin)
   - PUT    /api/v1/panoramas/pins/{pin_id}          (Update pin)
   - PATCH  /api/v1/panoramas/pins/{pin_id}          (Partial update pin)
   - POST   /api/v1/panoramas/pins/{pin_id}/deactivate (Deactivate pin)
   - DELETE /api/v1/panoramas/pins/{pin_id}          (Delete pin - guarded by PROTECT)

2. Public Panorama Read:
   - GET /api/v1/spaces/{space_id}/panorama
   - GET /api/v1/panoramas/spaces/{space_id}/panorama (alias)
"""
from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import Client

from apps.accounts.models import UserRole
from apps.bookings.tests.factories import BookingFactory
from apps.panoramas.models import PanoramaStatus, TablePin
from apps.panoramas.tests.factories import PanoramaImageFactory, SpaceFactory, TablePinFactory
from apps.venues.tests.factories import UserFactory, VenueFactory, activate_test_subscription
from core.testing import authenticate_client


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path, settings):
    """Isolate media storage and cache per test run."""
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
    venue = VenueFactory(
        owner=venue_owner,
        is_approved=True,
    )
    activate_test_subscription(venue)
    return venue


@pytest.fixture
def space(venue):
    return SpaceFactory(venue=venue, name="Main Dining Hall", is_active=True)


@pytest.fixture
def ready_panorama(space):
    pano = PanoramaImageFactory(
        space=space,
        status=PanoramaStatus.READY,
        width=4096,
        height=2048,
    )
    pano.webp_file.save("pano.webp", ContentFile(b"fake_webp_bytes"), save=False)
    pano.thumb_file.save("thumb.webp", ContentFile(b"fake_thumb_bytes"), save=False)
    pano.save()
    space.active_panorama = pano
    space.save(update_fields=["active_panorama"])
    return pano


@pytest.mark.django_db
class TestTablePinValidation:
    """Validate pitch, yaw, capacity, and table_number schema validation."""

    def test_create_pin_pitch_bounds(self, client: Client, venue_owner, space):
        """Pitch must be between -90.0 and 90.0 degrees inclusive; out-of-bounds returns 422."""
        url = f"/api/v1/panoramas/spaces/{space.id}/pins"
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}

        # Pitch = 90.1 (too high) -> 422
        resp = client.post(
            url,
            {"table_number": "T1", "capacity": 2, "pitch": 90.1, "yaw": 0.0},
            content_type="application/json",
            **auth,
        )
        assert resp.status_code == 422
        assert resp.json()["error_code"] == "VALIDATION_ERROR"

        # Pitch = -90.1 (too low) -> 422
        resp = client.post(
            url,
            {"table_number": "T1", "capacity": 2, "pitch": -90.1, "yaw": 0.0},
            content_type="application/json",
            **auth,
        )
        assert resp.status_code == 422

        # Boundary values: -90.0 and 90.0 are valid
        resp = client.post(
            url,
            {"table_number": "T-MIN", "capacity": 2, "pitch": -90.0, "yaw": 0.0, "reservation_fee_toman": 50_000},
            content_type="application/json",
            **auth,
        )
        assert resp.status_code == 201

        resp = client.post(
            url,
            {"table_number": "T-MAX", "capacity": 2, "pitch": 90.0, "yaw": 0.0, "reservation_fee_toman": 50_000},
            content_type="application/json",
            **auth,
        )
        assert resp.status_code == 201

    def test_create_pin_yaw_bounds(self, client: Client, venue_owner, space):
        """Yaw must be between -180.0 and 180.0 degrees inclusive; out-of-bounds returns 422."""
        url = f"/api/v1/panoramas/spaces/{space.id}/pins"
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}

        # Yaw = 180.1 -> 422
        resp = client.post(
            url,
            {"table_number": "T1", "capacity": 2, "pitch": 0.0, "yaw": 180.1},
            content_type="application/json",
            **auth,
        )
        assert resp.status_code == 422

        # Yaw = -180.1 -> 422
        resp = client.post(
            url,
            {"table_number": "T1", "capacity": 2, "pitch": 0.0, "yaw": -180.1},
            content_type="application/json",
            **auth,
        )
        assert resp.status_code == 422

        # Boundary values: -180.0 and 180.0 are valid
        resp = client.post(
            url,
            {"table_number": "Y-MIN", "capacity": 2, "pitch": 0.0, "yaw": -180.0, "reservation_fee_toman": 50_000},
            content_type="application/json",
            **auth,
        )
        assert resp.status_code == 201

        resp = client.post(
            url,
            {"table_number": "Y-MAX", "capacity": 2, "pitch": 0.0, "yaw": 180.0, "reservation_fee_toman": 50_000},
            content_type="application/json",
            **auth,
        )
        assert resp.status_code == 201

    def test_create_pin_rejects_nan_and_inf(self, client: Client, venue_owner, space):
        """Pydantic schema must reject NaN and Infinity."""
        url = f"/api/v1/panoramas/spaces/{space.id}/pins"
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}

        # Test NaN in JSON
        payload = '{"table_number": "T-NAN", "capacity": 2, "pitch": NaN, "yaw": 0.0}'
        resp = client.post(url, payload, content_type="application/json", **auth)
        assert resp.status_code == 422

        # Test Infinity in JSON
        payload = '{"table_number": "T-INF", "capacity": 2, "pitch": Infinity, "yaw": 0.0}'
        resp = client.post(url, payload, content_type="application/json", **auth)
        assert resp.status_code == 422

    def test_pydantic_schema_direct_validation(self):
        """Direct unit test on Pydantic schemas for NaN, Inf, and bounds."""
        from pydantic import ValidationError

        from apps.panoramas.schemas import TablePinCreateIn, TablePinUpdateIn

        # Valid instances
        c = TablePinCreateIn(table_number="T1", capacity=4, pitch=-90.0, yaw=180.0, reservation_fee_toman=50_000)
        assert c.pitch == -90.0
        assert c.yaw == 180.0

        # NaN pitch rejected
        with pytest.raises(ValidationError):
            TablePinCreateIn(table_number="T1", capacity=2, pitch=float("nan"), reservation_fee_toman=50_000)

        # Inf yaw rejected
        with pytest.raises(ValidationError):
            TablePinCreateIn(table_number="T1", capacity=2, yaw=float("inf"), reservation_fee_toman=50_000)

        # Negative Inf yaw rejected
        with pytest.raises(ValidationError):
            TablePinCreateIn(table_number="T1", capacity=2, yaw=float("-inf"), reservation_fee_toman=50_000)

        # Capacity 0 rejected
        with pytest.raises(ValidationError):
            TablePinCreateIn(table_number="T1", capacity=0, reservation_fee_toman=50_000)

        # Update schema NaN rejected
        with pytest.raises(ValidationError):
            TablePinUpdateIn(pitch=float("nan"))

    def test_create_pin_capacity_validation(self, client: Client, venue_owner, space):
        """Capacity must be strictly positive (> 0); 0 or negative returns 422."""
        url = f"/api/v1/panoramas/spaces/{space.id}/pins"
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}

        resp = client.post(
            url,
            {"table_number": "T-CAP0", "capacity": 0, "pitch": 0.0, "yaw": 0.0},
            content_type="application/json",
            **auth,
        )
        assert resp.status_code == 422

        resp = client.post(
            url,
            {"table_number": "T-CAPNEG", "capacity": -2, "pitch": 0.0, "yaw": 0.0},
            content_type="application/json",
            **auth,
        )
        assert resp.status_code == 422

    def test_create_pin_blank_table_number(self, client: Client, venue_owner, space):
        """Table number cannot be blank or whitespace."""
        url = f"/api/v1/panoramas/spaces/{space.id}/pins"
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}

        resp = client.post(
            url,
            {"table_number": "   ", "capacity": 2, "pitch": 0.0, "yaw": 0.0},
            content_type="application/json",
            **auth,
        )
        assert resp.status_code == 422

    def test_table_pin_capacity_boolean_rejected_422(self, client: Client, venue_owner: Any, space: Any) -> None:
        """Boolean capacity (true) must be rejected with 422 on create and update."""
        authenticate_client(client, venue_owner)
        create_url = f"/api/v1/panoramas/spaces/{space.id}/pins"

        resp = client.post(
            create_url,
            '{"table_number": "T-BOOL", "capacity": true, "pitch": 0.0, "yaw": 0.0, "reservation_fee_toman": 50000}',
            content_type="application/json",
        )
        assert resp.status_code == 422

        pin = TablePinFactory(venue=space.venue, space=space)
        update_url = f"/api/v1/panoramas/pins/{pin.id}"
        resp = client.patch(
            update_url,
            '{"capacity": true}',
            content_type="application/json",
        )
        assert resp.status_code == 422

    def test_table_pin_reservation_fee_bigint_bounds(self, client: Client, venue_owner: Any, space: Any) -> None:
        """reservation_fee_toman enforces PostgreSQL signed 64-bit integer max."""
        authenticate_client(client, venue_owner)
        create_url = f"/api/v1/panoramas/spaces/{space.id}/pins"
        max_bigint = 9_223_372_036_854_775_807
        over_bigint = 9_223_372_036_854_775_808

        resp = client.post(
            create_url,
            {"table_number": "T-OVER", "capacity": 2, "pitch": 0.0, "yaw": 0.0, "reservation_fee_toman": over_bigint},
            content_type="application/json",
        )
        assert resp.status_code == 422

        resp = client.post(
            create_url,
            {"table_number": "T-MAXB", "capacity": 2, "pitch": 0.0, "yaw": 0.0, "reservation_fee_toman": max_bigint},
            content_type="application/json",
        )
        assert resp.status_code == 201
        pin_id = resp.json()["id"]

        update_url = f"/api/v1/panoramas/pins/{pin_id}"
        resp = client.patch(
            update_url,
            {"reservation_fee_toman": over_bigint},
            content_type="application/json",
        )
        assert resp.status_code == 422

        resp = client.patch(
            update_url,
            {"reservation_fee_toman": max_bigint},
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["reservation_fee_toman"] == max_bigint

    def test_table_pin_capacity_negative_rejected_422(self, client: Client, venue_owner: Any, space: Any) -> None:
        """Negative capacity (-1) must be rejected with 422 on create and update."""
        authenticate_client(client, venue_owner)
        create_url = f"/api/v1/panoramas/spaces/{space.id}/pins"

        resp = client.post(
            create_url,
            {"table_number": "T-NEG", "capacity": -1, "pitch": 0.0, "yaw": 0.0, "reservation_fee_toman": 50_000},
            content_type="application/json",
        )
        assert resp.status_code == 422

        pin = TablePinFactory(venue=space.venue, space=space)
        resp = client.patch(
            f"/api/v1/panoramas/pins/{pin.id}",
            {"capacity": -1},
            content_type="application/json",
        )
        assert resp.status_code == 422


@pytest.mark.django_db
class TestTablePinPermissions:
    """Verify authentication, role checks, and IDOR protection."""

    def test_unauthenticated_request_returns_401(self, client: Client, space):
        """Requests without credentials return HTTP 401."""
        resp = client.post(
            f"/api/v1/panoramas/spaces/{space.id}/pins",
            {"table_number": "T1", "capacity": 2},
            content_type="application/json",
        )
        assert resp.status_code == 401

    def test_customer_role_returns_403(self, client: Client, customer_user, space):
        """Customer cannot create or manage pins -> HTTP 403."""
        authenticate_client(client, customer_user)
        resp = client.post(
            f"/api/v1/panoramas/spaces/{space.id}/pins",
            {"table_number": "T1", "capacity": 2, "reservation_fee_toman": 50_000},
            content_type="application/json",
        )
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "FORBIDDEN"

    def test_foreign_owner_cannot_create_pin(self, client: Client, other_owner, space):
        """Owner B cannot create pins in Owner A's venue/space -> HTTP 403."""
        authenticate_client(client, other_owner)
        resp = client.post(
            f"/api/v1/panoramas/spaces/{space.id}/pins",
            {"table_number": "T1", "capacity": 2, "reservation_fee_toman": 50_000},
            content_type="application/json",
        )
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "FORBIDDEN"

    def test_foreign_owner_cannot_update_or_delete_pin(self, client: Client, other_owner, space):
        """Owner B cannot update, deactivate, or delete Owner A's pins -> HTTP 403."""
        pin = TablePinFactory(space=space, venue=space.venue, table_number="T1")

        authenticate_client(client, other_owner)
        auth: dict[str, Any] = {}

        # Update
        resp = client.put(
            f"/api/v1/panoramas/pins/{pin.id}",
            {"table_number": "T1-MOD"},
            content_type="application/json",
            **auth,
        )
        assert resp.status_code == 403

        # Deactivate
        resp = client.post(f"/api/v1/panoramas/pins/{pin.id}/deactivate", **auth)
        assert resp.status_code == 403

        # Delete
        resp = client.delete(f"/api/v1/panoramas/pins/{pin.id}", **auth)
        assert resp.status_code == 403

    def test_nonexistent_space_or_pin_returns_404(self, client: Client, venue_owner):
        """Non-existent space or pin returns HTTP 404."""
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}

        resp = client.post(
            "/api/v1/panoramas/spaces/999999/pins",
            {"table_number": "T1", "capacity": 2, "reservation_fee_toman": 50_000},
            content_type="application/json",
            **auth,
        )
        assert resp.status_code == 404

        resp = client.get("/api/v1/panoramas/pins/999999", **auth)
        assert resp.status_code == 404


@pytest.mark.django_db
class TestTablePinCRUD:
    """Owner TablePin CRUD operations, venue derivation, and conflict handling."""

    def test_create_pin_derives_venue_server_side(self, client: Client, venue_owner, space, ready_panorama):
        """Pin's venue is derived server-side from space.venue, never from client input."""
        url = f"/api/v1/panoramas/spaces/{space.id}/pins"
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}

        resp = client.post(
            url,
            {
                "table_number": "Booth 1",
                "capacity": 4,
                "pitch": 15.5,
                "yaw": -30.0,
                "panorama_image_id": str(ready_panorama.id),
                "description": "Cozy corner booth",
                "reservation_fee_toman": 50_000,
                "is_active": True,
            },
            content_type="application/json",
            **auth,
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["table_number"] == "Booth 1"
        assert data["capacity"] == 4
        assert data["venue_id"] == space.venue.id
        assert data["space_id"] == space.id
        assert data["pitch"] == 15.5
        assert data["yaw"] == -30.0
        assert data["is_active"] is True

        # Verify DB persistence
        pin = TablePin.objects.get(id=data["id"])
        assert pin.venue == space.venue
        assert pin.space == space
        assert pin.panorama_image == ready_panorama

    def test_create_duplicate_table_number_in_same_venue_returns_409(self, client: Client, venue_owner, space):
        """Duplicate table_number within the same venue returns HTTP 409 TABLE_NUMBER_ALREADY_EXISTS."""
        TablePinFactory(venue=space.venue, space=space, table_number="Table 5")

        url = f"/api/v1/panoramas/spaces/{space.id}/pins"
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}

        resp = client.post(
            url,
            {"table_number": "Table 5", "capacity": 2, "reservation_fee_toman": 50_000},
            content_type="application/json",
            **auth,
        )
        assert resp.status_code == 409
        assert resp.json()["error_code"] == "TABLE_NUMBER_ALREADY_EXISTS"

    def test_owner_can_list_and_get_pins(self, client: Client, venue_owner, space):
        """Owner can retrieve pin details and list pins in their space."""
        pin1 = TablePinFactory(venue=space.venue, space=space, table_number="A1")
        TablePinFactory(venue=space.venue, space=space, table_number="A2")

        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}

        # List
        resp = client.get(f"/api/v1/panoramas/spaces/{space.id}/pins", **auth)
        assert resp.status_code == 200
        pin_numbers = [p["table_number"] for p in resp.json()]
        assert "A1" in pin_numbers
        assert "A2" in pin_numbers

        # Get single
        resp = client.get(f"/api/v1/panoramas/pins/{pin1.id}", **auth)
        assert resp.status_code == 200
        assert resp.json()["id"] == pin1.id
        assert resp.json()["table_number"] == "A1"

    def test_owner_can_update_pin(self, client: Client, venue_owner, space):
        """Owner can update coordinates, capacity, table_number, and description."""
        pin = TablePinFactory(venue=space.venue, space=space, table_number="OldNumber", capacity=2)
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}

        # PUT
        resp = client.put(
            f"/api/v1/panoramas/pins/{pin.id}",
            {
                "table_number": "NewNumber",
                "capacity": 6,
                "pitch": -45.0,
                "yaw": 90.0,
                "description": "Updated view",
            },
            content_type="application/json",
            **auth,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["table_number"] == "NewNumber"
        assert data["capacity"] == 6
        assert data["pitch"] == -45.0
        assert data["yaw"] == 90.0

        pin.refresh_from_db()
        assert pin.table_number == "NewNumber"
        assert pin.capacity == 6

        # PATCH
        resp = client.patch(
            f"/api/v1/panoramas/pins/{pin.id}",
            {"description": "Patched description"},
            content_type="application/json",
            **auth,
        )
        assert resp.status_code == 200
        pin.refresh_from_db()
        assert pin.description == "Patched description"

    def test_deactivate_pin_endpoint(self, client: Client, venue_owner, space):
        """POST /api/v1/panoramas/pins/{pin_id}/deactivate sets is_active=False."""
        pin = TablePinFactory(venue=space.venue, space=space, is_active=True)
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}

        resp = client.post(f"/api/v1/panoramas/pins/{pin.id}/deactivate", **auth)
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

        pin.refresh_from_db()
        assert pin.is_active is False

    def test_delete_pin_without_bookings_succeeds(self, client: Client, venue_owner, space):
        """Pin without bookings is hard-deleted with HTTP 204 No Content."""
        pin = TablePinFactory(venue=space.venue, space=space)
        pin_id = pin.id
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}

        resp = client.delete(f"/api/v1/panoramas/pins/{pin_id}", **auth)
        assert resp.status_code == 204
        assert not TablePin.objects.filter(id=pin_id).exists()

    def test_delete_pin_with_bookings_fails_safely_protect(self, client: Client, venue_owner, space, customer_user):
        """ADR-005: Pin with existing bookings cannot be deleted (returns 409 TABLE_PIN_PROTECTED)."""
        pin = TablePinFactory(venue=space.venue, space=space)
        BookingFactory(
            venue=space.venue,
            table_pin=pin,
            customer=customer_user,
        )

        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}

        resp = client.delete(f"/api/v1/panoramas/pins/{pin.id}", **auth)
        assert resp.status_code == 409
        data = resp.json()
        assert data["error_code"] == "TABLE_PIN_PROTECTED"
        assert "Deactivate it instead" in data["message"]

        # Ensure pin still exists in DB
        assert TablePin.objects.filter(id=pin.id).exists()


@pytest.mark.django_db
class TestPublicPanoramaReadEndpoint:
    """Test public panorama read endpoint under /spaces and /panoramas (BR-005)."""

    def test_public_panorama_happy_path(self, client: Client, space, ready_panorama):
        """Public read returns WebP image URL and active pins (200 OK)."""
        active_pin_1 = TablePinFactory(venue=space.venue, space=space, table_number="T1", is_active=True)
        active_pin_2 = TablePinFactory(venue=space.venue, space=space, table_number="T2", is_active=True)
        inactive_pin = TablePinFactory(venue=space.venue, space=space, table_number="T3", is_active=False)

        # 1. Test direct route: /api/v1/spaces/{space_id}/panorama
        resp = client.get(f"/api/v1/spaces/{space.id}/panorama")
        assert resp.status_code == 200
        data = resp.json()

        assert data["space_id"] == space.id
        assert data["space_name"] == space.name
        assert data["venue_id"] == space.venue.id
        assert data["venue_name"] == space.venue.name
        assert data["panorama_image_id"] == str(ready_panorama.id)
        assert data["image_url"].endswith(".webp")
        assert data["thumbnail_url"].endswith(".webp")

        # Pins check: only active pins present
        returned_pin_ids = [p["id"] for p in data["pins"]]
        assert active_pin_1.id in returned_pin_ids
        assert active_pin_2.id in returned_pin_ids
        assert inactive_pin.id not in returned_pin_ids

        # Never expose original_file
        assert "original_file" not in data

        # 2. Test alias route: /api/v1/panoramas/spaces/{space_id}/panorama
        resp_alias = client.get(f"/api/v1/panoramas/spaces/{space.id}/panorama")
        assert resp_alias.status_code == 200
        assert resp_alias.json() == data

    def test_unapproved_venue_returns_404_zero_leak(self, client: Client, space, ready_panorama):
        """BR-005: Unapproved venue returns 404 with zero info leak."""
        space.venue.is_approved = False
        space.venue.save(update_fields=["is_approved"])

        resp = client.get(f"/api/v1/spaces/{space.id}/panorama")
        assert resp.status_code == 404
        assert resp.json()["error_code"] == "NOT_FOUND"

    def test_inactive_subscription_returns_404(self, client: Client, space, ready_panorama):
        """BR-005: Inactive/expired subscription returns 404."""
        space.venue.venue_subscriptions.all().delete()

        resp = client.get(f"/api/v1/spaces/{space.id}/panorama")
        assert resp.status_code == 404

    def test_inactive_space_returns_404(self, client: Client, space, ready_panorama):
        """Inactive space returns 404."""
        space.is_active = False
        space.save(update_fields=["is_active"])

        resp = client.get(f"/api/v1/spaces/{space.id}/panorama")
        assert resp.status_code == 404

    def test_no_ready_panorama_returns_404(self, client: Client, space):
        """Space without a READY panorama returns 404."""
        # Create a panorama in UPLOADED or PROCESSING status
        PanoramaImageFactory(space=space, status=PanoramaStatus.UPLOADED)

        resp = client.get(f"/api/v1/spaces/{space.id}/panorama")
        assert resp.status_code == 404

    def test_single_bounded_query_no_n_plus_one(self, client: Client, space, ready_panorama, django_assert_num_queries):
        """Verify endpoint uses a bounded query count (no N+1 when loading pins)."""
        # Create 10 active pins
        for i in range(10):
            TablePinFactory(venue=space.venue, space=space, table_number=f"T-P{i}", is_active=True)

        # Query count must stay bounded (space/venue + active subscription EXISTS + active_pano + pins)
        with django_assert_num_queries(4):
            resp = client.get(f"/api/v1/spaces/{space.id}/panorama")
            assert resp.status_code == 200
            assert len(resp.json()["pins"]) == 10

    def test_public_panorama_fallback_to_latest_ready_if_active_panorama_none(self, client: Client, space):
        """When space.active_panorama is None, endpoint falls back to the latest READY panorama."""
        space.active_panorama = None
        space.save(update_fields=["active_panorama"])

        pano = PanoramaImageFactory(
            space=space,
            status=PanoramaStatus.READY,
            width=4096,
            height=2048,
        )
        pano.webp_file.save("fallback.webp", ContentFile(b"fake_webp"), save=True)

        resp = client.get(f"/api/v1/spaces/{space.id}/panorama")
        assert resp.status_code == 200
        data = resp.json()
        assert data["panorama_image_id"] == str(pano.id)
        assert data["image_url"].endswith(".webp")

    def test_public_panorama_filters_pins_by_panorama_image_id(self, client: Client, space, ready_panorama):
        """Pins assigned to a specific panorama are only returned when that panorama is viewed."""
        other_pano = PanoramaImageFactory(
            space=space,
            status=PanoramaStatus.READY,
            width=4096,
            height=2048,
        )
        other_pano.webp_file.save("other.webp", ContentFile(b"other"), save=True)

        # Pin for ready_panorama
        pin_for_current = TablePinFactory(
            venue=space.venue,
            space=space,
            table_number="CurrentPanoPin",
            panorama_image=ready_panorama,
            is_active=True,
        )
        # Pin for other_pano
        pin_for_other = TablePinFactory(
            venue=space.venue,
            space=space,
            table_number="OtherPanoPin",
            panorama_image=other_pano,
            is_active=True,
        )
        # Pin with no specific panorama (space-wide)
        pin_space_wide = TablePinFactory(
            venue=space.venue,
            space=space,
            table_number="SpaceWidePin",
            panorama_image=None,
            is_active=True,
        )

        resp = client.get(f"/api/v1/spaces/{space.id}/panorama")
        assert resp.status_code == 200
        returned_pin_ids = [p["id"] for p in resp.json()["pins"]]

        assert pin_for_current.id in returned_pin_ids
        assert pin_space_wide.id in returned_pin_ids
        assert pin_for_other.id not in returned_pin_ids

    def test_update_duplicate_table_number_returns_409(self, client: Client, venue_owner, space):
        """Updating table_number to one that already exists in the venue returns 409."""
        TablePinFactory(venue=space.venue, space=space, table_number="Table Alpha")
        pin = TablePinFactory(venue=space.venue, space=space, table_number="Table Beta")
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}

        resp = client.put(
            f"/api/v1/panoramas/pins/{pin.id}",
            {"table_number": "Table Alpha"},
            content_type="application/json",
            **auth,
        )
        assert resp.status_code == 409
        assert resp.json()["error_code"] == "TABLE_NUMBER_ALREADY_EXISTS"

    def test_create_and_update_pin_reject_extra_fields(
        self, client: Client, venue_owner: Any, space: Any
    ) -> None:
        """Extra fields in TablePinCreateIn and TablePinUpdateIn return 422 (extra='forbid')."""
        authenticate_client(client, venue_owner)

        create_resp = client.post(
            f"/api/v1/panoramas/spaces/{space.id}/pins",
            {
                "table_number": "T-EXTRA",
                "capacity": 2,
                "reservation_fee_toman": 50_000,
                "unexpected_field": "forbid_me",
            },
            content_type="application/json",
        )
        assert create_resp.status_code == 422

        pin = TablePinFactory(venue=space.venue, space=space, table_number="T-STRICT")
        update_resp = client.put(
            f"/api/v1/panoramas/pins/{pin.id}",
            {"capacity": 4, "unexpected_field": "forbid_me"},
            content_type="application/json",
        )
        assert update_resp.status_code == 422
