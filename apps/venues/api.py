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

from ninja import Router
from ninja.responses import Status

from apps.accounts.auth import auth
from apps.venues import services
from apps.venues.schemas import (
    DesignAddonCreateIn,
    DesignAddonOut,
    DesignAddonUpdateIn,
    OwnerBookingOut,
    VenueAdminItemOut,
    VenueApprovalOut,
    VenueCreateIn,
    VenueOwnerOut,
    VenuePublicDetailOut,
    VenuePublicItemOut,
    VenueRejectIn,
    VenueSubscriptionOut,
    VenueUpdateIn,
)

router = Router(tags=["venues"])


# ---------------------------------------------------------------------------
# Owner endpoints (authenticated, VENUE_OWNER or ADMIN)
# ---------------------------------------------------------------------------


@router.get("/owner/venues", response=list[VenueOwnerOut], auth=auth, summary="List owner venues")
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


@router.post(
    "/owner/venues/{venue_id}/submit",
    response=VenueOwnerOut,
    auth=auth,
    summary="Submit owner venue for review (FR-33)",
)
def submit_my_venue(request, venue_id: int):
    """Submit a DRAFT or REJECTED venue for platform admin review."""
    return services.submit_venue_for_review(request.auth, venue_id)


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
    response=list[OwnerBookingOut],
    auth=auth,
    summary="List owner venue bookings (PH-06-02-PRE)",
)
@router.get(
    "/owner/venues/{venue_id}/bookings",
    response=list[OwnerBookingOut],
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


@router.get(
    "/owner/venues/{venue_id}/addons/",
    response=list[DesignAddonOut],
    auth=auth,
    summary="List owner venue design add-ons (FR-32)",
)
def list_my_venue_addons(request, venue_id: int):
    """List all design add-ons (including inactive) for the authenticated owner's venue."""
    return services.list_owner_addons(request.auth, venue_id)


@router.post(
    "/owner/venues/{venue_id}/addons/",
    response={201: DesignAddonOut},
    auth=auth,
    summary="Create owner venue design add-on (FR-32)",
)
def create_my_venue_addon(request, venue_id: int, payload: DesignAddonCreateIn):
    """Create a design add-on for the authenticated owner's venue."""
    addon = services.create_owner_addon(
        request.auth,
        venue_id,
        title=payload.title,
        fee=payload.fee,
        is_active=payload.is_active,
    )
    return Status(201, addon)


@router.get(
    "/owner/venues/{venue_id}/addons/{addon_id}/",
    response=DesignAddonOut,
    auth=auth,
    summary="Get owner venue design add-on (FR-32)",
)
def get_my_venue_addon(request, venue_id: int, addon_id: int):
    """Get a single design add-on belonging to the authenticated owner's venue."""
    return services.get_owner_addon(request.auth, venue_id, addon_id)


@router.put(
    "/owner/venues/{venue_id}/addons/{addon_id}/",
    response=DesignAddonOut,
    auth=auth,
    summary="Update owner venue design add-on (FR-32)",
)
def update_my_venue_addon(request, venue_id: int, addon_id: int, payload: DesignAddonUpdateIn):
    """Replace fields of a design add-on belonging to the authenticated owner's venue."""
    return services.update_owner_addon(
        request.auth,
        venue_id,
        addon_id,
        title=payload.title,
        fee=payload.fee,
        is_active=payload.is_active,
    )


@router.delete(
    "/owner/venues/{venue_id}/addons/{addon_id}/",
    response={204: None},
    auth=auth,
    summary="Delete owner venue design add-on (FR-32)",
)
def delete_my_venue_addon(request, venue_id: int, addon_id: int):
    """Delete a design add-on belonging to the authenticated owner's venue."""
    services.delete_owner_addon(request.auth, venue_id, addon_id)
    return Status(204, None)


# ---------------------------------------------------------------------------
# Admin approval endpoints (authenticated, ADMIN or is_staff)
# ---------------------------------------------------------------------------


@router.get(
    "/admin/venues",
    response=list[VenueAdminItemOut],
    auth=auth,
    summary="Admin list all venues",
)
def list_admin_venues_endpoint(request, limit: int = 50, offset: int = 0):
    """List all venues regardless of approval or subscription status (ADMIN/staff only)."""
    return services.list_admin_venues(request.auth, limit=limit, offset=offset)


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
        "review_status": venue.review_status,
        "rejection_reason": venue.rejection_reason,
        "message": "Venue approved successfully.",
    }


@router.post(
    "/admin/venues/{venue_id}/reject",
    response=VenueApprovalOut,
    auth=auth,
    summary="Admin reject venue",
)
def reject_venue_endpoint(request, venue_id: int, payload: VenueRejectIn):
    """Reject/unapprove a venue with a reason and invalidate its public cache."""
    venue = services.reject_venue(request.auth, venue_id, reason=payload.reason)
    return {
        "id": venue.id,
        "slug": venue.slug,
        "is_approved": venue.is_approved,
        "review_status": venue.review_status,
        "rejection_reason": venue.rejection_reason,
        "message": "Venue unapproved/rejected.",
    }


# ---------------------------------------------------------------------------
# Public catalogue endpoints (unauthenticated, filtered & cached)
# ---------------------------------------------------------------------------


@router.get("/", response=list[VenuePublicItemOut], summary="List public venues")
def list_public(
    request,
    city: str | None = None,
    venue_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """List approved venues with active subscription (BR-005).

    Privacy: Never exposes owner phone number or internal status flags.
    """
    return services.list_public_venues(
        city=city,
        venue_type=venue_type,
        limit=limit,
        offset=offset,
    )


@router.get("/{slug}", response=VenuePublicDetailOut, summary="Get public venue detail")
def get_public_detail(request, slug: str):
    """Public detail for an approved venue with active subscription.

    Cached with 3600s TTL (ARCH-004). Returns 404 for unapproved venues.
    """
    return services.get_public_venue_by_slug(slug)
