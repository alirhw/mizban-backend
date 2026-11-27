"""Tests for Customer Reviews & Ratings (Task T-037 / FR-24, FR-25, BR-09, BR-13)."""
from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.bookings.models import BookingStatus
from apps.bookings.tests.factories import BookingFactory
from apps.panoramas.tests.factories import TablePinFactory
from apps.reviews.models import Review
from apps.venues.tests.factories import UserFactory, VenueFactory
from core.testing import authenticate_client


def _completed_booking(
    *,
    customer: Any = None,
    table_pin: Any = None,
    status: str = BookingStatus.COMPLETED,
    end_at_delta: timedelta = timedelta(hours=-1),
) -> Any:
    now = timezone.now()
    customer = customer or UserFactory(role=UserRole.CUSTOMER)
    table_pin = table_pin or TablePinFactory()
    end_at = now + end_at_delta
    start_at = end_at - timedelta(hours=2)
    return BookingFactory(
        customer=customer,
        table_pin=table_pin,
        status=status,
        start_at=start_at,
        end_at=end_at,
        slot_date=start_at.date(),
        slot_start_time=start_at.time().replace(microsecond=0),
    )


def _post_review(client: Client, payload: dict[str, Any], user: Any = None) -> Any:
    if user is not None:
        authenticate_client(client, user)
    else:
        client.logout()
    return client.post(
        "/api/v1/reviews/",
        data=json.dumps(payload),
        content_type="application/json",
    )


@pytest.mark.django_db
def test_submit_review_happy_path_and_appears_in_venue_and_table_lists(client: Client) -> None:
    """Case 1: COMPLETED booking with end_at <= now creates review (201) and exposes it publicly."""
    customer: Any = UserFactory(role=UserRole.CUSTOMER)
    pin: Any = TablePinFactory(table_number="VIP-7")
    booking: Any = _completed_booking(customer=customer, table_pin=pin)

    resp = _post_review(
        client,
        {"booking_id": booking.id, "rating": 5, "text": "Great atmosphere and service!"},
        user=customer,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["booking_id"] == booking.id
    assert data["rating"] == 5
    assert data["text"] == "Great atmosphere and service!"
    assert data["reviewer_name"] == "Customer"
    assert data["table_number"] == "VIP-7"
    assert data["is_visible"] is True

    venue_resp = client.get(f"/api/v1/reviews/venues/{pin.venue_id}/")
    assert venue_resp.status_code == 200
    venue_data = venue_resp.json()
    assert venue_data["review_count"] == 1
    assert venue_data["average_rating"] == 5.0
    assert [r["id"] for r in venue_data["reviews"]] == [data["id"]]

    table_resp = client.get(f"/api/v1/reviews/tables/{pin.id}/")
    assert table_resp.status_code == 200
    table_data = table_resp.json()
    assert table_data["review_count"] == 1
    assert table_data["average_rating"] == 5.0
    assert [r["id"] for r in table_data["reviews"]] == [data["id"]]


@pytest.mark.django_db
def test_submit_review_rating_bounds_1_and_5_succeed_0_and_6_rejected(client: Client) -> None:
    """Case 2: Ratings 1 and 5 succeed (201); ratings 0 and 6 return 422."""
    customer: Any = UserFactory(role=UserRole.CUSTOMER)
    b1: Any = _completed_booking(customer=customer)
    b5: Any = _completed_booking(customer=customer)
    b_invalid: Any = _completed_booking(customer=customer)

    assert (
        _post_review(
            client, {"booking_id": b1.id, "rating": 1, "text": "Minimum rating"}, user=customer
        ).status_code
        == 201
    )
    assert (
        _post_review(
            client, {"booking_id": b5.id, "rating": 5, "text": "Maximum rating"}, user=customer
        ).status_code
        == 201
    )
    assert (
        _post_review(
            client, {"booking_id": b_invalid.id, "rating": 0, "text": "Too low"}, user=customer
        ).status_code
        == 422
    )
    assert (
        _post_review(
            client, {"booking_id": b_invalid.id, "rating": 6, "text": "Too high"}, user=customer
        ).status_code
        == 422
    )


@pytest.mark.django_db
def test_submit_review_rejects_float_and_boolean_ratings(client: Client) -> None:
    """Case 3: Float (4.5) and raw JSON boolean (true) ratings return 422 (StrictInt)."""
    customer: Any = UserFactory(role=UserRole.CUSTOMER)
    booking: Any = _completed_booking(customer=customer)

    float_resp = _post_review(
        client,
        {"booking_id": booking.id, "rating": 4.5, "text": "Float rating"},
        user=customer,
    )
    assert float_resp.status_code == 422

    bool_resp = _post_review(
        client,
        {"booking_id": booking.id, "rating": True, "text": "Bool rating"},
        user=customer,
    )
    assert bool_resp.status_code == 422
    assert Review.objects.filter(booking=booking).count() == 0


@pytest.mark.django_db
def test_submit_review_text_validation_blank_over_1000_and_exact_1000(client: Client) -> None:
    """Case 4: Empty/blank text and 1001-char text return 422; 1000-char text succeeds (201)."""
    customer: Any = UserFactory(role=UserRole.CUSTOMER)
    booking: Any = _completed_booking(customer=customer)

    for invalid_text in ("", "   \t\n  ", "a" * 1001):
        resp = _post_review(
            client,
            {"booking_id": booking.id, "rating": 4, "text": invalid_text},
            user=customer,
        )
        assert resp.status_code == 422

    ok_resp = _post_review(
        client,
        {"booking_id": booking.id, "rating": 4, "text": "a" * 1000},
        user=customer,
    )
    assert ok_resp.status_code == 201
    assert len(ok_resp.json()["text"]) == 1000


@pytest.mark.django_db
def test_submit_review_rejects_extra_fields(client: Client) -> None:
    """Case 5: Extra fields in ReviewCreateIn return 422 (extra='forbid')."""
    customer: Any = UserFactory(role=UserRole.CUSTOMER)
    booking: Any = _completed_booking(customer=customer)

    resp = _post_review(
        client,
        {
            "booking_id": booking.id,
            "rating": 5,
            "text": "Nice table",
            "is_visible": False,
        },
        user=customer,
    )
    assert resp.status_code == 422


@pytest.mark.django_db
def test_submit_review_duplicate_for_same_booking_returns_409(client: Client) -> None:
    """Case 6: Second review for same booking returns 409 REVIEW_ALREADY_EXISTS with 1 DB row."""
    customer: Any = UserFactory(role=UserRole.CUSTOMER)
    booking: Any = _completed_booking(customer=customer)

    first = _post_review(
        client,
        {"booking_id": booking.id, "rating": 5, "text": "First review"},
        user=customer,
    )
    assert first.status_code == 201

    second = _post_review(
        client,
        {"booking_id": booking.id, "rating": 3, "text": "Second review"},
        user=customer,
    )
    assert second.status_code == 409
    assert second.json()["error_code"] == "REVIEW_ALREADY_EXISTS"
    assert Review.objects.filter(booking=booking).count() == 1


@pytest.mark.django_db
def test_submit_review_non_owner_customer_returns_403(client: Client) -> None:
    """Case 7: Another customer trying to review someone else's booking gets 403 REVIEW_NOT_ALLOWED."""
    owner_customer: Any = UserFactory(role=UserRole.CUSTOMER)
    other_customer: Any = UserFactory(role=UserRole.CUSTOMER)
    booking: Any = _completed_booking(customer=owner_customer)

    resp = _post_review(
        client,
        {"booking_id": booking.id, "rating": 2, "text": "Not my booking"},
        user=other_customer,
    )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "REVIEW_NOT_ALLOWED"


@pytest.mark.django_db
def test_submit_review_confirmed_booking_past_end_returns_409(client: Client) -> None:
    """Case 8: CONFIRMED booking whose end_at has passed returns 409 REVIEW_NOT_ELIGIBLE."""
    customer: Any = UserFactory(role=UserRole.CUSTOMER)
    booking: Any = _completed_booking(
        customer=customer,
        status=BookingStatus.CONFIRMED,
        end_at_delta=timedelta(hours=-2),
    )

    resp = _post_review(
        client,
        {"booking_id": booking.id, "rating": 5, "text": "Still confirmed"},
        user=customer,
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "REVIEW_NOT_ELIGIBLE"


@pytest.mark.django_db
def test_submit_review_completed_booking_future_end_returns_409(client: Client) -> None:
    """Case 9: COMPLETED booking with end_at in the future returns 409 REVIEW_NOT_ELIGIBLE."""
    customer: Any = UserFactory(role=UserRole.CUSTOMER)
    booking: Any = _completed_booking(
        customer=customer,
        status=BookingStatus.COMPLETED,
        end_at_delta=timedelta(hours=2),
    )

    resp = _post_review(
        client,
        {"booking_id": booking.id, "rating": 5, "text": "Future end"},
        user=customer,
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "REVIEW_NOT_ELIGIBLE"


@pytest.mark.django_db
def test_submit_review_cancelled_booking_returns_409(client: Client) -> None:
    """Case 10: CANCELLED booking returns 409 REVIEW_NOT_ELIGIBLE."""
    customer: Any = UserFactory(role=UserRole.CUSTOMER)
    booking: Any = _completed_booking(
        customer=customer,
        status=BookingStatus.CANCELLED,
        end_at_delta=timedelta(hours=-2),
    )

    resp = _post_review(
        client,
        {"booking_id": booking.id, "rating": 1, "text": "Cancelled booking"},
        user=customer,
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "REVIEW_NOT_ELIGIBLE"


@pytest.mark.django_db
def test_venue_reviews_list_filters_hidden_and_computes_average_newest_first(
    client: Client,
) -> None:
    """Case 11: Venue list returns visible reviews newest-first; hidden reviews excluded from list & avg."""
    venue: Any = VenueFactory()
    pin: Any = TablePinFactory(venue=venue)

    b1: Any = _completed_booking(table_pin=pin)
    b2: Any = _completed_booking(table_pin=pin)
    b_hidden: Any = _completed_booking(table_pin=pin)

    r1 = Review.objects.create(booking=b1, rating=4, text="First", is_visible=True)
    r2 = Review.objects.create(booking=b2, rating=5, text="Second", is_visible=True)
    r_hidden = Review.objects.create(booking=b_hidden, rating=1, text="Hidden", is_visible=True)
    Review.objects.filter(pk=r_hidden.pk).update(is_visible=False)

    resp = client.get(f"/api/v1/reviews/venues/{venue.id}/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["review_count"] == 2
    assert body["average_rating"] == 4.5
    assert [r["id"] for r in body["reviews"]] == [r2.id, r1.id]


@pytest.mark.django_db
def test_table_reviews_list_isolates_table_pin_and_computes_average(client: Client) -> None:
    """Case 12: Table list returns only that table's visible reviews and per-table average."""
    venue: Any = VenueFactory()
    pin_a: Any = TablePinFactory(venue=venue, table_number="A1")
    pin_b: Any = TablePinFactory(venue=venue, table_number="B1")

    ba1: Any = _completed_booking(table_pin=pin_a)
    ba2: Any = _completed_booking(table_pin=pin_a)
    bb1: Any = _completed_booking(table_pin=pin_b)

    ra1 = Review.objects.create(booking=ba1, rating=4, text="Pin A one", is_visible=True)
    ra2 = Review.objects.create(booking=ba2, rating=3, text="Pin A two", is_visible=True)
    rb1 = Review.objects.create(booking=bb1, rating=1, text="Pin B one", is_visible=True)

    resp = client.get(f"/api/v1/reviews/tables/{pin_a.id}/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["review_count"] == 2
    assert body["average_rating"] == 3.5
    returned_ids = [r["id"] for r in body["reviews"]]
    assert returned_ids == [ra2.id, ra1.id]
    assert rb1.id not in returned_ids


@pytest.mark.django_db
def test_my_reviews_list_includes_hidden_own_reviews_and_excludes_others(client: Client) -> None:
    """Case 13: GET /my/ returns customer's own reviews including is_visible=False; excludes others."""
    c1: Any = UserFactory(role=UserRole.CUSTOMER)
    c2: Any = UserFactory(role=UserRole.CUSTOMER)

    b_vis: Any = _completed_booking(customer=c1)
    b_hid: Any = _completed_booking(customer=c1)
    b_other: Any = _completed_booking(customer=c2)

    r_vis = Review.objects.create(booking=b_vis, rating=5, text="Visible own", is_visible=True)
    r_hid = Review.objects.create(booking=b_hid, rating=2, text="Hidden own", is_visible=False)
    Review.objects.create(booking=b_other, rating=4, text="Other customer", is_visible=True)

    authenticate_client(client, c1)
    resp_c1 = client.get("/api/v1/reviews/my/")
    assert resp_c1.status_code == 200
    items_c1 = resp_c1.json()
    assert [item["id"] for item in items_c1] == [r_hid.id, r_vis.id]
    assert items_c1[0]["is_visible"] is False
    assert items_c1[1]["is_visible"] is True

    authenticate_client(client, c2)
    resp_c2 = client.get("/api/v1/reviews/my/")
    assert resp_c2.status_code == 200
    assert [item["booking_id"] for item in resp_c2.json()] == [b_other.id]


@pytest.mark.django_db
def test_submit_review_unauthenticated_401_and_venue_owner_403(client: Client) -> None:
    """Case 14: Unauthenticated POST returns 401; VENUE_OWNER POST returns 403."""
    owner: Any = UserFactory(role=UserRole.VENUE_OWNER)
    booking: Any = _completed_booking()

    unauth_resp = _post_review(
        client,
        {"booking_id": booking.id, "rating": 5, "text": "Anon"},
        user=None,
    )
    assert unauth_resp.status_code == 401

    owner_resp = _post_review(
        client,
        {"booking_id": booking.id, "rating": 5, "text": "Owner"},
        user=owner,
    )
    assert owner_resp.status_code == 403


@pytest.mark.django_db
def test_public_venue_reviews_privacy_no_pii_or_internal_fields(client: Client) -> None:
    """Case 15: Public venue review response never exposes phone, email, last_name, booking_id, or is_visible."""
    customer: Any = UserFactory(role=UserRole.CUSTOMER, phone="09128887766")
    pin: Any = TablePinFactory()
    booking: Any = _completed_booking(customer=customer, table_pin=pin)
    Review.objects.create(booking=booking, rating=5, text="Loved the coffee", is_visible=True)

    resp = client.get(f"/api/v1/reviews/venues/{pin.venue_id}/")
    assert resp.status_code == 200
    raw_body = resp.content.decode("utf-8")
    assert customer.phone not in raw_body

    parsed = resp.json()
    assert len(parsed["reviews"]) == 1
    review_obj = parsed["reviews"][0]
    for forbidden_key in ("phone", "email", "last_name", "booking_id", "is_visible"):
        assert forbidden_key not in review_obj
        assert forbidden_key not in raw_body


@pytest.mark.django_db
def test_reviews_empty_venue_and_table_200_and_nonexistent_404(client: Client) -> None:
    """Case 16: Empty venue/table returns 200 with null avg, 0 count, []; nonexistent returns 404."""
    venue: Any = VenueFactory()
    pin: Any = TablePinFactory(venue=venue)

    empty_venue = client.get(f"/api/v1/reviews/venues/{venue.id}/")
    assert empty_venue.status_code == 200
    assert empty_venue.json() == {"average_rating": None, "review_count": 0, "reviews": []}

    empty_table = client.get(f"/api/v1/reviews/tables/{pin.id}/")
    assert empty_table.status_code == 200
    assert empty_table.json() == {"average_rating": None, "review_count": 0, "reviews": []}

    assert client.get("/api/v1/reviews/venues/9999999/").status_code == 404
    assert client.get("/api/v1/reviews/tables/9999999/").status_code == 404


@pytest.mark.django_db
def test_submit_review_nonexistent_booking_returns_404_and_string_rating_422(
    client: Client,
) -> None:
    """Nonexistent booking returns 404; string rating '5' is rejected with 422 by StrictInt."""
    customer: Any = UserFactory(role=UserRole.CUSTOMER)
    booking: Any = _completed_booking(customer=customer)

    missing_resp = _post_review(
        client,
        {"booking_id": 9_999_999, "rating": 5, "text": "Missing booking"},
        user=customer,
    )
    assert missing_resp.status_code == 404

    str_rating_resp = _post_review(
        client,
        {"booking_id": booking.id, "rating": "5", "text": "String rating"},
        user=customer,
    )
    assert str_rating_resp.status_code == 422


@pytest.mark.django_db
def test_my_reviews_unauthenticated_401_and_venue_owner_403_and_pagination(
    client: Client,
) -> None:
    """GET /my/ enforces 401/403 and limit/offset pagination works across all review list endpoints."""
    customer: Any = UserFactory(role=UserRole.CUSTOMER)
    owner: Any = UserFactory(role=UserRole.VENUE_OWNER)
    venue: Any = VenueFactory(owner=owner)
    pin: Any = TablePinFactory(venue=venue)

    assert client.get("/api/v1/reviews/my/").status_code == 401
    authenticate_client(client, owner)
    assert client.get("/api/v1/reviews/my/").status_code == 403

    r1 = Review.objects.create(
        booking=_completed_booking(customer=customer, table_pin=pin),
        rating=3,
        text="First",
        is_visible=True,
    )
    r2 = Review.objects.create(
        booking=_completed_booking(customer=customer, table_pin=pin),
        rating=4,
        text="Second",
        is_visible=True,
    )
    r3 = Review.objects.create(
        booking=_completed_booking(customer=customer, table_pin=pin),
        rating=5,
        text="Third",
        is_visible=True,
    )

    venue_page = client.get(f"/api/v1/reviews/venues/{venue.id}/?limit=1&offset=1")
    assert venue_page.status_code == 200
    assert venue_page.json()["review_count"] == 3
    assert [r["id"] for r in venue_page.json()["reviews"]] == [r2.id]

    table_page = client.get(f"/api/v1/reviews/tables/{pin.id}/?limit=1&offset=1")
    assert table_page.status_code == 200
    assert table_page.json()["review_count"] == 3
    assert [r["id"] for r in table_page.json()["reviews"]] == [r2.id]

    authenticate_client(client, customer)
    my_page = client.get("/api/v1/reviews/my/?limit=1&offset=1")
    assert my_page.status_code == 200
    assert [r["id"] for r in my_page.json()] == [r2.id]
    assert {r1.id, r3.id}.isdisjoint({r["id"] for r in my_page.json()})
