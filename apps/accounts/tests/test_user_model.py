"""Smoke tests for the custom user model (task T-005 behaviour)."""
import pytest

from apps.accounts.models import User

pytestmark = pytest.mark.django_db


def test_create_user_defaults_to_customer_without_password():
    user = User.objects.create_user(phone="09123456789")
    assert user.role == "CUSTOMER"
    assert user.get_username() == "09123456789"
    assert not user.has_usable_password()


def test_phone_is_normalised_at_creation():
    user = User.objects.create_user(phone="+98 912 345 6789")
    assert user.phone == "09123456789"


def test_create_superuser_gets_admin_role():
    user = User.objects.create_superuser(phone="09123456789", password="x" * 12)
    assert user.role == "ADMIN"
    assert user.is_staff and user.is_superuser
