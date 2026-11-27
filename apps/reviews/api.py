"""Django Ninja router for the reviews app (FR-24/FR-25).

Mounted centrally in config/api.py under /api/v1/reviews.
Views stay thin (ARCH-001): authenticate, validate via schemas.py,
delegate to services.py, and return typed schemas.
"""
from __future__ import annotations

from ninja import Router
from ninja.responses import Status

from apps.accounts.auth import auth
from apps.reviews import services
from apps.reviews.schemas import (
    ReviewAdminOut,
    ReviewCreateIn,
    ReviewListOut,
    ReviewMineOut,
)

router = Router(tags=["reviews"])


@router.post("/", response={201: ReviewMineOut}, auth=auth, summary="Submit a review (FR-24)")
def create_review(request, payload: ReviewCreateIn):
    """Submit a rating and review text for a completed booking."""
    review = services.submit_review(
        user=request.auth,
        booking_id=payload.booking_id,
        rating=payload.rating,
        text=payload.text,
    )
    return Status(201, services.serialize_my_review(review))


@router.get(
    "/venues/{venue_id}/",
    response=ReviewListOut,
    summary="List public venue reviews (FR-25)",
)
def list_venue_reviews(request, venue_id: int, limit: int = 20, offset: int = 0):
    """Return visible reviews and aggregate rating for a venue."""
    return services.list_venue_reviews(venue_id, limit=limit, offset=offset)


@router.get(
    "/tables/{table_pin_id}/",
    response=ReviewListOut,
    summary="List public table reviews (FR-25)",
)
def list_table_reviews(request, table_pin_id: int, limit: int = 20, offset: int = 0):
    """Return visible reviews and aggregate rating for a table pin."""
    return services.list_table_reviews(table_pin_id, limit=limit, offset=offset)


@router.get(
    "/my/",
    response=list[ReviewMineOut],
    auth=auth,
    summary="List my submitted reviews",
)
def list_my_reviews(request, limit: int = 20, offset: int = 0):
    """Return all reviews submitted by the authenticated customer."""
    return services.list_my_reviews(request.auth, limit=limit, offset=offset)


@router.get(
    "/admin/",
    response=list[ReviewAdminOut],
    auth=auth,
    summary="List all reviews for admin moderation (FR-41)",
)
def list_admin_reviews(
    request,
    venue_id: int | None = None,
    is_visible: bool | None = None,
    limit: int = 20,
    offset: int = 0,
):
    """Return paginated reviews for admin moderation with optional filters."""
    return services.list_admin_reviews(
        request.auth,
        venue_id=venue_id,
        is_visible=is_visible,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/admin/{review_id}/hide",
    response=ReviewAdminOut,
    auth=auth,
    summary="Hide a review (FR-41, BR-13)",
)
def hide_review(request, review_id: int):
    """Hide a review from public listing."""
    review = services.set_review_visibility(request.auth, review_id, is_visible=False)
    return services.serialize_admin_review(review)


@router.post(
    "/admin/{review_id}/show",
    response=ReviewAdminOut,
    auth=auth,
    summary="Show a review (FR-41, BR-13)",
)
def show_review(request, review_id: int):
    """Restore a hidden review to public listing."""
    review = services.set_review_visibility(request.auth, review_id, is_visible=True)
    return services.serialize_admin_review(review)
