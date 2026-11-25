"""Django Ninja router for the venues app (Task T-009).

Mounted centrally in config/api.py under /api/v1/venues.
Views stay thin (Architecture Spec section 14):
- authenticate
- validate via schemas.py
- call services.py
- return typed schemas
Never write raw ORM queries or perform mutations directly in views (ARCH-001).
"""
from __future__ import annotations

from typing import List, Optional

from ninja import Router
from ninja.responses import Status

from apps.accounts.auth import auth
from apps.venues import services
from apps.venues.schemas import (
    OwnerBookingOut,
    VenueApprovalOut,
    VenueCreateIn,
    VenueOwnerOut,
    VenuePublicDetailOut,
    VenuePublicItemOut,
    VenueSubscriptionOut,
    VenueUpdateIn,
)

router = Router(tags=["venues"])


# ---------------------------------------------------------------------------
# Owner endpoints (authenticated, VENUE_OWNER or ADMIN)
# ---------------------------------------------------------------------------


@router.get("/owner/venues", response=List[VenueOwnerOut], auth=auth, summary="List owner venues")
def list_my_venues(request):
    """List all venues belonging to the authenticated owner."""
    return services.list_owner_venues(request.auth)


@router.post("/owner/venues", response={201: VenueOwnerOut}, auth=auth, summary="Create venue")
def create_venue(request, payload: VenueCreateIn):
    """Create a new venue for the authenticated owner (is_approved=False)."""
    venue = services.create_venue_for_owner(
        user=request.auth,
        name=payload.name,
        city=payload.city,
        venue_type=payload.venue_type,
        address=payload.address,
        description=payload.description,
        slug=payload.slug,
    )
    return Status(201, venue)


@router.get("/owner/venues/{venue_id}", response=VenueOwnerOut, auth=auth, summary="Get owner venue")
def get_my_venue(request, venue_id: int):
    """Get owner's venue detail. Enforces IDOR check."""
    return services.get_owner_venue(request.auth, venue_id)


@router.put("/owner/venues/{venue_id}", response=VenueOwnerOut, auth=auth, summary="Update owner venue")
def update_my_venue(request, venue_id: int, payload: VenueUpdateIn):
    """Update owner's venue. Enforces IDOR check and invalidates cache on commit."""
    venue = services.update_venue_for_owner(
        user=request.auth,
        venue_id=venue_id,
        name=payload.name,
        city=payload.city,
        venue_type=payload.venue_type,
        address=payload.address,
        description=payload.description,
    )
    return venue


@router.get(
    "/owner/venues/{venue_id}/subscription/",
    response=VenueSubscriptionOut,
    auth=auth,
    summary="Get owner venue subscription status (Decision 5)",
)
@router.get(
    "/owner/venues/{venue_id}/subscription",
    response=VenueSubscriptionOut,
    auth=auth,
    summary="Get owner venue subscription status (trailing-slash alias)",
    include_in_schema=False,
)
def get_my_venue_subscription(request, venue_id: int):
    """Read-only subscription status for the authenticated owner's venue."""
    return services.get_owner_venue_subscription(request.auth, venue_id)


@router.get(
    "/owner/venues/{venue_id}/bookings/",
    response=List[OwnerBookingOut],
    auth=auth,
    summary="List owner venue bookings (PH-06-02-PRE)",
)
@router.get(
    "/owner/venues/{venue_id}/bookings",
    response=List[OwnerBookingOut],
    auth=auth,
    summary="List owner venue bookings (trailing-slash alias)",
    include_in_schema=False,
)
def list_my_venue_bookings(request, venue_id: int, limit: int = 50, offset: int = 0):
    """Read-only bounded list of bookings for the authenticated owner's venue."""
    return services.list_owner_venue_bookings(
        request.auth,
        venue_id,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Admin approval endpoints (authenticated, ADMIN or is_staff)
# ---------------------------------------------------------------------------


@router.post(
    "/admin/venues/{venue_id}/approve",
    response=VenueApprovalOut,
    auth=auth,
    summary="Admin approve venue",
)
def approve_venue_endpoint(request, venue_id: int):
    """Approve a venue and invalidate its public cache."""
    venue = services.approve_venue(request.auth, venue_id)
    return {
        "id": venue.id,
        "slug": venue.slug,
        "is_approved": venue.is_approved,
        "message": "Venue approved successfully.",
    }


@router.post(
    "/admin/venues/{venue_id}/reject",
    response=VenueApprovalOut,
    auth=auth,
    summary="Admin reject venue",
)
def reject_venue_endpoint(request, venue_id: int):
    """Reject/unapprove a venue and invalidate its public cache."""
    venue = services.reject_venue(request.auth, venue_id)
    return {
        "id": venue.id,
        "slug": venue.slug,
        "is_approved": venue.is_approved,
        "message": "Venue unapproved/rejected.",
    }


# ---------------------------------------------------------------------------
# Public catalogue endpoints (unauthenticated, filtered & cached)
# ---------------------------------------------------------------------------


@router.get("/", response=List[VenuePublicItemOut], summary="List public venues")
def list_public(
    request,
    city: Optional[str] = None,
    venue_type: Optional[str] = None,
):
    """List approved venues with active subscription (BR-005).

    Privacy: Never exposes owner phone number or internal status flags.
    """
    return services.list_public_venues(city=city, venue_type=venue_type)


@router.get("/{slug}", response=VenuePublicDetailOut, summary="Get public venue detail")
def get_public_detail(request, slug: str):
    """Public detail for an approved venue with active subscription.

    Cached with 3600s TTL (ARCH-004). Returns 404 for unapproved venues.
    """
    return services.get_public_venue_by_slug(slug)
