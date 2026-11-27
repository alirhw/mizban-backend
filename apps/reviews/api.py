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
from apps.reviews.schemas import ReviewCreateIn, ReviewListOut, ReviewMineOut

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
