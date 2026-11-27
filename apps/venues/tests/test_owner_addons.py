"""Tests for Venue Owner Design Add-on CRUD, BR-15 snapshots, and cache invalidation (T-035)."""
from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.bookings.models import BookingAddon
from apps.bookings.services import create_booking_lock
from apps.panoramas.tests.factories import TablePinFactory
from apps.venues.models import DesignAddon
from apps.venues.services import get_venue_slug_cache_key
from apps.venues.tests.factories import (
    DesignAddonFactory,
    UserFactory,
    VenueFactory,
    activate_test_subscription,
)
from core.testing import authenticate_client


class ApiHelper:
    """Thin test client wrapper authenticating requests as a given user."""

    def __init__(self, client: Client) -> None:
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

    def delete(self, path: str, user=None):
        if user:
            authenticate_client(self.client, user)
        else:
            self.client.logout()
        return self.client.delete(path)


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


def _addons_url(venue_id: int) -> str:
    return f"/api/v1/venues/owner/venues/{venue_id}/addons/"


def _addon_detail_url(venue_id: int, addon_id: int) -> str:
    return f"/api/v1/venues/owner/venues/{venue_id}/addons/{addon_id}/"


@pytest.mark.django_db(transaction=True)
def test_create_addon_happy_path(api, owner_user):
    """POST creates add-on with is_active=True default and exposes it in owner list and public detail."""
    venue = VenueFactory(owner=owner_user, is_approved=True, slug="addon-happy-cafe")
    activate_test_subscription(venue)

    resp = api.post(
        _addons_url(venue.id),
        data={"title": "Rose Bouquet", "fee": 250_000},
        user=owner_user,
    )
    assert resp.status_code == 201
    created = resp.json()
    assert created["title"] == "Rose Bouquet"
    assert created["fee"] == 250_000
    assert created["is_active"] is True
    assert isinstance(created["id"], int)

    owner_list = api.get(_addons_url(venue.id), user=owner_user)
    assert owner_list.status_code == 200
    assert [a["id"] for a in owner_list.json()] == [created["id"]]

    public_detail = api.get(f"/api/v1/venues/{venue.slug}")
    assert public_detail.status_code == 200
    public_addons = public_detail.json()["design_addons"]
    assert len(public_addons) == 1
    assert public_addons[0]["id"] == created["id"]
    assert public_addons[0]["title"] == "Rose Bouquet"
    assert public_addons[0]["fee"] == 250_000


@pytest.mark.django_db
def test_create_addon_with_zero_fee(api, owner_user):
    """Free add-on (fee=0) is allowed (DB constraint is fee >= 0)."""
    venue = VenueFactory(owner=owner_user)

    resp = api.post(
        _addons_url(venue.id),
        data={"title": "Complimentary Candle", "fee": 0},
        user=owner_user,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["fee"] == 0
    assert DesignAddon.objects.filter(id=body["id"], fee=0).exists()


@pytest.mark.django_db
def test_create_addon_with_negative_fee_rejected(api, owner_user):
    """Negative fee (-1) returns 422 and creates no add-on."""
    venue = VenueFactory(owner=owner_user)

    resp = api.post(
        _addons_url(venue.id),
        data={"title": "Invalid Fee Addon", "fee": -1},
        user=owner_user,
    )
    assert resp.status_code == 422
    assert DesignAddon.objects.filter(venue=venue).count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("blank_title", ["", "   "])
def test_create_addon_with_blank_title_rejected(api, owner_user, blank_title):
    """Empty or whitespace-only title returns 422 and creates no add-on."""
    venue = VenueFactory(owner=owner_user)

    resp = api.post(
        _addons_url(venue.id),
        data={"title": blank_title, "fee": 50_000},
        user=owner_user,
    )
    assert resp.status_code == 422
    assert DesignAddon.objects.filter(venue=venue).count() == 0


@pytest.mark.django_db
def test_create_addon_other_owner_403_and_nonexistent_404(api, owner_user, other_owner_user):
    """Creating on another owner's venue returns 403; nonexistent venue returns 404."""
    other_venue = VenueFactory(owner=other_owner_user)

    forbidden_resp = api.post(
        _addons_url(other_venue.id),
        data={"title": "Sneaky Addon", "fee": 10_000},
        user=owner_user,
    )
    assert forbidden_resp.status_code == 403
    assert DesignAddon.objects.filter(venue=other_venue).count() == 0

    not_found_resp = api.post(
        _addons_url(9_999_999),
        data={"title": "Ghost Addon", "fee": 10_000},
        user=owner_user,
    )
    assert not_found_resp.status_code == 404


@pytest.mark.django_db
def test_list_owner_addons_returns_only_own_including_inactive_ordered_by_title(
    api, owner_user, other_owner_user
):
    """Owner list returns only that venue's add-ons (active & inactive), ordered by title."""
    venue = VenueFactory(owner=owner_user)
    other_venue = VenueFactory(owner=other_owner_user)

    addon_z = DesignAddonFactory(venue=venue, title="Zebra Decor", fee=30_000, is_active=True)
    addon_a = DesignAddonFactory(venue=venue, title="Alpha Candles", fee=20_000, is_active=False)
    addon_m = DesignAddonFactory(venue=venue, title="Middle Flowers", fee=40_000, is_active=True)
    DesignAddonFactory(venue=other_venue, title="Foreign Addon", fee=50_000, is_active=True)

    resp = api.get(_addons_url(venue.id), user=owner_user)
    assert resp.status_code == 200
    items = resp.json()
    assert [item["id"] for item in items] == [addon_a.id, addon_m.id, addon_z.id]
    assert [item["is_active"] for item in items] == [False, True, True]


@pytest.mark.django_db(transaction=True)
def test_update_and_get_addon_detail(api, owner_user):
    """PUT updates title/fee/is_active, persists to DB, GET detail works, public detail shows new fee."""
    venue = VenueFactory(owner=owner_user, is_approved=True, slug="addon-update-cafe")
    activate_test_subscription(venue)
    addon = DesignAddonFactory(venue=venue, title="Old Title", fee=100_000, is_active=True)

    detail_resp = api.get(_addon_detail_url(venue.id, addon.id), user=owner_user)
    assert detail_resp.status_code == 200
    assert detail_resp.json()["title"] == "Old Title"

    update_resp = api.put(
        _addon_detail_url(venue.id, addon.id),
        data={"title": "Updated Title", "fee": 175_000, "is_active": True},
        user=owner_user,
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["title"] == "Updated Title"
    assert updated["fee"] == 175_000
    assert updated["is_active"] is True

    addon.refresh_from_db()
    assert addon.title == "Updated Title"
    assert addon.fee == 175_000

    public_detail = api.get(f"/api/v1/venues/{venue.slug}")
    assert public_detail.status_code == 200
    assert public_detail.json()["design_addons"][0]["fee"] == 175_000


@pytest.mark.django_db
def test_update_other_owners_addon_403_and_404(api, owner_user, other_owner_user):
    """Updating another owner's venue returns 403; targeting own venue with another's addon_id returns 404."""
    own_venue = VenueFactory(owner=owner_user)
    other_venue = VenueFactory(owner=other_owner_user)
    other_addon = DesignAddonFactory(venue=other_venue, title="Protected Addon", fee=90_000)

    forbidden_resp = api.put(
        _addon_detail_url(other_venue.id, other_addon.id),
        data={"title": "Hacked", "fee": 1, "is_active": True},
        user=owner_user,
    )
    assert forbidden_resp.status_code == 403

    not_found_resp = api.put(
        _addon_detail_url(own_venue.id, other_addon.id),
        data={"title": "Hacked", "fee": 1, "is_active": True},
        user=owner_user,
    )
    assert not_found_resp.status_code == 404

    other_addon.refresh_from_db()
    assert other_addon.title == "Protected Addon"
    assert other_addon.fee == 90_000


@pytest.mark.django_db(transaction=True)
def test_deactivate_addon_hides_from_public_and_booking_selection(api, owner_user, customer_user):
    """Deactivating an add-on removes it from public detail and booking selection, keeping it in owner list."""
    venue = VenueFactory(owner=owner_user, is_approved=True, slug="addon-deactivate-cafe")
    activate_test_subscription(venue)
    pin = TablePinFactory(venue=venue, reservation_fee_toman=80_000)
    addon = DesignAddonFactory(venue=venue, title="Seasonal Lights", fee=120_000, is_active=True)

    resp = api.put(
        _addon_detail_url(venue.id, addon.id),
        data={"title": addon.title, "fee": addon.fee, "is_active": False},
        user=owner_user,
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    owner_list = api.get(_addons_url(venue.id), user=owner_user)
    assert owner_list.status_code == 200
    assert len(owner_list.json()) == 1
    assert owner_list.json()[0]["is_active"] is False

    public_detail = api.get(f"/api/v1/venues/{venue.slug}")
    assert public_detail.status_code == 200
    assert public_detail.json()["design_addons"] == []

    now = timezone.now()
    slot_dt = (now + timedelta(hours=48)).replace(minute=0, second=0, microsecond=0)
    booking = create_booking_lock(
        user=customer_user,
        table_pin=pin,
        slot_date=slot_dt.date(),
        slot_start_time=slot_dt.time(),
        addon_ids=[addon.id],
        now=now,
    )
    assert BookingAddon.objects.filter(booking=booking).count() == 0
    assert booking.amount_in_person_toman == 0


@pytest.mark.django_db
def test_delete_unused_addon_returns_204(api, owner_user):
    """Deleting an unreferenced add-on returns 204 with empty body and removes it from owner list."""
    venue = VenueFactory(owner=owner_user)
    addon = DesignAddonFactory(venue=venue, title="Disposable Addon", fee=50_000)

    del_resp = api.delete(_addon_detail_url(venue.id, addon.id), user=owner_user)
    assert del_resp.status_code == 204
    assert del_resp.content == b""

    assert not DesignAddon.objects.filter(id=addon.id).exists()
    list_resp = api.get(_addons_url(venue.id), user=owner_user)
    assert list_resp.status_code == 200
    assert list_resp.json() == []


@pytest.mark.django_db
def test_delete_addon_in_use_returns_409_and_preserves_booking(api, owner_user, customer_user):
    """Deleting an add-on referenced by BookingAddon returns 409 ADDON_IN_USE and leaves rows intact."""
    venue = VenueFactory(owner=owner_user, is_approved=True)
    activate_test_subscription(venue)
    pin = TablePinFactory(venue=venue, reservation_fee_toman=60_000)
    addon = DesignAddonFactory(venue=venue, title="In-Use Addon", fee=110_000, is_active=True)

    now = timezone.now()
    slot_dt = (now + timedelta(hours=48)).replace(minute=0, second=0, microsecond=0)
    booking = create_booking_lock(
        user=customer_user,
        table_pin=pin,
        slot_date=slot_dt.date(),
        slot_start_time=slot_dt.time(),
        addon_ids=[addon.id],
        now=now,
    )

    del_resp = api.delete(_addon_detail_url(venue.id, addon.id), user=owner_user)
    assert del_resp.status_code == 409
    assert del_resp.json()["error_code"] == "ADDON_IN_USE"

    assert DesignAddon.objects.filter(id=addon.id).exists()
    booking.refresh_from_db()
    assert booking.amount_in_person_toman == 110_000
    assert BookingAddon.objects.filter(booking=booking, design_addon=addon).exists()


@pytest.mark.django_db
def test_br15_editing_addon_fee_does_not_alter_existing_booking_snapshot(api, owner_user, customer_user):
    """BR-15: Editing add-on fee preserves existing BookingAddon snapshot; new bookings use new fee."""
    venue = VenueFactory(owner=owner_user, is_approved=True)
    activate_test_subscription(venue)
    pin = TablePinFactory(venue=venue, reservation_fee_toman=70_000)
    addon = DesignAddonFactory(venue=venue, title="Cake Setup", fee=150_000, is_active=True)

    now = timezone.now()
    slot1 = (now + timedelta(hours=48)).replace(minute=0, second=0, microsecond=0)
    booking1 = create_booking_lock(
        user=customer_user,
        table_pin=pin,
        slot_date=slot1.date(),
        slot_start_time=slot1.time(),
        addon_ids=[addon.id],
        now=now,
    )
    ba1 = BookingAddon.objects.get(booking=booking1, design_addon=addon)
    assert ba1.price_snapshot_toman == 150_000
    assert booking1.amount_in_person_toman == 150_000

    update_resp = api.put(
        _addon_detail_url(venue.id, addon.id),
        data={"title": "Cake Setup", "fee": 220_000, "is_active": True},
        user=owner_user,
    )
    assert update_resp.status_code == 200

    ba1.refresh_from_db()
    booking1.refresh_from_db()
    assert ba1.price_snapshot_toman == 150_000
    assert booking1.amount_in_person_toman == 150_000

    slot2 = (now + timedelta(hours=72)).replace(minute=0, second=0, microsecond=0)
    booking2 = create_booking_lock(
        user=customer_user,
        table_pin=pin,
        slot_date=slot2.date(),
        slot_start_time=slot2.time(),
        addon_ids=[addon.id],
        now=now,
    )
    ba2 = BookingAddon.objects.get(booking=booking2, design_addon=addon)
    assert ba2.price_snapshot_toman == 220_000
    assert booking2.amount_in_person_toman == 220_000


@pytest.mark.django_db(transaction=True)
def test_addon_update_invalidates_public_venue_cache(api, owner_user):
    """Updating an add-on fee invalidates the cached public venue detail on commit."""
    venue = VenueFactory(owner=owner_user, is_approved=True, slug="addon-cache-cafe")
    activate_test_subscription(venue)
    addon = DesignAddonFactory(venue=venue, title="Cached Flowers", fee=100_000, is_active=True)
    cache_key = get_venue_slug_cache_key(venue.slug)

    cache.clear()
    assert cache.get(cache_key) is None

    warm_resp = api.get(f"/api/v1/venues/{venue.slug}")
    assert warm_resp.status_code == 200
    assert warm_resp.json()["design_addons"][0]["fee"] == 100_000
    cached_payload = cache.get(cache_key)
    assert cached_payload is not None
    assert cached_payload["design_addons"][0]["fee"] == 100_000

    update_resp = api.put(
        _addon_detail_url(venue.id, addon.id),
        data={"title": "Cached Flowers", "fee": 350_000, "is_active": True},
        user=owner_user,
    )
    assert update_resp.status_code == 200
    assert cache.get(cache_key) is None

    fresh_resp = api.get(f"/api/v1/venues/{venue.slug}")
    assert fresh_resp.status_code == 200
    assert fresh_resp.json()["design_addons"][0]["fee"] == 350_000
    assert cache.get(cache_key)["design_addons"][0]["fee"] == 350_000


@pytest.mark.django_db
def test_customer_role_forbidden_on_all_owner_addon_endpoints(api, owner_user, customer_user):
    """CUSTOMER role receives 403 on list, create, detail, update, and delete owner add-on endpoints."""
    venue = VenueFactory(owner=owner_user)
    addon = DesignAddonFactory(venue=venue, title="Owner Only", fee=50_000)

    assert api.get(_addons_url(venue.id), user=customer_user).status_code == 403
    assert (
        api.post(
            _addons_url(venue.id),
            data={"title": "Forbidden", "fee": 10_000},
            user=customer_user,
        ).status_code
        == 403
    )
    assert api.get(_addon_detail_url(venue.id, addon.id), user=customer_user).status_code == 403
    assert (
        api.put(
            _addon_detail_url(venue.id, addon.id),
            data={"title": "Forbidden", "fee": 10_000, "is_active": True},
            user=customer_user,
        ).status_code
        == 403
    )
    assert api.delete(_addon_detail_url(venue.id, addon.id), user=customer_user).status_code == 403


@pytest.mark.django_db
def test_extra_fields_rejected_on_create_and_update(api, owner_user):
    """Extra fields in create or update payload are rejected with 422 (extra='forbid')."""
    venue = VenueFactory(owner=owner_user)
    addon = DesignAddonFactory(venue=venue, title="Strict Addon", fee=80_000)

    create_resp = api.post(
        _addons_url(venue.id),
        data={"title": "New Addon", "fee": 50_000, "unexpected_field": "nope"},
        user=owner_user,
    )
    assert create_resp.status_code == 422

    update_resp = api.put(
        _addon_detail_url(venue.id, addon.id),
        data={"title": "Strict Addon", "fee": 90_000, "is_active": True, "venue_id": 999},
        user=owner_user,
    )
    assert update_resp.status_code == 422
