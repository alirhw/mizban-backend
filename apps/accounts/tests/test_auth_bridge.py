"""Tests for minimal authenticated identity bridge (Task T-009).

Verifies that development-only authentication fallback paths
(X-User-Phone header and Bearer-by-phone-lookup) are active ONLY
under DEBUG=True and strictly disabled under non-debug settings (DEBUG=False).
"""
import pytest
from django.test import RequestFactory, override_settings

from apps.accounts.auth import MinimalAuth
from apps.accounts.models import User

pytestmark = pytest.mark.django_db


@pytest.fixture
def auth_bridge():
    return MinimalAuth()


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def sample_user():
    return User.objects.create_user(phone="09121112233", role="VENUE_OWNER")


def test_auth_bridge_active_when_debug_true(auth_bridge, rf, sample_user):
    """Under DEBUG=True, X-User-Phone and Bearer-by-phone lookups succeed."""
    with override_settings(DEBUG=True):
        # 1. Test X-User-Phone header
        req_header = rf.get("/api/v1/venues/owner/venues", HTTP_X_USER_PHONE="09121112233")
        assert auth_bridge(req_header) == sample_user

        # 2. Test Bearer token lookup
        req_bearer = rf.get(
            "/api/v1/venues/owner/venues",
            HTTP_AUTHORIZATION="Bearer 09121112233",
        )
        assert auth_bridge(req_bearer) == sample_user


def test_auth_bridge_disabled_when_debug_false(auth_bridge, rf, sample_user):
    """Under DEBUG=False, X-User-Phone and Bearer-by-phone lookups are completely rejected."""
    with override_settings(DEBUG=False):
        # 1. Test X-User-Phone header is ignored/rejected
        req_header = rf.get("/api/v1/venues/owner/venues", HTTP_X_USER_PHONE="09121112233")
        assert auth_bridge(req_header) is None

        # 2. Test Bearer token lookup is rejected
        req_bearer = rf.get(
            "/api/v1/venues/owner/venues",
            HTTP_AUTHORIZATION="Bearer 09121112233",
        )
        assert auth_bridge(req_bearer) is None


def test_session_auth_still_allowed_when_debug_false(auth_bridge, rf, sample_user):
    """Standard Django session authentication remains valid under DEBUG=False."""
    with override_settings(DEBUG=False):
        req = rf.get("/api/v1/venues/owner/venues")
        req.user = sample_user  # Simulates an active Django session
        assert auth_bridge(req) == sample_user
