"""Service layer for the venues app (Task T-009).

Architecture rules:
- ARCH-001: All business logic, DB mutations, and permissions live here.
- ARCH-002: All state-affecting writes execute inside transaction.atomic().
- ARCH-004: Venue metadata cache TTL is 3600s. Cache invalidation happens
  via transaction.on_commit() hooks to ensure data consistency.
- NFR-005: Public venue data never includes owner phone numbers.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import Any

from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.db.models.deletion import ProtectedError
from django.http import Http404
from django.utils import timezone
from django.utils.text import slugify

from apps.accounts.models import UserRole
from apps.venues.models import (
    DesignAddon,
    SubscriptionPlan,
    Venue,
    VenueReviewStatus,
    VenueSubscription,
)
from core.exceptions import (
    AddonInUseError,
    InactiveSubscriptionPlanError,
    VenueNotSubmittableError,
)
from core.jalali import format_jalali

logger = logging.getLogger(__name__)

VENUE_CACHE_TTL = 3600  # 1 hour
MAX_BIGINT = 9_223_372_036_854_775_807


def get_venue_cache_key(venue_id: int) -> str:
    return f"venue:metadata:{venue_id}"


def get_venue_slug_cache_key(slug: str) -> str:
    return f"venue:metadata:slug:{slug}"


def invalidate_venue_cache(venue_id: int, slug: str | None = None) -> None:
    """Invalidate cached venue metadata.

    Called via transaction.on_commit() to ensure cache eviction only happens
    after the database transaction successfully commits.
    """
    keys = [get_venue_cache_key(venue_id)]
    if slug:
        keys.append(get_venue_slug_cache_key(slug))
    cache.delete_many(keys)
    logger.info("Invalidated cache for venue id=%s slug=%s", venue_id, slug)


def list_public_venues(
    city: str | None = None,
    venue_type: str | None = None,
) -> list[Venue]:
    """Return publicly listed venues (BR-005: approved + active subscription)."""
    qs = Venue.objects.public().order_by("name")
    if city:
        qs = qs.filter(city__iexact=city.strip())
    if venue_type:
        qs = qs.filter(venue_type=venue_type.strip().upper())
    return list(qs)


def get_public_venue_by_slug(slug: str) -> dict[str, Any]:
    """Return public details for an approved, active venue.

    Caches the serialized dictionary for 3600s (ARCH-004).
    Excludes unapproved or inactive venues (BR-005) with 404.
    """
    cache_key = get_venue_slug_cache_key(slug)
    cached_data = cache.get(cache_key)
    if cached_data is not None:
        return cached_data

    venue = (
        Venue.objects.public()
        .filter(slug=slug)
        .prefetch_related("operating_hours", "design_addons")
        .first()
    )
    if not venue:
        raise Http404("Venue not found or not publicly available.")

    data = {
        "id": venue.id,
        "name": venue.name,
        "slug": venue.slug,
        "city": venue.city,
        "venue_type": venue.venue_type,
        "address": venue.address,
        "description": venue.description,
        "operating_hours": [
            {
                "id": oh.id,
                "weekday": oh.weekday,
                "open_time": oh.open_time,
                "close_time": oh.close_time,
                "crosses_midnight": oh.crosses_midnight,
            }
            for oh in venue.operating_hours.all()
        ],
        "design_addons": [
            {
                "id": da.id,
                "title": da.title,
                "fee": da.fee,
                "is_active": da.is_active,
            }
            for da in venue.design_addons.filter(is_active=True)
        ],
    }

    cache.set(cache_key, data, timeout=VENUE_CACHE_TTL)
    cache.set(get_venue_cache_key(venue.id), data, timeout=VENUE_CACHE_TTL)
    return data


def list_owner_venues(user: Any) -> list[Venue]:
    """List venues owned by the authenticated caller.

    Role enforcement: must be VENUE_OWNER or ADMIN.
    """
    if not (user.is_staff or user.role in (UserRole.VENUE_OWNER, UserRole.ADMIN)):
        raise PermissionDenied("Only venue owners or admins can access owner venues.")

    now = timezone.now()
    active_sub_exists = VenueSubscription.objects.filter(
        venue_id=OuterRef("pk"),
        expires_at__gt=now,
    )
    qs = (
        Venue.objects.filter(owner=user)
        .annotate(_has_active_subscription=Exists(active_sub_exists))
        .prefetch_related("operating_hours", "design_addons")
    )
    return list(qs)


def get_owner_venue(user: Any, venue_id: int) -> Venue:
    """Get owner's venue by ID with IDOR prevention.

    Raises PermissionDenied if caller is not the owner (and not admin).
    """
    if not (user.is_staff or user.role in (UserRole.VENUE_OWNER, UserRole.ADMIN)):
        raise PermissionDenied("Only venue owners or admins can view owner venues.")

    venue = (
        Venue.objects.filter(id=venue_id)
        .prefetch_related("operating_hours", "design_addons")
        .first()
    )
    if not venue:
        raise Http404("Venue not found.")

    if venue.owner_id != user.id and not (user.is_staff or user.role == UserRole.ADMIN):
        raise PermissionDenied("You do not own this venue.")

    return venue


def create_venue_for_owner(
    user: Any,
    name: str,
    city: str,
    venue_type: str,
    address: str,
    description: str = "",
    slug: str | None = None,
) -> Venue:
    """Create a new venue for an owner.

    Invariants:
    - User must have VENUE_OWNER or ADMIN role.
    - is_approved is always False on creation.
    - Runs inside transaction.atomic().
    """
    if not (user.is_staff or user.role in (UserRole.VENUE_OWNER, UserRole.ADMIN)):
        raise PermissionDenied("Only venue owners or admins can create venues.")

    base_slug = slugify(slug or name)
    if not base_slug:
        base_slug = f"venue-{user.id}"

    candidate_slug = base_slug
    counter = 1
    while Venue.objects.filter(slug=candidate_slug).exists():
        candidate_slug = f"{base_slug}-{counter}"
        counter += 1

    with transaction.atomic():
        venue = Venue.objects.create(
            owner=user,
            name=name.strip(),
            slug=candidate_slug,
            city=city.strip(),
            venue_type=venue_type.strip().upper(),
            address=address.strip(),
            description=description.strip() if description else "",
            is_approved=False,
        )

    return venue


def update_venue_for_owner(
    user: Any,
    venue_id: int,
    *,
    name: str | None = None,
    city: str | None = None,
    venue_type: str | None = None,
    address: str | None = None,
    description: str | None = None,
) -> Venue:
    """Update a venue owned by the caller.

    Invariants:
    - IDOR check: caller must own venue (or be admin).
    - Cannot modify is_approved or subscription_status (mass assignment protection).
    - Cache invalidation occurs inside transaction.on_commit().
    """
    with transaction.atomic():
        venue = Venue.objects.select_for_update().filter(id=venue_id).first()
        if not venue:
            raise Http404("Venue not found.")

        if venue.owner_id != user.id and not (user.is_staff or user.role == UserRole.ADMIN):
            raise PermissionDenied("You do not own this venue.")

        if name is not None:
            venue.name = name.strip()
        if city is not None:
            venue.city = city.strip()
        if venue_type is not None:
            venue.venue_type = venue_type.strip().upper()
        if address is not None:
            venue.address = address.strip()
        if description is not None:
            venue.description = description.strip()

        venue.save()

        # Invalidate metadata cache on commit
        vid, vslug = venue.id, venue.slug
        transaction.on_commit(lambda: invalidate_venue_cache(vid, vslug))

    return venue


def submit_venue_for_review(user: Any, venue_id: int) -> Venue:
    """Owner workflow: submit a DRAFT or REJECTED venue for admin review (FR-33 / T-036)."""
    venue = get_owner_venue(user, venue_id)

    with transaction.atomic():
        locked_venue = (
            Venue.objects.select_for_update()
            .prefetch_related("operating_hours", "design_addons")
            .filter(id=venue.id)
            .first()
        )
        if not locked_venue:
            raise Http404("Venue not found.")

        if locked_venue.review_status not in (
            VenueReviewStatus.DRAFT,
            VenueReviewStatus.REJECTED,
        ):
            raise VenueNotSubmittableError(
                "Venue can only be submitted for review from DRAFT or REJECTED status.",
                details={"review_status": locked_venue.review_status},
            )

        locked_venue.review_status = VenueReviewStatus.PENDING_REVIEW
        locked_venue.is_approved = False
        locked_venue.submitted_for_review_at = timezone.now()
        locked_venue.rejection_reason = ""
        locked_venue.save(
            update_fields=[
                "review_status",
                "is_approved",
                "submitted_for_review_at",
                "rejection_reason",
                "updated_at",
            ]
        )

        vid, vslug = locked_venue.id, locked_venue.slug
        transaction.on_commit(lambda: invalidate_venue_cache(vid, vslug))

    logger.info("Owner id=%s submitted venue id=%s slug=%s for review", user.id, vid, vslug)
    return locked_venue


def approve_venue(admin_user: Any, venue_id: int) -> Venue:
    """Platform admin workflow: approve a venue.

    Invariants:
    - Admin only (role == ADMIN or is_staff=True).
    - is_approved becomes True, review_status becomes APPROVED, rejection_reason cleared.
    - Invalidation on transaction commit.
    """
    if not (admin_user.is_staff or admin_user.role == UserRole.ADMIN):
        raise PermissionDenied("Only administrators can approve venues.")

    with transaction.atomic():
        venue = Venue.objects.select_for_update().filter(id=venue_id).first()
        if not venue:
            raise Http404("Venue not found.")

        venue.review_status = VenueReviewStatus.APPROVED
        venue.is_approved = True
        venue.rejection_reason = ""
        venue.save(update_fields=["review_status", "is_approved", "rejection_reason", "updated_at"])

        vid, vslug = venue.id, venue.slug
        transaction.on_commit(lambda: invalidate_venue_cache(vid, vslug))

    logger.info("Admin id=%s approved venue id=%s slug=%s", admin_user.id, vid, vslug)
    return venue


def reject_venue(admin_user: Any, venue_id: int, *, reason: str) -> Venue:
    """Platform admin workflow: reject/unapprove a venue with a reason (FR-37 / T-036).

    Invariants:
    - Admin only (role == ADMIN or is_staff=True).
    - reason must be a non-blank string up to 1000 characters.
    - is_approved becomes False, review_status becomes REJECTED.
    - Invalidation on transaction commit.
    """
    if not (admin_user.is_staff or admin_user.role == UserRole.ADMIN):
        raise PermissionDenied("Only administrators can reject venues.")

    if not isinstance(reason, str):
        raise DjangoValidationError({"reason": "Rejection reason must be a string."})
    cleaned = reason.strip()
    if not cleaned or len(cleaned) > 1000:
        raise DjangoValidationError(
            {"reason": "Rejection reason must be between 1 and 1000 characters."}
        )

    with transaction.atomic():
        venue = Venue.objects.select_for_update().filter(id=venue_id).first()
        if not venue:
            raise Http404("Venue not found.")

        venue.review_status = VenueReviewStatus.REJECTED
        venue.is_approved = False
        venue.rejection_reason = cleaned
        venue.save(update_fields=["review_status", "is_approved", "rejection_reason", "updated_at"])

        vid, vslug = venue.id, venue.slug
        transaction.on_commit(lambda: invalidate_venue_cache(vid, vslug))

    logger.info("Admin id=%s rejected venue id=%s slug=%s", admin_user.id, vid, vslug)
    return venue


def activate_subscription(
    venue: Venue | int,
    *,
    plan: SubscriptionPlan | int,
    activated_by: Any,
    note: str = "",
    now: datetime | None = None,
) -> VenueSubscription:
    """Manually activate or stack a subscription window for a venue (Decision 5 / Task T-025).

    Stacking rule:
    - If the venue currently has an active subscription (expires_at > now),
      starts_at = current expires_at, expires_at = starts_at + plan.duration_days.
    - Otherwise, starts_at = now, expires_at = now + plan.duration_days.
    """
    current_time = now or timezone.now()
    venue_id = venue.pk if isinstance(venue, Venue) else venue
    plan_id = plan.pk if isinstance(plan, SubscriptionPlan) else plan

    with transaction.atomic():
        locked_venue = Venue.objects.select_for_update().filter(pk=venue_id).first()
        if not locked_venue:
            raise Http404("Venue not found.")

        plan_obj = SubscriptionPlan.objects.filter(pk=plan_id).first()
        if not plan_obj:
            raise Http404("Subscription plan not found.")

        if not plan_obj.is_active:
            raise InactiveSubscriptionPlanError(
                "Cannot activate an inactive subscription plan.",
                details={"plan_id": plan_obj.id, "plan_name": plan_obj.name},
            )

        latest = (
            VenueSubscription.objects.filter(venue=locked_venue)
            .order_by("-expires_at", "-id")
            .first()
        )
        if latest is not None and latest.expires_at > current_time:
            starts_at = latest.expires_at
        else:
            starts_at = current_time

        expires_at = starts_at + timedelta(days=plan_obj.duration_days)

        sub = VenueSubscription.objects.create(
            venue=locked_venue,
            plan=plan_obj,
            starts_at=starts_at,
            expires_at=expires_at,
            created_by=activated_by,
            note=note or "",
        )

        vid, vslug = locked_venue.id, locked_venue.slug
        transaction.on_commit(lambda: invalidate_venue_cache(vid, vslug))

    logger.info(
        "Subscription activated for venue id=%s plan_id=%s expires_at=%s",
        vid,
        plan_obj.id,
        expires_at.isoformat(),
    )
    return sub


def get_owner_venue_subscription(
    user: Any,
    venue_id: int,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return current subscription status for an owner's venue (Task T-025).

    Uses get_owner_venue for identical role/IDOR (403/404) enforcement.
    """
    venue = get_owner_venue(user, venue_id)
    current_time = now or timezone.now()

    latest = (
        VenueSubscription.objects.select_related("plan")
        .filter(venue=venue)
        .order_by("-expires_at", "-id")
        .first()
    )
    if latest is None:
        return {
            "is_active": False,
            "plan_name": None,
            "starts_at": None,
            "expires_at": None,
            "jalali_expires_at": None,
            "days_remaining": 0,
            "has_ever_subscribed": False,
        }

    is_active = latest.expires_at > current_time
    days_remaining = (
        max(0, math.ceil((latest.expires_at - current_time).total_seconds() / 86400))
        if is_active
        else 0
    )
    return {
        "is_active": is_active,
        "plan_name": latest.plan.name,
        "starts_at": latest.starts_at,
        "expires_at": latest.expires_at,
        "jalali_expires_at": format_jalali(latest.expires_at),
        "days_remaining": days_remaining,
        "has_ever_subscribed": True,
    }


def mask_phone(phone: str) -> str:
    """Mask middle digits of a phone number so full numbers never leave the server."""
    digits = (phone or "").strip()
    if len(digits) >= 7:
        return f"{digits[:4]}***{digits[-3:]}"
    if len(digits) >= 3:
        return f"{digits[:1]}***{digits[-1:]}"
    return "***"


def list_owner_venue_bookings(
    user: Any,
    venue_id: int,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List bookings for an owner's venue ordered by nearest slot start first (PH-06-02-PRE).

    Enforces identical role/IDOR checks (403/404) via get_owner_venue().
    Constant-query read via select_related('table_pin', 'customer').
    """
    from apps.bookings.models import Booking

    venue = get_owner_venue(user, venue_id)
    clamped_limit = max(1, min(int(limit), 200))
    clamped_offset = max(0, int(offset))

    bookings = list(
        Booking.objects.select_related("table_pin", "customer")
        .filter(venue=venue)
        .order_by("start_at", "id")[clamped_offset : clamped_offset + clamped_limit]
    )

    return [
        {
            "booking_id": booking.id,
            "status": booking.status,
            "table_number": booking.table_pin.table_number,
            "slot_date": booking.slot_date,
            "jalali_date": format_jalali(booking.start_at, fmt="%Y/%m/%d"),
            "slot_start_time": booking.slot_start_time,
            "start_at": booking.start_at,
            "end_at": booking.end_at,
            "start_jalali": format_jalali(booking.start_at, fmt="%Y/%m/%d %H:%M"),
            "end_jalali": format_jalali(booking.end_at, fmt="%Y/%m/%d %H:%M"),
            "amount_online_toman": booking.amount_online_toman,
            "amount_in_person_toman": booking.amount_in_person_toman,
            "customer_phone_masked": mask_phone(booking.customer.phone),
            "created_at": booking.created_at,
        }
        for booking in bookings
    ]


def _validate_addon_fields(title: str, fee: int) -> str:
    """Validate and normalize design add-on title and fee (FR-32 / T-035)."""
    cleaned = title.strip() if isinstance(title, str) else ""
    if not cleaned:
        raise DjangoValidationError({"title": "Design add-on title cannot be blank."})
    if len(cleaned) > 200:
        raise DjangoValidationError({"title": "Design add-on title must be at most 200 characters."})
    if isinstance(fee, bool) or fee < 0:
        raise DjangoValidationError({"fee": "Design add-on fee must be a non-negative integer."})
    if fee > MAX_BIGINT:
        raise DjangoValidationError(
            {"fee": f"Design add-on fee must be at most {MAX_BIGINT}."}
        )
    return cleaned


def list_owner_addons(user: Any, venue_id: int) -> list[DesignAddon]:
    """List all design add-ons (including inactive) for an owner's venue."""
    venue = get_owner_venue(user, venue_id)
    return list(venue.design_addons.all())


def get_owner_addon(user: Any, venue_id: int, addon_id: int) -> DesignAddon:
    """Return a single design add-on belonging to the owner's venue (404 if absent or other venue)."""
    venue = get_owner_venue(user, venue_id)
    addon = venue.design_addons.filter(id=addon_id).first()
    if addon is None:
        raise Http404("Design add-on not found.")
    return addon


def create_owner_addon(
    user: Any,
    venue_id: int,
    *,
    title: str,
    fee: int,
    is_active: bool = True,
) -> DesignAddon:
    """Create a design add-on for an owner's venue and invalidate venue cache on commit."""
    venue = get_owner_venue(user, venue_id)
    cleaned_title = _validate_addon_fields(title, fee)
    with transaction.atomic():
        addon = DesignAddon.objects.create(
            venue=venue,
            title=cleaned_title,
            fee=fee,
            is_active=is_active,
        )
        vid, vslug = venue.id, venue.slug
        transaction.on_commit(lambda: invalidate_venue_cache(vid, vslug))
    return addon


def update_owner_addon(
    user: Any,
    venue_id: int,
    addon_id: int,
    *,
    title: str,
    fee: int,
    is_active: bool,
) -> DesignAddon:
    """Replace fields of an owner's venue design add-on and invalidate cache on commit."""
    venue = get_owner_venue(user, venue_id)
    addon = venue.design_addons.filter(id=addon_id).first()
    if addon is None:
        raise Http404("Design add-on not found.")
    cleaned_title = _validate_addon_fields(title, fee)
    with transaction.atomic():
        addon.title = cleaned_title
        addon.fee = fee
        addon.is_active = is_active
        addon.save(update_fields=["title", "fee", "is_active", "updated_at"])
        vid, vslug = venue.id, venue.slug
        transaction.on_commit(lambda: invalidate_venue_cache(vid, vslug))
    return addon


def delete_owner_addon(user: Any, venue_id: int, addon_id: int) -> None:
    """Delete an owner's venue design add-on; raise AddonInUseError if referenced by bookings."""
    venue = get_owner_venue(user, venue_id)
    addon = venue.design_addons.filter(id=addon_id).first()
    if addon is None:
        raise Http404("Design add-on not found.")
    with transaction.atomic():
        try:
            addon.delete()
        except ProtectedError as exc:
            raise AddonInUseError() from exc
        vid, vslug = venue.id, venue.slug
        transaction.on_commit(lambda: invalidate_venue_cache(vid, vslug))
