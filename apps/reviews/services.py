"""Service layer for the reviews app (FR-24/FR-25, BR-09/BR-13)."""
from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Avg, Count, QuerySet
from django.http import Http404
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.bookings.models import Booking, BookingStatus
from apps.panoramas.models import TablePin
from apps.reviews.models import Review
from apps.venues.models import Venue
from core.exceptions import (
    ReviewAlreadyExistsError,
    ReviewNotAllowedError,
    ReviewNotEligibleError,
)

logger = logging.getLogger(__name__)


def _reviewer_display_name(customer: Any) -> str:
    """Return a safe public display name (first_name only, or 'Customer')."""
    first_name = getattr(customer, "first_name", "")
    cleaned = first_name.strip() if isinstance(first_name, str) else ""
    return cleaned or "Customer"


def serialize_public_review(review: Review) -> dict[str, Any]:
    """Serialize a Review for public display without exposing customer PII."""
    booking = review.booking
    return {
        "id": review.id,
        "rating": review.rating,
        "text": review.text,
        "reviewer_name": _reviewer_display_name(booking.customer),
        "table_number": booking.table_pin.table_number,
        "created_at": review.created_at,
    }


def serialize_my_review(review: Review) -> dict[str, Any]:
    """Serialize a Review for the authoring customer."""
    data = serialize_public_review(review)
    data["booking_id"] = review.booking_id
    data["is_visible"] = review.is_visible
    return data


def submit_review(*, user: Any, booking_id: int, rating: int, text: str) -> Review:
    """Submit a review for a completed booking owned by the customer (FR-24)."""
    if getattr(user, "role", None) != UserRole.CUSTOMER:
        raise PermissionDenied("Only customers can submit reviews.")

    if isinstance(rating, bool) or not isinstance(rating, int) or not (1 <= rating <= 5):
        raise DjangoValidationError({"rating": "Rating must be an integer between 1 and 5."})

    if not isinstance(text, str):
        raise DjangoValidationError({"text": "Review text must be a string."})
    cleaned_text = text.strip()
    if not cleaned_text or len(cleaned_text) > 1000:
        raise DjangoValidationError(
            {"text": "Review text must be between 1 and 1000 characters."}
        )

    with transaction.atomic():
        booking = (
            Booking.objects.select_for_update()
            .select_related("table_pin", "customer")
            .filter(pk=booking_id)
            .first()
        )
        if booking is None:
            raise Http404("Booking not found.")

        if booking.customer_id != user.id:
            raise ReviewNotAllowedError()

        if booking.status != BookingStatus.COMPLETED or booking.end_at > timezone.now():
            raise ReviewNotEligibleError()

        if Review.objects.filter(booking=booking).exists():
            raise ReviewAlreadyExistsError()

        review = Review.objects.create(
            booking=booking,
            rating=rating,
            text=cleaned_text,
            is_visible=True,
        )

    logger.info(
        "Customer id=%s submitted review id=%s for booking id=%s",
        user.id,
        review.id,
        booking.id,
    )
    return review


def _clamp_pagination(limit: int, offset: int) -> tuple[int, int]:
    """Clamp limit to [1, 100] and offset to [0, inf)."""
    return max(1, min(int(limit), 100)), max(0, int(offset))


def _list_public_reviews(qs: QuerySet[Review], *, limit: int, offset: int) -> dict[str, Any]:
    """Compute SQL aggregates and return paginated serialized public reviews."""
    clamped_limit, clamped_offset = _clamp_pagination(limit, offset)

    agg = qs.aggregate(avg_rating=Avg("rating"), total=Count("id"))
    review_count = int(agg["total"] or 0)
    avg_raw = agg["avg_rating"]
    average_rating = (
        round(float(avg_raw), 1) if avg_raw is not None and review_count > 0 else None
    )

    rows = list(
        qs.select_related("booking__table_pin", "booking__customer").order_by("-created_at")[
            clamped_offset : clamped_offset + clamped_limit
        ]
    )
    return {
        "average_rating": average_rating,
        "review_count": review_count,
        "reviews": [serialize_public_review(review) for review in rows],
    }


def list_venue_reviews(venue_id: int, *, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    """Return visible reviews and aggregate rating for a venue (FR-25)."""
    if not Venue.objects.filter(pk=venue_id).exists():
        raise Http404("Venue not found.")
    qs = Review.objects.filter(booking__table_pin__venue_id=venue_id, is_visible=True)
    return _list_public_reviews(qs, limit=limit, offset=offset)


def list_table_reviews(table_pin_id: int, *, limit: int = 20, offset: int = 0) -> dict[str, Any]:
    """Return visible reviews and aggregate rating for a table pin (FR-25)."""
    if not TablePin.objects.filter(pk=table_pin_id).exists():
        raise Http404("Table not found.")
    qs = Review.objects.filter(booking__table_pin_id=table_pin_id, is_visible=True)
    return _list_public_reviews(qs, limit=limit, offset=offset)


def list_my_reviews(user: Any, *, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
    """Return all reviews authored by the authenticated customer (including hidden)."""
    if getattr(user, "role", None) != UserRole.CUSTOMER:
        raise PermissionDenied("Only customers can view their reviews.")

    clamped_limit, clamped_offset = _clamp_pagination(limit, offset)
    rows = list(
        Review.objects.filter(booking__customer_id=user.id)
        .select_related("booking__table_pin", "booking__customer")
        .order_by("-created_at")[clamped_offset : clamped_offset + clamped_limit]
    )
    return [serialize_my_review(review) for review in rows]


def _require_admin(admin_user: Any) -> None:
    """Ensure the caller has administrator privileges."""
    if not (
        getattr(admin_user, "is_staff", False)
        or getattr(admin_user, "role", None) == UserRole.ADMIN
    ):
        raise PermissionDenied("Only administrators can moderate reviews.")


def serialize_admin_review(review: Review) -> dict[str, Any]:
    """Serialize a Review for admin moderation."""
    data = serialize_my_review(review)
    data["venue_id"] = review.booking.venue_id
    return data


def set_review_visibility(
    admin_user: Any,
    review_id: int,
    *,
    is_visible: bool,
) -> Review:
    """Hide or show a review (FR-41, BR-13)."""
    _require_admin(admin_user)

    with transaction.atomic():
        review = (
            Review.objects.select_for_update()
            .select_related("booking__table_pin", "booking__customer")
            .filter(pk=review_id)
            .first()
        )
        if review is None:
            raise Http404("Review not found.")

        if review.is_visible != is_visible:
            review.is_visible = is_visible
            review.save(update_fields=["is_visible"])

    logger.info(
        "Admin id=%s set review id=%s visibility is_visible=%s",
        admin_user.id,
        review.id,
        is_visible,
    )
    return review


def list_admin_reviews(
    admin_user: Any,
    *,
    venue_id: int | None = None,
    is_visible: bool | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return paginated reviews for admin moderation with optional filters."""
    _require_admin(admin_user)

    qs = Review.objects.select_related("booking__table_pin", "booking__customer").order_by(
        "-created_at"
    )
    if venue_id is not None:
        qs = qs.filter(booking__venue_id=venue_id)
    if is_visible is not None:
        qs = qs.filter(is_visible=is_visible)

    clamped_limit, clamped_offset = _clamp_pagination(limit, offset)
    rows = list(qs[clamped_offset : clamped_offset + clamped_limit])
    return [serialize_admin_review(r) for r in rows]
