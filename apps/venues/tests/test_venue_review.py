"""Tests for Venue Submission & Rejection Feedback Loop (Task T-036 / FR-33, FR-37, FR-39)."""
from __future__ import annotations

import json
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from apps.accounts.models import UserRole
from apps.venues.models import VenueReviewStatus
from apps.venues.tests.factories import UserFactory, VenueFactory, activate_test_subscription
from core.testing import authenticate_client


class ApiHelper:
    """Thin test client helper for authenticated JSON requests."""

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


@pytest.fixture
def admin_user():
    return UserFactory(role=UserRole.ADMIN, is_staff=True)


@pytest.mark.django_db
def test_submit_from_draft_transitions_to_pending_review(api, owner_user):
    """Case 1: Submitting a DRAFT venue sets PENDING_REVIEW and timestamp while keeping is_approved=False."""
    venue = VenueFactory(owner=owner_user, review_status=VenueReviewStatus.DRAFT, is_approved=False)

    response = api.post(f"/api/v1/venues/owner/venues/{venue.id}/submit", user=owner_user)

    assert response.status_code == 200
    payload = response.json()
    assert payload["review_status"] == VenueReviewStatus.PENDING_REVIEW
    assert payload["is_approved"] is False
    assert payload["submitted_for_review_at"] is not None

    venue.refresh_from_db()
    assert venue.review_status == VenueReviewStatus.PENDING_REVIEW
    assert venue.is_approved is False
    assert venue.submitted_for_review_at is not None


@pytest.mark.django_db
def test_submit_from_pending_review_returns_409(api, owner_user):
    """Case 2: Submitting a venue already in PENDING_REVIEW returns 409 VENUE_NOT_SUBMITTABLE."""
    submitted_at = timezone.now() - timedelta(hours=1)
    venue = VenueFactory(
        owner=owner_user,
        review_status=VenueReviewStatus.PENDING_REVIEW,
        is_approved=False,
        submitted_for_review_at=submitted_at,
    )

    response = api.post(f"/api/v1/venues/owner/venues/{venue.id}/submit", user=owner_user)

    assert response.status_code == 409
    assert response.json()["error_code"] == "VENUE_NOT_SUBMITTABLE"

    venue.refresh_from_db()
    assert venue.review_status == VenueReviewStatus.PENDING_REVIEW
    assert venue.submitted_for_review_at == submitted_at


@pytest.mark.django_db
def test_submit_from_approved_returns_409(api, owner_user):
    """Case 3: Submitting an APPROVED venue returns 409 VENUE_NOT_SUBMITTABLE."""
    venue = VenueFactory(
        owner=owner_user,
        review_status=VenueReviewStatus.APPROVED,
        is_approved=True,
    )

    response = api.post(f"/api/v1/venues/owner/venues/{venue.id}/submit", user=owner_user)

    assert response.status_code == 409
    assert response.json()["error_code"] == "VENUE_NOT_SUBMITTABLE"


@pytest.mark.django_db
def test_submit_permissions_and_not_found(api, owner_user, other_owner_user, customer_user):
    """Case 4: Submitting another owner's venue -> 403, nonexistent -> 404, CUSTOMER -> 403."""
    venue = VenueFactory(owner=owner_user, review_status=VenueReviewStatus.DRAFT)

    other_resp = api.post(f"/api/v1/venues/owner/venues/{venue.id}/submit", user=other_owner_user)
    assert other_resp.status_code == 403

    not_found_resp = api.post("/api/v1/venues/owner/venues/999999/submit", user=owner_user)
    assert not_found_resp.status_code == 404

    customer_resp = api.post(f"/api/v1/venues/owner/venues/{venue.id}/submit", user=customer_user)
    assert customer_resp.status_code == 403


@pytest.mark.django_db
def test_admin_reject_with_reason_stores_stripped_reason_and_exposes_to_owner(
    api, admin_user, owner_user
):
    """Case 5: Admin reject stores stripped reason and owner detail exposes it."""
    venue = VenueFactory(
        owner=owner_user,
        review_status=VenueReviewStatus.PENDING_REVIEW,
        is_approved=False,
    )

    reject_resp = api.post(
        f"/api/v1/venues/admin/venues/{venue.id}/reject",
        data={"reason": "  Missing interior photos  "},
        user=admin_user,
    )

    assert reject_resp.status_code == 200
    reject_payload = reject_resp.json()
    assert reject_payload["review_status"] == VenueReviewStatus.REJECTED
    assert reject_payload["is_approved"] is False
    assert reject_payload["rejection_reason"] == "Missing interior photos"

    venue.refresh_from_db()
    assert venue.review_status == VenueReviewStatus.REJECTED
    assert venue.is_approved is False
    assert venue.rejection_reason == "Missing interior photos"

    owner_detail_resp = api.get(f"/api/v1/venues/owner/venues/{venue.id}", user=owner_user)
    assert owner_detail_resp.status_code == 200
    assert owner_detail_resp.json()["rejection_reason"] == "Missing interior photos"


@pytest.mark.django_db
def test_admin_reject_without_or_blank_reason_returns_422(api, admin_user, owner_user):
    """Case 6: Rejecting without a reason or with a blank/whitespace reason returns 422."""
    venue = VenueFactory(owner=owner_user, review_status=VenueReviewStatus.PENDING_REVIEW)

    empty_body_resp = api.post(
        f"/api/v1/venues/admin/venues/{venue.id}/reject",
        data={},
        user=admin_user,
    )
    assert empty_body_resp.status_code == 422

    empty_reason_resp = api.post(
        f"/api/v1/venues/admin/venues/{venue.id}/reject",
        data={"reason": ""},
        user=admin_user,
    )
    assert empty_reason_resp.status_code == 422

    blank_resp = api.post(
        f"/api/v1/venues/admin/venues/{venue.id}/reject",
        data={"reason": "   \t\n  "},
        user=admin_user,
    )
    assert blank_resp.status_code == 422


@pytest.mark.django_db
def test_admin_reject_reason_over_1000_chars_returns_422_and_leaves_state_unchanged(
    api, admin_user, owner_user
):
    """Case 7: Rejecting with a reason longer than 1000 chars returns 422 and leaves state unchanged."""
    venue = VenueFactory(
        owner=owner_user,
        review_status=VenueReviewStatus.PENDING_REVIEW,
        is_approved=False,
        rejection_reason="",
    )

    response = api.post(
        f"/api/v1/venues/admin/venues/{venue.id}/reject",
        data={"reason": "a" * 1001},
        user=admin_user,
    )

    assert response.status_code == 422
    venue.refresh_from_db()
    assert venue.review_status == VenueReviewStatus.PENDING_REVIEW
    assert venue.is_approved is False
    assert venue.rejection_reason == ""


@pytest.mark.django_db
def test_non_admin_cannot_reject_venue(api, owner_user):
    """Case 8: Non-admin (including the venue owner) receives 403 when calling reject."""
    venue = VenueFactory(owner=owner_user, review_status=VenueReviewStatus.PENDING_REVIEW)

    response = api.post(
        f"/api/v1/venues/admin/venues/{venue.id}/reject",
        data={"reason": "Self reject"},
        user=owner_user,
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_admin_approve_pending_review_clears_earlier_rejection_reason(
    api, admin_user, owner_user
):
    """Case 9: Approving a PENDING_REVIEW venue sets APPROVED, is_approved=True, and clears rejection_reason."""
    venue = VenueFactory(
        owner=owner_user,
        review_status=VenueReviewStatus.PENDING_REVIEW,
        is_approved=False,
        rejection_reason="Stale reason",
    )

    response = api.post(f"/api/v1/venues/admin/venues/{venue.id}/approve", user=admin_user)

    assert response.status_code == 200
    payload = response.json()
    assert payload["review_status"] == VenueReviewStatus.APPROVED
    assert payload["is_approved"] is True
    assert payload["rejection_reason"] == ""

    venue.refresh_from_db()
    assert venue.review_status == VenueReviewStatus.APPROVED
    assert venue.is_approved is True
    assert venue.rejection_reason == ""


@pytest.mark.django_db
def test_admin_can_approve_rejected_venue_directly(api, admin_user, owner_user):
    """Case 10: Admin can approve a REJECTED venue directly and clear its rejection_reason."""
    venue = VenueFactory(
        owner=owner_user,
        review_status=VenueReviewStatus.REJECTED,
        is_approved=False,
        rejection_reason="Address was unclear",
    )

    response = api.post(f"/api/v1/venues/admin/venues/{venue.id}/approve", user=admin_user)

    assert response.status_code == 200
    payload = response.json()
    assert payload["review_status"] == VenueReviewStatus.APPROVED
    assert payload["is_approved"] is True
    assert payload["rejection_reason"] == ""

    venue.refresh_from_db()
    assert venue.review_status == VenueReviewStatus.APPROVED
    assert venue.is_approved is True
    assert venue.rejection_reason == ""


@pytest.mark.django_db
def test_fr37_reject_edit_resubmit_flow(api, admin_user, owner_user):
    """Case 11: FR-37 flow: reject -> owner edits -> owner resubmits -> PENDING_REVIEW, cleared reason, newer ts."""
    first_submitted_at = timezone.now() - timedelta(minutes=10)
    venue = VenueFactory(
        owner=owner_user,
        review_status=VenueReviewStatus.PENDING_REVIEW,
        is_approved=False,
        submitted_for_review_at=first_submitted_at,
    )

    reject_resp = api.post(
        f"/api/v1/venues/admin/venues/{venue.id}/reject",
        data={"reason": "Update description and name"},
        user=admin_user,
    )
    assert reject_resp.status_code == 200

    edit_resp = api.put(
        f"/api/v1/venues/owner/venues/{venue.id}",
        data={"name": "Revised Cafe", "description": "Updated description with full details."},
        user=owner_user,
    )
    assert edit_resp.status_code == 200

    resubmit_resp = api.post(f"/api/v1/venues/owner/venues/{venue.id}/submit", user=owner_user)
    assert resubmit_resp.status_code == 200
    payload = resubmit_resp.json()
    assert payload["review_status"] == VenueReviewStatus.PENDING_REVIEW
    assert payload["rejection_reason"] == ""

    venue.refresh_from_db()
    assert venue.review_status == VenueReviewStatus.PENDING_REVIEW
    assert venue.rejection_reason == ""
    assert venue.submitted_for_review_at is not None
    assert venue.submitted_for_review_at > first_submitted_at


@pytest.mark.django_db
def test_public_endpoints_hide_rejected_venue_and_never_expose_rejection_reason(
    api, admin_user, owner_user
):
    """Case 12: Rejected venue (even with active subscription) is hidden publicly and leaks no rejection_reason."""
    venue = VenueFactory(
        owner=owner_user,
        name="Rejected Hidden Cafe",
        slug="rejected-hidden-cafe",
        review_status=VenueReviewStatus.REJECTED,
        is_approved=False,
        rejection_reason="Internal moderation note",
    )
    activate_test_subscription(venue, activated_by=admin_user)

    detail_resp = api.get(f"/api/v1/venues/{venue.slug}")
    assert detail_resp.status_code == 404
    assert "rejection_reason" not in detail_resp.content.decode()
    assert "Internal moderation note" not in detail_resp.content.decode()

    list_resp = api.get("/api/v1/venues/")
    assert list_resp.status_code == 200
    assert list_resp.json() == []
    assert "rejection_reason" not in list_resp.content.decode()


@pytest.mark.django_db
def test_owner_and_admin_endpoints_expose_review_fields(api, admin_user, owner_user):
    """Case 13: Owner list/detail and admin approve/reject responses expose review fields."""
    submitted_at = timezone.now() - timedelta(minutes=5)
    venue = VenueFactory(
        owner=owner_user,
        review_status=VenueReviewStatus.PENDING_REVIEW,
        is_approved=False,
        submitted_for_review_at=submitted_at,
    )

    reject_resp = api.post(
        f"/api/v1/venues/admin/venues/{venue.id}/reject",
        data={"reason": "Incomplete address"},
        user=admin_user,
    )
    assert reject_resp.status_code == 200
    reject_data = reject_resp.json()
    assert reject_data["review_status"] == VenueReviewStatus.REJECTED
    assert reject_data["rejection_reason"] == "Incomplete address"

    list_resp = api.get("/api/v1/venues/owner/venues", user=owner_user)
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 1
    assert items[0]["review_status"] == VenueReviewStatus.REJECTED
    assert items[0]["rejection_reason"] == "Incomplete address"
    assert items[0]["submitted_for_review_at"] is not None

    detail_resp = api.get(f"/api/v1/venues/owner/venues/{venue.id}", user=owner_user)
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["review_status"] == VenueReviewStatus.REJECTED
    assert detail["rejection_reason"] == "Incomplete address"
    assert detail["submitted_for_review_at"] is not None

    approve_resp = api.post(f"/api/v1/venues/admin/venues/{venue.id}/approve", user=admin_user)
    assert approve_resp.status_code == 200
    approve_data = approve_resp.json()
    assert approve_data["review_status"] == VenueReviewStatus.APPROVED
    assert approve_data["rejection_reason"] == ""


@pytest.mark.django_db
def test_no_pending_migrations():
    """Case 14: Django makemigrations --check --dry-run reports no pending model changes."""
    call_command("makemigrations", "--check", "--dry-run")
