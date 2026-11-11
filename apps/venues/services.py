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
from typing import Any, List, Optional

from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.utils.text import slugify

from apps.accounts.models import UserRole
from apps.venues.models import SubscriptionStatus, Venue

logger = logging.getLogger(__name__)

VENUE_CACHE_TTL = 3600  # 1 hour


def get_venue_cache_key(venue_id: int) -> str:
    return f"venue:metadata:{venue_id}"


def get_venue_slug_cache_key(slug: str) -> str:
    return f"venue:metadata:slug:{slug}"


def invalidate_venue_cache(venue_id: int, slug: Optional[str] = None) -> None:
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
    city: Optional[str] = None,
    venue_type: Optional[str] = None,
) -> List[Venue]:
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


def list_owner_venues(user: Any) -> List[Venue]:
    """List venues owned by the authenticated caller.

    Role enforcement: must be VENUE_OWNER or ADMIN.
    """
    if not (user.is_staff or user.role in (UserRole.VENUE_OWNER, UserRole.ADMIN)):
        raise PermissionDenied("Only venue owners or admins can access owner venues.")

    qs = Venue.objects.filter(owner=user).prefetch_related("operating_hours", "design_addons")
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
    slug: Optional[str] = None,
) -> Venue:
    """Create a new venue for an owner.

    Invariants:
    - User must have VENUE_OWNER or ADMIN role.
    - is_approved is always False on creation.
    - subscription_status defaults to INACTIVE.
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
            subscription_status=SubscriptionStatus.INACTIVE,
        )

    return venue


def update_venue_for_owner(
    user: Any,
    venue_id: int,
    *,
    name: Optional[str] = None,
    city: Optional[str] = None,
    venue_type: Optional[str] = None,
    address: Optional[str] = None,
    description: Optional[str] = None,
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


def approve_venue(admin_user: Any, venue_id: int) -> Venue:
    """Platform admin workflow: approve a venue.

    Invariants:
    - Admin only (role == ADMIN or is_staff=True).
    - is_approved becomes True.
    - Invalidation on transaction commit.
    """
    if not (admin_user.is_staff or admin_user.role == UserRole.ADMIN):
        raise PermissionDenied("Only administrators can approve venues.")

    with transaction.atomic():
        venue = Venue.objects.select_for_update().filter(id=venue_id).first()
        if not venue:
            raise Http404("Venue not found.")

        venue.is_approved = True
        venue.save(update_fields=["is_approved", "updated_at"])

        vid, vslug = venue.id, venue.slug
        transaction.on_commit(lambda: invalidate_venue_cache(vid, vslug))

    logger.info("Admin %s approved venue id=%s slug=%s", admin_user, vid, vslug)
    return venue


def reject_venue(admin_user: Any, venue_id: int) -> Venue:
    """Platform admin workflow: reject/unapprove a venue.

    Invariants:
    - Admin only (role == ADMIN or is_staff=True).
    - is_approved becomes False.
    - Invalidation on transaction commit.
    """
    if not (admin_user.is_staff or admin_user.role == UserRole.ADMIN):
        raise PermissionDenied("Only administrators can reject venues.")

    with transaction.atomic():
        venue = Venue.objects.select_for_update().filter(id=venue_id).first()
        if not venue:
            raise Http404("Venue not found.")

        venue.is_approved = False
        venue.save(update_fields=["is_approved", "updated_at"])

        vid, vslug = venue.id, venue.slug
        transaction.on_commit(lambda: invalidate_venue_cache(vid, vslug))

    logger.info("Admin %s rejected venue id=%s slug=%s", admin_user, vid, vslug)
    return venue
