"""Integration and unit tests for Space CRUD and Public Space Read APIs (Task T-018b).

Covers:
1. Owner Space Creation:
   - POST /api/v1/venues/{venue_id}/spaces/
   - Owner/admin auth, IDOR check, field validation (name, display_order >= 0), extra field forbidding.
2. Owner Space Listing:
   - GET /api/v1/venues/{venue_id}/spaces/
   - Returns all spaces (active and inactive) ordered by display_order.
3. Dual-Purpose Space Detail:
   - GET /api/v1/spaces/{space_id}/
   - Owner/admin sees space regardless of status.
   - Public/customer/foreign owner only sees space if BR-005 holds and is_active=True (otherwise 404 zero leak).
4. Owner Space Update:
   - PATCH /api/v1/spaces/{space_id}/ and PUT
   - Partial updates, validation, IDOR check.
5. Owner Explicit Deactivation:
   - POST /api/v1/spaces/{space_id}/deactivate/
6. Deletion Semantics (T-015 Policy):
   - DELETE /api/v1/spaces/{space_id}/
   - No pins & no panoramas -> 204 hard deleted from DB.
   - Associated pins or panoramas (no bookings) -> 200 soft deactivated (remains in DB).
   - Associated pins with bookings -> 409 TABLE_PIN_PROTECTED (remains in DB).
7. Public Space Listing:
   - GET /api/v1/venues/{slug}/spaces/
   - Gated by BR-005: active spaces only for approved venues with active subscription (otherwise 404).
8. Model Unit Tests:
   - Space.delete() and Space.deactivate() methods.
"""
from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache
from django.db.models import ProtectedError
from django.test import Client

from apps.accounts.models import UserRole
from apps.bookings.tests.factories import BookingFactory
from apps.panoramas.models import PanoramaStatus, Space
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
def admin_user():
    return UserFactory(role=UserRole.ADMIN, is_staff=True)


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
def unapproved_venue(venue_owner):
    venue = VenueFactory(
        owner=venue_owner,
        is_approved=False,
    )
    activate_test_subscription(venue)
    return venue


@pytest.fixture
def inactive_sub_venue(venue_owner):
    return VenueFactory(
        owner=venue_owner,
        is_approved=True,
    )


@pytest.fixture
def space(venue):
    return SpaceFactory(
        venue=venue,
        name="Main Dining Room",
        description="Spacious hall with natural light",
        display_order=1,
        is_active=True,
    )


# ==============================================================================
# 1. Owner Space Creation Tests
# ==============================================================================

@pytest.mark.django_db
class TestSpaceCreation:
    """POST /api/v1/venues/{venue_id}/spaces/"""

    def test_owner_can_create_space(self, client: Client, venue_owner, venue):
        """Owner can create a space under their venue."""
        url = f"/api/v1/venues/{venue.id}/spaces/"
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}
        payload = {
            "name": "Garden Terrace",
            "description": "Outdoor open-air seating area",
            "display_order": 2,
            "is_active": True,
        }

        resp = client.post(url, payload, content_type="application/json", **auth)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Garden Terrace"
        assert data["description"] == "Outdoor open-air seating area"
        assert data["display_order"] == 2
        assert data["is_active"] is True
        assert data["venue_id"] == venue.id
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

        # Check DB persistence
        space_db = Space.objects.get(id=data["id"])
        assert space_db.venue == venue
        assert space_db.name == "Garden Terrace"
        assert space_db.display_order == 2

    def test_admin_can_create_space(self, client: Client, admin_user, venue):
        """Platform admin can create a space under any venue."""
        url = f"/api/v1/venues/{venue.id}/spaces/"
        authenticate_client(client, admin_user)
        auth: dict[str, Any] = {}
        payload = {"name": "Admin Created Hall"}

        resp = client.post(url, payload, content_type="application/json", **auth)
        assert resp.status_code == 201
        assert resp.json()["name"] == "Admin Created Hall"

    def test_create_space_unauthenticated_returns_401(self, client: Client, venue):
        """Unauthenticated caller receives 401."""
        url = f"/api/v1/venues/{venue.id}/spaces/"
        resp = client.post(url, {"name": "Terrace"}, content_type="application/json")
        assert resp.status_code == 401

    def test_create_space_customer_returns_403(self, client: Client, customer_user, venue):
        """Customer cannot create spaces (403 Forbidden)."""
        url = f"/api/v1/venues/{venue.id}/spaces/"
        authenticate_client(client, customer_user)
        auth: dict[str, Any] = {}
        resp = client.post(url, {"name": "Terrace"}, content_type="application/json", **auth)
        assert resp.status_code == 403

    def test_create_space_foreign_owner_returns_403(self, client: Client, other_owner, venue):
        """Owner B cannot create a space in Owner A's venue (IDOR protection)."""
        url = f"/api/v1/venues/{venue.id}/spaces/"
        authenticate_client(client, other_owner)
        auth: dict[str, Any] = {}
        resp = client.post(url, {"name": "Stolen Space"}, content_type="application/json", **auth)
        assert resp.status_code == 403

    def test_create_space_nonexistent_venue_returns_404(self, client: Client, venue_owner):
        """Non-existent venue id returns 404."""
        url = "/api/v1/venues/999999/spaces/"
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}
        resp = client.post(url, {"name": "Space"}, content_type="application/json", **auth)
        assert resp.status_code == 404

    def test_create_space_empty_or_whitespace_name_returns_422(self, client: Client, venue_owner, venue):
        """Empty or blank space name returns 422 VALIDATION_ERROR."""
        url = f"/api/v1/venues/{venue.id}/spaces/"
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}

        resp1 = client.post(url, {"name": ""}, content_type="application/json", **auth)
        assert resp1.status_code == 422

        resp2 = client.post(url, {"name": "    "}, content_type="application/json", **auth)
        assert resp2.status_code == 422

    def test_create_space_oversized_name_returns_422(self, client: Client, venue_owner, venue):
        """Name exceeding 100 characters returns 422."""
        url = f"/api/v1/venues/{venue.id}/spaces/"
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}
        resp = client.post(url, {"name": "A" * 101}, content_type="application/json", **auth)
        assert resp.status_code == 422

    def test_create_space_negative_display_order_returns_422(self, client: Client, venue_owner, venue):
        """Negative display order returns 422."""
        url = f"/api/v1/venues/{venue.id}/spaces/"
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}
        resp = client.post(url, {"name": "Terrace", "display_order": -5}, content_type="application/json", **auth)
        assert resp.status_code == 422

    def test_create_space_forbids_extra_fields(self, client: Client, venue_owner, venue):
        """Unknown extra fields in payload return 422."""
        url = f"/api/v1/venues/{venue.id}/spaces/"
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}
        resp = client.post(
            url,
            {"name": "Terrace", "unknown_field": "injected"},
            content_type="application/json",
            **auth,
        )
        assert resp.status_code == 422

    def test_create_space_strips_name(self, client: Client, venue_owner, venue):
        """Leading and trailing whitespace in name is stripped."""
        url = f"/api/v1/venues/{venue.id}/spaces/"
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}
        resp = client.post(url, {"name": "  Cozy Lounge  "}, content_type="application/json", **auth)
        assert resp.status_code == 201
        assert resp.json()["name"] == "Cozy Lounge"


# ==============================================================================
# 2. Owner Space Listing Tests
# ==============================================================================

@pytest.mark.django_db
class TestOwnerSpaceListing:
    """GET /api/v1/venues/{venue_id}/spaces/"""

    def test_owner_can_list_spaces(self, client: Client, venue_owner, venue):
        """Owner receives all spaces in their venue, including inactive ones, ordered properly."""
        s1 = SpaceFactory(venue=venue, name="B Hall", display_order=2, is_active=True)
        s2 = SpaceFactory(venue=venue, name="A Hall", display_order=1, is_active=False)

        url = f"/api/v1/venues/{venue.id}/spaces/"
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}
        resp = client.get(url, **auth)

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        # s2 has display_order 1, s1 has display_order 2
        assert data[0]["id"] == s2.id
        assert data[0]["is_active"] is False
        assert data[1]["id"] == s1.id
        assert data[1]["is_active"] is True

    def test_list_spaces_unauthenticated_returns_401(self, client: Client, venue):
        """Unauthenticated call to integer venue_id returns 401."""
        url = f"/api/v1/venues/{venue.id}/spaces/"
        resp = client.get(url)
        assert resp.status_code == 401

    def test_list_spaces_foreign_owner_returns_403(self, client: Client, other_owner, venue):
        """Foreign owner cannot list another owner's spaces via venue_id."""
        url = f"/api/v1/venues/{venue.id}/spaces/"
        authenticate_client(client, other_owner)
        auth: dict[str, Any] = {}
        resp = client.get(url, **auth)
        assert resp.status_code == 403


# ==============================================================================
# 3. Dual-Purpose Space Detail Tests
# ==============================================================================

@pytest.mark.django_db
class TestSpaceDetailDualPurpose:
    """GET /api/v1/spaces/{space_id}/"""

    def test_owner_can_get_inactive_space(self, client: Client, venue_owner, venue):
        """Owner can view their own space even when is_active=False."""
        inactive_space = SpaceFactory(venue=venue, is_active=False, name="Hidden Space")
        url = f"/api/v1/spaces/{inactive_space.id}/"
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}

        resp = client.get(url, **auth)
        assert resp.status_code == 200
        assert resp.json()["id"] == inactive_space.id
        assert resp.json()["is_active"] is False

    def test_admin_can_get_any_space(self, client: Client, admin_user, venue):
        """Platform admin can view any space."""
        s = SpaceFactory(venue=venue, is_active=False)
        url = f"/api/v1/spaces/{s.id}/"
        authenticate_client(client, admin_user)
        auth: dict[str, Any] = {}

        resp = client.get(url, **auth)
        assert resp.status_code == 200
        assert resp.json()["id"] == s.id

    def test_public_can_get_active_space_when_br005_satisfied(self, client: Client, space):
        """Public (unauthenticated) user can view active space in approved+active venue."""
        url = f"/api/v1/spaces/{space.id}/"
        resp = client.get(url)

        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == space.id
        assert data["name"] == space.name

    def test_public_gets_404_when_space_is_inactive(self, client: Client, venue):
        """Public gets 404 when space is inactive (zero info leak)."""
        inactive_space = SpaceFactory(venue=venue, is_active=False)
        url = f"/api/v1/spaces/{inactive_space.id}/"
        resp = client.get(url)
        assert resp.status_code == 404

    def test_public_gets_404_when_venue_unapproved(self, client: Client, unapproved_venue):
        """Public gets 404 when venue is not approved."""
        s = SpaceFactory(venue=unapproved_venue, is_active=True)
        url = f"/api/v1/spaces/{s.id}/"
        resp = client.get(url)
        assert resp.status_code == 404

    def test_public_gets_404_when_venue_subscription_inactive(self, client: Client, inactive_sub_venue):
        """Public gets 404 when venue subscription is inactive."""
        s = SpaceFactory(venue=inactive_sub_venue, is_active=True)
        url = f"/api/v1/spaces/{s.id}/"
        resp = client.get(url)
        assert resp.status_code == 404

    def test_customer_gets_404_when_space_inactive(self, client: Client, customer_user, venue):
        """Authenticated customer gets 404 when space is inactive."""
        inactive_space = SpaceFactory(venue=venue, is_active=False)
        url = f"/api/v1/spaces/{inactive_space.id}/"
        authenticate_client(client, customer_user)
        auth: dict[str, Any] = {}

        resp = client.get(url, **auth)
        assert resp.status_code == 404

    def test_foreign_owner_gets_404_when_space_inactive(self, client: Client, other_owner, venue):
        """Foreign owner gets 404 when target space is inactive (treated as public)."""
        inactive_space = SpaceFactory(venue=venue, is_active=False)
        url = f"/api/v1/spaces/{inactive_space.id}/"
        authenticate_client(client, other_owner)
        auth: dict[str, Any] = {}

        resp = client.get(url, **auth)
        assert resp.status_code == 404

    def test_get_space_detail_bounded_queries(self, client: Client, space, django_assert_num_queries):
        """Single space detail uses bounded queries with select_related and subscription EXISTS (zero N+1)."""
        url = f"/api/v1/spaces/{space.id}/"
        with django_assert_num_queries(2):
            resp = client.get(url)
            assert resp.status_code == 200


# ==============================================================================
# 4. Owner Space Update Tests
# ==============================================================================

@pytest.mark.django_db
class TestSpaceUpdate:
    """PATCH & PUT /api/v1/spaces/{space_id}/"""

    def test_owner_can_patch_space(self, client: Client, venue_owner, space):
        """Owner can partially update space fields."""
        url = f"/api/v1/spaces/{space.id}/"
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}
        payload = {"name": "Renovated Hall", "display_order": 10}

        resp = client.patch(url, payload, content_type="application/json", **auth)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Renovated Hall"
        assert data["display_order"] == 10
        assert data["description"] == space.description  # Unchanged

        space.refresh_from_db()
        assert space.name == "Renovated Hall"
        assert space.display_order == 10

    def test_owner_can_put_space(self, client: Client, venue_owner, space):
        """Owner can update space fields via PUT."""
        url = f"/api/v1/spaces/{space.id}/"
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}
        payload = {"name": "Full Put Space", "description": "Updated via PUT", "display_order": 5}

        resp = client.put(url, payload, content_type="application/json", **auth)
        assert resp.status_code == 200
        assert resp.json()["name"] == "Full Put Space"

    def test_patch_space_foreign_owner_returns_403(self, client: Client, other_owner, space):
        """Foreign owner cannot update another owner's space (403 Forbidden)."""
        url = f"/api/v1/spaces/{space.id}/"
        authenticate_client(client, other_owner)
        auth: dict[str, Any] = {}
        resp = client.patch(url, {"name": "Hacked"}, content_type="application/json", **auth)
        assert resp.status_code == 403

    def test_patch_space_validation_errors(self, client: Client, venue_owner, space):
        """Invalid fields in PATCH are rejected."""
        url = f"/api/v1/spaces/{space.id}/"
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}

        # Blank name
        resp = client.patch(url, {"name": "   "}, content_type="application/json", **auth)
        assert resp.status_code == 422

        # Negative display_order
        resp2 = client.patch(url, {"display_order": -3}, content_type="application/json", **auth)
        assert resp2.status_code == 422

        # Extra forbidden field
        resp3 = client.patch(url, {"injected": "val"}, content_type="application/json", **auth)
        assert resp3.status_code == 422


# ==============================================================================
# 5. Explicit Deactivation Tests
# ==============================================================================

@pytest.mark.django_db
class TestSpaceDeactivation:
    """POST /api/v1/spaces/{space_id}/deactivate/"""

    def test_owner_can_deactivate_space(self, client: Client, venue_owner, space):
        """Explicit deactivate endpoint marks is_active=False."""
        assert space.is_active is True
        url = f"/api/v1/spaces/{space.id}/deactivate/"
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}

        resp = client.post(url, **auth)
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

        space.refresh_from_db()
        assert space.is_active is False

    def test_deactivate_foreign_owner_returns_403(self, client: Client, other_owner, space):
        """Foreign owner cannot deactivate space."""
        url = f"/api/v1/spaces/{space.id}/deactivate/"
        authenticate_client(client, other_owner)
        auth: dict[str, Any] = {}
        resp = client.post(url, **auth)
        assert resp.status_code == 403


# ==============================================================================
# 6. Deletion Semantics Tests (T-015 Policy)
# ==============================================================================

@pytest.mark.django_db
class TestSpaceDeletionPolicy:
    """DELETE /api/v1/spaces/{space_id}/

    Policy:
    - If pins with bookings exist -> 409 TABLE_PIN_PROTECTED (space remains).
    - If pins or panoramas exist (no bookings) -> deactivates space, returns 200 (space remains).
    - If no pins and no panoramas -> hard-deletes space, returns 204.
    """

    def test_delete_space_without_pins_or_panoramas_hard_deletes(self, client: Client, venue_owner, space):
        """Space with no pins and no panoramas is hard deleted from DB (204 No Content)."""
        space_id = space.id
        url = f"/api/v1/spaces/{space_id}/"
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}

        resp = client.delete(url, **auth)
        assert resp.status_code == 204
        assert not Space.objects.filter(id=space_id).exists()

    def test_delete_space_with_pins_no_bookings_soft_deactivates(self, client: Client, venue_owner, space):
        """Space with table pins (no bookings) is soft-deactivated instead of deleted (200 OK)."""
        TablePinFactory(venue=space.venue, space=space, table_number="T1")
        url = f"/api/v1/spaces/{space.id}/"
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}

        resp = client.delete(url, **auth)
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == space.id
        assert data["is_active"] is False

        # Space remains present in DB with is_active=False
        space.refresh_from_db()
        assert space.is_active is False

    def test_delete_space_with_panoramas_no_bookings_soft_deactivates(self, client: Client, venue_owner, space):
        """Space with panorama images (no bookings) is soft-deactivated (200 OK)."""
        PanoramaImageFactory(space=space, status=PanoramaStatus.UPLOADED)
        url = f"/api/v1/spaces/{space.id}/"
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}

        resp = client.delete(url, **auth)
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

        space.refresh_from_db()
        assert space.is_active is False

    def test_delete_space_with_bookings_fails_safely_protect_409(
        self, client: Client, venue_owner, space, customer_user
    ):
        """ADR-005: Space with pins having booking history cannot be deleted (409 TABLE_PIN_PROTECTED)."""
        pin = TablePinFactory(venue=space.venue, space=space, table_number="T-Booked")
        BookingFactory(venue=space.venue, table_pin=pin, customer=customer_user)

        url = f"/api/v1/spaces/{space.id}/"
        authenticate_client(client, venue_owner)
        auth: dict[str, Any] = {}

        resp = client.delete(url, **auth)
        assert resp.status_code == 409
        assert resp.json()["error_code"] == "TABLE_PIN_PROTECTED"

        # Space remains present and unchanged in DB
        space.refresh_from_db()
        assert Space.objects.filter(id=space.id).exists()

    def test_delete_space_foreign_owner_returns_403(self, client: Client, other_owner, space):
        """Foreign owner cannot delete another owner's space (403 Forbidden)."""
        url = f"/api/v1/spaces/{space.id}/"
        authenticate_client(client, other_owner)
        auth: dict[str, Any] = {}
        resp = client.delete(url, **auth)
        assert resp.status_code == 403


# ==============================================================================
# 7. Public Space Listing by Venue Slug
# ==============================================================================

@pytest.mark.django_db
class TestPublicSpaceListing:
    """GET /api/v1/venues/{slug}/spaces/"""

    def test_public_can_list_active_spaces_under_br005(self, client: Client, venue):
        """Public list returns active spaces only for an approved venue with active subscription."""
        SpaceFactory(venue=venue, name="Active 1", display_order=1, is_active=True)
        SpaceFactory(venue=venue, name="Active 2", display_order=2, is_active=True)
        SpaceFactory(venue=venue, name="Inactive 3", display_order=3, is_active=False)

        url = f"/api/v1/venues/{venue.slug}/spaces/"
        resp = client.get(url)

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        names = [item["name"] for item in data]
        assert "Active 1" in names
        assert "Active 2" in names
        assert "Inactive 3" not in names

    def test_public_list_unapproved_venue_returns_404(self, client: Client, unapproved_venue):
        """Public list on unapproved venue returns 404 (zero info leak)."""
        SpaceFactory(venue=unapproved_venue, is_active=True)
        url = f"/api/v1/venues/{unapproved_venue.slug}/spaces/"
        resp = client.get(url)
        assert resp.status_code == 404

    def test_public_list_inactive_subscription_returns_404(self, client: Client, inactive_sub_venue):
        """Public list on approved venue with inactive subscription returns 404."""
        SpaceFactory(venue=inactive_sub_venue, is_active=True)
        url = f"/api/v1/venues/{inactive_sub_venue.slug}/spaces/"
        resp = client.get(url)
        assert resp.status_code == 404

    def test_public_list_nonexistent_slug_returns_404(self, client: Client):
        """Non-existent venue slug returns 404."""
        url = "/api/v1/venues/nonexistent-cafe-slug/spaces/"
        resp = client.get(url)
        assert resp.status_code == 404

    def test_public_list_spaces_bounded_queries(self, client: Client, venue, django_assert_num_queries):
        """Public list of spaces executes bounded queries without N+1 regression."""
        for i in range(5):
            SpaceFactory(venue=venue, name=f"Bulk Space {i}", display_order=i, is_active=True)

        url = f"/api/v1/venues/{venue.slug}/spaces/"
        with django_assert_num_queries(3):
            resp = client.get(url)
            assert resp.status_code == 200
            assert len(resp.json()) >= 5


# ==============================================================================
# 8. Space Model Unit Tests
# ==============================================================================

@pytest.mark.django_db
class TestSpaceModelMethods:
    """Unit tests for Space.delete() and Space.deactivate()."""

    def test_space_model_deactivate(self, space):
        """Space.deactivate() sets is_active=False and saves."""
        space.deactivate()
        space.refresh_from_db()
        assert space.is_active is False

    def test_space_model_delete_without_bookings_succeeds(self, space):
        """Space.delete() deletes row when no bookings exist."""
        space_id = space.id
        space.delete()
        assert not Space.objects.filter(id=space_id).exists()

    def test_space_model_delete_with_bookings_raises_protected_error(self, space, customer_user):
        """Space.delete() raises ProtectedError when pins have existing bookings."""
        pin = TablePinFactory(venue=space.venue, space=space)
        BookingFactory(venue=space.venue, table_pin=pin, customer=customer_user)

        with pytest.raises(ProtectedError) as exc_info:
            space.delete()

        assert "Cannot delete Space" in str(exc_info.value)
        assert "existing booking history" in str(exc_info.value)
