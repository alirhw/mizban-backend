"""Reproduction and verification tests for T-046 venues minors (m5, m7, m8, m10, m11, m15, m35)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import time, timedelta
from threading import Barrier

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.bookings.models import Booking, BookingStatus
from apps.notifications.models import Notification, NotificationType
from apps.panoramas.models import Space, TablePin
from apps.venues.admin import DesignAddonAdmin, OperatingHoursAdmin, VenueAdmin
from apps.venues.models import (
    DesignAddon,
    OperatingHours,
    SubscriptionPlan,
    Venue,
    VenueReviewStatus,
    VenueSubscription,
)
from apps.venues.services import (
    create_venue_for_owner,
    get_owner_venue_subscription,
    get_public_venue_by_slug,
    list_owner_venue_bookings,
    list_owner_venues,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# m5: Future-dated subscription (starts_at > now) must not be active
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_future_dated_subscription_is_not_active():
    owner = User.objects.create_user(phone="09120004001", role=UserRole.VENUE_OWNER)
    plan = SubscriptionPlan.objects.create(name="Basic", duration_days=30, price_toman=100_000)
    now = timezone.now()

    venue = Venue.objects.create(
        owner=owner,
        name="Future Sub Cafe",
        slug="future-sub-m5",
        city="Tehran",
        venue_type="CAFE",
        address="Addr",
        is_approved=True,
        review_status=VenueReviewStatus.APPROVED,
    )
    VenueSubscription.objects.create(
        venue=venue,
        plan=plan,
        starts_at=now + timedelta(days=2),
        expires_at=now + timedelta(days=32),
        created_by=owner,
    )

    assert venue.has_active_subscription(now=now) is False
    assert not Venue.objects.public(now=now).filter(pk=venue.pk).exists()

    owner_venues = list_owner_venues(owner)
    assert len(owner_venues) == 1
    assert owner_venues[0]._has_active_subscription is False

    sub_status = get_owner_venue_subscription(owner, venue.id, now=now)
    assert sub_status["is_active"] is False
    assert sub_status["days_remaining"] == 0


# ---------------------------------------------------------------------------
# m7: Bulk admin approve/reject create owner notifications
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_admin_bulk_approve_and_reject_create_notifications():
    owner = User.objects.create_user(phone="09120004002", role=UserRole.VENUE_OWNER)
    admin_user = User.objects.create_user(phone="09120004003", role=UserRole.ADMIN, is_staff=True)

    v1 = Venue.objects.create(
        owner=owner,
        name="Bulk Approve",
        slug="bulk-approve-m7",
        city="Tehran",
        venue_type="CAFE",
        address="Addr 1",
        review_status=VenueReviewStatus.PENDING_REVIEW,
    )
    v2 = Venue.objects.create(
        owner=owner,
        name="Bulk Reject",
        slug="bulk-reject-m7",
        city="Tehran",
        venue_type="CAFE",
        address="Addr 2",
        review_status=VenueReviewStatus.PENDING_REVIEW,
    )

    model_admin = VenueAdmin(Venue, AdminSite())
    req = RequestFactory().post("/admin/venues/venue/")
    req.user = admin_user
    # Disable Django messages middleware dependency by attaching dummy _messages if needed
    from django.contrib.messages.storage.fallback import FallbackStorage

    req.session = {}
    req._messages = FallbackStorage(req)

    model_admin.approve_selected_venues(req, Venue.objects.filter(pk=v1.pk))
    model_admin.reject_selected_venues(req, Venue.objects.filter(pk=v2.pk))

    assert Notification.objects.filter(
        recipient=owner, venue=v1, type=NotificationType.VENUE_APPROVED
    ).exists()
    assert Notification.objects.filter(
        recipient=owner, venue=v2, type=NotificationType.VENUE_REJECTED
    ).exists()


# ---------------------------------------------------------------------------
# m8: Cache invalidation on OperatingHours/DesignAddon admin + subscription liveness
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_public_venue_detail_cache_invalidated_on_admin_edit_and_revalidates_subscription():
    from django.http import Http404

    owner = User.objects.create_user(phone="09120004004", role=UserRole.VENUE_OWNER)
    admin_user = User.objects.create_user(phone="09120004005", role=UserRole.ADMIN, is_staff=True)
    plan = SubscriptionPlan.objects.create(name="Pro", duration_days=30, price_toman=100_000)
    now = timezone.now()

    venue = Venue.objects.create(
        owner=owner,
        name="Cached Cafe",
        slug="cached-cafe-m8",
        city="Tehran",
        venue_type="CAFE",
        address="Addr",
        is_approved=True,
        review_status=VenueReviewStatus.APPROVED,
    )
    sub = VenueSubscription.objects.create(
        venue=venue,
        plan=plan,
        starts_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=29),
        created_by=owner,
    )
    oh = OperatingHours.objects.create(
        venue=venue, weekday=0, open_time=time(9, 0), close_time=time(17, 0)
    )
    addon = DesignAddon.objects.create(venue=venue, title="Flowers", fee=10_000, is_active=True)

    # Populate cache
    first = get_public_venue_by_slug(venue.slug)
    assert first["operating_hours"][0]["close_time"] == time(17, 0)
    assert len(first["design_addons"]) == 1

    # Edit OperatingHours via admin
    req = RequestFactory().post("/admin/")
    req.user = admin_user
    oh_admin = OperatingHoursAdmin(OperatingHours, AdminSite())
    oh.close_time = time(20, 0)
    oh_admin.save_model(req, oh, form=None, change=True)

    after_oh = get_public_venue_by_slug(venue.slug)
    assert after_oh["operating_hours"][0]["close_time"] == time(20, 0)

    # Delete DesignAddon via admin
    addon_admin = DesignAddonAdmin(DesignAddon, AdminSite())
    addon_admin.delete_model(req, addon)

    after_addon = get_public_venue_by_slug(venue.slug)
    assert len(after_addon["design_addons"]) == 0

    # Expire subscription directly in DB (no cache invalidation): must 404 immediately
    sub.expires_at = now - timedelta(seconds=1)
    sub.save(update_fields=["expires_at"])

    with pytest.raises(Http404):
        get_public_venue_by_slug(venue.slug)


# ---------------------------------------------------------------------------
# m10: Concurrent venue creation with same slug retries without IntegrityError
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_create_venue_concurrent_same_slug_retries_without_integrity_error():
    owner = User.objects.create_user(phone="09120004006", role=UserRole.VENUE_OWNER)
    workers = 4
    barrier = Barrier(workers)

    def _create(_idx: int) -> str:
        from django.db import connections

        barrier.wait(timeout=5)
        try:
            v = create_venue_for_owner(
                user=owner,
                name="Concurrent Cafe",
                city="Tehran",
                venue_type="CAFE",
                address="Addr",
                slug="concurrent-cafe-m10",
            )
            return v.slug
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        slugs = list(pool.map(_create, range(workers)))

    assert len(set(slugs)) == workers
    assert "concurrent-cafe-m10" in slugs


# ---------------------------------------------------------------------------
# m11: Owner bookings masks customer phone ONLY when status == CONFIRMED
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_owner_bookings_masks_phone_only_for_confirmed():
    owner = User.objects.create_user(phone="09120004007", role=UserRole.VENUE_OWNER)
    customer = User.objects.create_user(phone="09123334455", role=UserRole.CUSTOMER)
    venue = Venue.objects.create(
        owner=owner,
        name="Phone Mask Cafe",
        slug="phone-mask-m11",
        city="Tehran",
        venue_type="CAFE",
        address="Addr",
        is_approved=True,
        review_status=VenueReviewStatus.APPROVED,
    )
    space = Space.objects.create(venue=venue, name="Main")
    pin = TablePin.objects.create(
        venue=venue,
        space=space,
        table_number="T1",
        capacity=4,
        yaw=0.0,
        pitch=0.0,
        reservation_fee_toman=50_000,
    )
    now = timezone.now()

    statuses = [
        BookingStatus.CONFIRMED,
        BookingStatus.PENDING_PAYMENT,
        BookingStatus.CANCELLED,
        BookingStatus.EXPIRED,
    ]
    created = {}
    for idx, st in enumerate(statuses):
        start_at = now + timedelta(days=2 + idx)
        b = Booking.objects.create(
            venue=venue,
            table_pin=pin,
            customer=customer,
            slot_date=start_at.date(),
            slot_start_time=time(10, 0),
            start_at=start_at,
            end_at=start_at + timedelta(minutes=90),
            status=st,
            lock_expires_at=now + timedelta(minutes=10),
            amount_online_toman=50_000,
            amount_in_person_toman=0,
        )
        created[st] = b.id

    rows = {r["booking_id"]: r for r in list_owner_venue_bookings(owner, venue.id)}
    assert rows[created[BookingStatus.CONFIRMED]]["customer_phone_masked"] == "0912***455"
    assert rows[created[BookingStatus.PENDING_PAYMENT]]["customer_phone_masked"] is None
    assert rows[created[BookingStatus.CANCELLED]]["customer_phone_masked"] is None
    assert rows[created[BookingStatus.EXPIRED]]["customer_phone_masked"] is None


# ---------------------------------------------------------------------------
# m15: Public venue list pagination (limit/offset)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_public_venues_list_supports_limit_and_offset():
    owner = User.objects.create_user(phone="09120004008", role=UserRole.VENUE_OWNER)
    plan = SubscriptionPlan.objects.create(name="Pro", duration_days=30, price_toman=100_000)
    now = timezone.now()

    for idx in range(5):
        v = Venue.objects.create(
            owner=owner,
            name=f"Paginated Venue {idx}",
            slug=f"paginated-venue-m15-{idx}",
            city="Tehran",
            venue_type="CAFE",
            address="Addr",
            is_approved=True,
            review_status=VenueReviewStatus.APPROVED,
        )
        VenueSubscription.objects.create(
            venue=v,
            plan=plan,
            starts_at=now - timedelta(days=1),
            expires_at=now + timedelta(days=29),
            created_by=owner,
        )

    client = Client()
    resp = client.get("/api/v1/venues/?limit=2&offset=1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert [d["slug"] for d in data] == ["paginated-venue-m15-1", "paginated-venue-m15-2"]


# ---------------------------------------------------------------------------
# m35: Admin venue list endpoint
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_admin_venues_list_endpoint():
    owner = User.objects.create_user(phone="09120004009", role=UserRole.VENUE_OWNER)
    customer = User.objects.create_user(phone="09120004010", role=UserRole.CUSTOMER)
    admin_user = User.objects.create_user(phone="09120004011", role=UserRole.ADMIN)

    Venue.objects.create(
        owner=owner,
        name="Beta Cafe",
        slug="beta-cafe-m35",
        city="Tehran",
        venue_type="CAFE",
        address="Addr",
        is_approved=False,
        review_status=VenueReviewStatus.DRAFT,
    )
    Venue.objects.create(
        owner=owner,
        name="Alpha Cafe",
        slug="alpha-cafe-m35",
        city="Tehran",
        venue_type="CAFE",
        address="Addr",
        is_approved=True,
        review_status=VenueReviewStatus.APPROVED,
    )

    client = Client()
    assert client.get("/api/v1/venues/admin/venues").status_code == 401

    client.force_login(customer)
    assert client.get("/api/v1/venues/admin/venues").status_code == 403

    client.force_login(owner)
    assert client.get("/api/v1/venues/admin/venues").status_code == 403

    client.force_login(admin_user)
    resp = client.get("/api/v1/venues/admin/venues")
    assert resp.status_code == 200
    data = resp.json()
    assert [d["name"] for d in data] == ["Alpha Cafe", "Beta Cafe"]
    assert set(data[0].keys()) == {"id", "name", "slug", "is_approved", "review_status"}

    resp_paged = client.get("/api/v1/venues/admin/venues?limit=1&offset=1")
    assert resp_paged.status_code == 200
    assert [d["name"] for d in resp_paged.json()] == ["Beta Cafe"]
