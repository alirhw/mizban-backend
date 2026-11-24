"""Tests for Venue Owner APIs, Admin Approval, and Cache Invalidation (Task T-009).

Acceptance criteria from spec & task:
1. Public endpoints exclude unapproved / inactive venues (BR-005).
2. Public responses never expose owner phone numbers (NFR-005).
3. Owner CRUD: owner lists/creates/views/updates their own venue.
4. IDOR prevention: Owner A cannot view or edit Owner B's venue (403).
5. Role enforcement: Customer cannot create or edit venues (403).
6. Mass assignment protection: Owner cannot self-approve a venue.
7. Admin approval: Admin can approve/reject venues; non-admin gets 403.
8. Cache invalidation: Public venue cache (TTL 3600s) is invalidated on edit and approval.
"""
from __future__ import annotations

import json

from django.core.cache import cache
from django.test import Client, override_settings
import pytest

from apps.accounts.models import UserRole
from apps.venues.models import SubscriptionStatus, Venue
from core.testing import authenticate_client
from apps.venues.services import (
    VENUE_CACHE_TTL,
    get_venue_cache_key,
    get_venue_slug_cache_key,
)
from apps.venues.tests.factories import (
    DesignAddonFactory,
    OperatingHoursFactory,
    UserFactory,
    VenueFactory,
    activate_test_subscription,
)


class ApiHelper:
    def __init__(self, client: Client):
        self.client = client

    def get(self, path: str, user=None):
        if user:
            authenticate_client(self.client, user)
        else:
            self.client.logout()
        return self.client.get(path)

    def post(self, path: str, data=None, user=None):
        if user:
            authenticate_client(self.client, user)
        else:
            self.client.logout()
        if data is not None:
            return self.client.post(path, data=json.dumps(data), content_type="application/json")
        return self.client.post(path)

    def put(self, path: str, data=None, user=None):
        if user:
            authenticate_client(self.client, user)
        else:
            self.client.logout()
        if data is not None:
            return self.client.put(path, data=json.dumps(data), content_type="application/json")
        return self.client.put(path)


@pytest.fixture(autouse=True)
def setup_test_env(settings):
    settings.DEBUG = True
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def api(client):
    return ApiHelper(client)


@pytest.fixture
def owner_user():
    return UserFactory(role=UserRole.VENUE_OWNER)


@pytest.fixture
def other_owner_user():
    return UserFactory(role=UserRole.VENUE_OWNER)


@pytest.fixture
def customer_user():
    return UserFactory(role=UserRole.CUSTOMER)


@pytest.fixture
def admin_user():
    return UserFactory(role=UserRole.ADMIN, is_staff=True)


# ---------------------------------------------------------------------------
# 1. Public Catalogue & Exclusion Tests (BR-005, NFR-005)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_public_venues_list_excludes_unapproved_and_inactive(api):
    """BR-005: Only is_approved=True AND subscription_status=ACTIVE venues appear."""
    approved_active = VenueFactory(
        name="Visible Cafe",
        slug="visible-cafe",
        is_approved=True,
    )
    activate_test_subscription(approved_active)
    unapproved = VenueFactory(
        name="Hidden Cafe Unapproved",
        slug="hidden-cafe",
        is_approved=False,
    )
    activate_test_subscription(unapproved)
    inactive_sub = VenueFactory(
        name="Hidden Cafe Inactive",
        slug="inactive-cafe",
        is_approved=True,
    )

    response = api.get("/api/v1/venues/")
    assert response.status_code == 200
    data = response.json()

    slugs = [v["slug"] for v in data]
    assert approved_active.slug in slugs
    assert unapproved.slug not in slugs
    assert inactive_sub.slug not in slugs


@pytest.mark.django_db
def test_public_venues_response_never_exposes_owner_phone(api):
    """NFR-005 / Privacy: Public listing and detail MUST NOT leak owner phone numbers."""
    owner = UserFactory(phone="09129998877", role=UserRole.VENUE_OWNER)
    venue = VenueFactory(
        owner=owner,
        is_approved=True,
    )
    activate_test_subscription(venue)
    OperatingHoursFactory(venue=venue)
    DesignAddonFactory(venue=venue)

    # 1. Check list response
    list_resp = api.get("/api/v1/venues/")
    assert list_resp.status_code == 200
    assert "09129998877" not in list_resp.content.decode()

    # 2. Check detail response
    detail_resp = api.get(f"/api/v1/venues/{venue.slug}")
    assert detail_resp.status_code == 200
    assert "09129998877" not in detail_resp.content.decode()
    item = detail_resp.json()
    assert "phone" not in item
    assert "owner" not in item


@pytest.mark.django_db
def test_public_venue_detail_unapproved_returns_404(api):
    """Unapproved venue must not be viewable on public detail endpoint."""
    venue = VenueFactory(
        is_approved=False,
    )
    activate_test_subscription(venue)
    response = api.get(f"/api/v1/venues/{venue.slug}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 2. Owner CRUD & IDOR Prevention Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_owner_can_create_venue(api, owner_user):
    """Owner can create a venue; it defaults to is_approved=False."""
    payload = {
        "name": "Cafe Golha",
        "city": "Tehran",
        "venue_type": "CAFE",
        "address": "Valiasr St",
        "description": "Cozy cafe with plants",
        "slug": "cafe-golha",
    }
    response = api.post(
        "/api/v1/venues/owner/venues",
        data=payload,
        user=owner_user,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Cafe Golha"
    assert data["slug"] == "cafe-golha"
    assert data["is_approved"] is False
    assert data["subscription_status"] == SubscriptionStatus.INACTIVE

    venue = Venue.objects.get(id=data["id"])
    assert venue.owner == owner_user
    assert venue.is_approved is False


@pytest.mark.django_db
def test_customer_cannot_create_venue(api, customer_user):
    """Role enforcement: CUSTOMER cannot create venues."""
    payload = {
        "name": "Customer Cafe",
        "city": "Tehran",
        "venue_type": "CAFE",
        "address": "Street 1",
    }
    response = api.post(
        "/api/v1/venues/owner/venues",
        data=payload,
        user=customer_user,
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_owner_can_list_own_venues_only(api, owner_user, other_owner_user):
    """Owner list endpoint only returns venues owned by the caller."""
    my_venue = VenueFactory(owner=owner_user, name="My Venue")
    other_venue = VenueFactory(owner=other_owner_user, name="Other Venue")

    response = api.get(
        "/api/v1/venues/owner/venues",
        user=owner_user,
    )
    assert response.status_code == 200
    ids = [v["id"] for v in response.json()]
    assert my_venue.id in ids
    assert other_venue.id not in ids


@pytest.mark.django_db
def test_owner_cannot_view_other_owners_venue_idor(api, owner_user, other_owner_user):
    """IDOR prevention: Owner A cannot GET Owner B's venue."""
    other_venue = VenueFactory(owner=other_owner_user)

    response = api.get(
        f"/api/v1/venues/owner/venues/{other_venue.id}",
        user=owner_user,
    )
    assert response.status_code == 403


@pytest.mark.django_db
def test_owner_cannot_update_other_owners_venue_idor(api, owner_user, other_owner_user):
    """IDOR prevention: Owner A cannot PUT/update Owner B's venue."""
    other_venue = VenueFactory(owner=other_owner_user, name="Original Name")

    response = api.put(
        f"/api/v1/venues/owner/venues/{other_venue.id}",
        data={"name": "Hacked Name"},
        user=owner_user,
    )
    assert response.status_code == 403
    other_venue.refresh_from_db()
    assert other_venue.name == "Original Name"


@pytest.mark.django_db
def test_owner_cannot_self_approve_venue_via_update(api, owner_user):
    """Mass assignment protection: Owner cannot pass is_approved to approve themselves."""
    venue = VenueFactory(owner=owner_user, is_approved=False)

    response = api.put(
        f"/api/v1/venues/owner/venues/{venue.id}",
        data={"name": "Updated Name", "is_approved": True},
        user=owner_user,
    )
    assert response.status_code == 200
    venue.refresh_from_db()
    assert venue.name == "Updated Name"
    assert venue.is_approved is False


# ---------------------------------------------------------------------------
# 3. Admin Approval Workflow Tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_admin_can_approve_and_reject_venue(api, admin_user, owner_user):
    """Admin can approve a venue, setting is_approved=True, and reject it back."""
    venue = VenueFactory(owner=owner_user, is_approved=False)

    # 1. Approve
    approve_resp = api.post(
        f"/api/v1/venues/admin/venues/{venue.id}/approve",
        user=admin_user,
    )
    assert approve_resp.status_code == 200
    venue.refresh_from_db()
    assert venue.is_approved is True

    # 2. Reject
    reject_resp = api.post(
        f"/api/v1/venues/admin/venues/{venue.id}/reject",
        user=admin_user,
    )
    assert reject_resp.status_code == 200
    venue.refresh_from_db()
    assert venue.is_approved is False


@pytest.mark.django_db
def test_owner_cannot_call_admin_approval_endpoint(api, owner_user):
    """Non-admin caller receives 403 Forbidden when calling approval endpoint."""
    venue = VenueFactory(owner=owner_user, is_approved=False)

    response = api.post(
        f"/api/v1/venues/admin/venues/{venue.id}/approve",
        user=owner_user,
    )
    assert response.status_code == 403
    venue.refresh_from_db()
    assert venue.is_approved is False


# ---------------------------------------------------------------------------
# 4. Cache and Cache Invalidation Tests (TTL 3600s, on_commit)
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_public_venue_detail_caching_and_invalidation_on_update(api, owner_user):
    """Public detail is cached for 3600s and invalidated when owner updates the venue."""
    venue = VenueFactory(
        owner=owner_user,
        name="Cached Cafe",
        slug="cached-cafe",
        is_approved=True,
    )
    activate_test_subscription(venue)
    cache_key = get_venue_slug_cache_key(venue.slug)

    # 1. Initial request populates cache
    assert cache.get(cache_key) is None
    resp1 = api.get(f"/api/v1/venues/{venue.slug}")
    assert resp1.status_code == 200
    assert cache.get(cache_key) is not None
    assert cache.get(cache_key)["name"] == "Cached Cafe"

    # 2. Owner updates venue -> cache is invalidated
    update_resp = api.put(
        f"/api/v1/venues/owner/venues/{venue.id}",
        data={"name": "New Cached Name"},
        user=owner_user,
    )
    assert update_resp.status_code == 200
    assert cache.get(cache_key) is None

    # 3. Next public request gets the updated name and re-caches it
    resp2 = api.get(f"/api/v1/venues/{venue.slug}")
    assert resp2.status_code == 200
    assert resp2.json()["name"] == "New Cached Name"
    assert cache.get(cache_key)["name"] == "New Cached Name"


@pytest.mark.django_db(transaction=True)
def test_cache_invalidation_on_admin_approval(api, admin_user, owner_user):
    """Admin approval invalidates cache."""
    venue = VenueFactory(
        owner=owner_user,
        slug="approval-cafe",
        is_approved=False,
    )
    activate_test_subscription(venue)
    cache_key = get_venue_slug_cache_key(venue.slug)

    # Prime cache manually to simulate any state
    cache.set(cache_key, {"name": "Old State"}, timeout=VENUE_CACHE_TTL)
    assert cache.get(cache_key) is not None

    # Admin approves venue
    resp = api.post(
        f"/api/v1/venues/admin/venues/{venue.id}/approve",
        user=admin_user,
    )
    assert resp.status_code == 200

    # Cache should be cleared
    assert cache.get(cache_key) is None

    # Now publicly accessible
    pub_resp = api.get(f"/api/v1/venues/{venue.slug}")
    assert pub_resp.status_code == 200
    assert pub_resp.json()["name"] == venue.name


@pytest.mark.django_db
def test_owner_api_rejects_debug_auth_bridge_when_debug_false(client, owner_user):
    """Bearer-phone lookup is completely removed and returns 401 Unauthorized."""
    with override_settings(DEBUG=False):
        resp = client.get(
            "/api/v1/venues/owner/venues",
            HTTP_AUTHORIZATION=f"Bearer {owner_user.phone}",
        )
        assert resp.status_code == 401

