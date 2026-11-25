"""Regression tests for DEV-ONLY seed management commands (Task T-028-FIX / B1)."""
from __future__ import annotations

import pytest
from django.core.management import call_command
from django.test import override_settings

from apps.venues.models import SubscriptionPlan, Venue

pytestmark = pytest.mark.django_db


@override_settings(DEBUG=True)
def test_seed_dev_panorama_clear_preserves_real_cafe_and_shared_plan():
    call_command("seed_dev_panorama")
    call_command("seed_dev_real_cafe")

    assert Venue.objects.filter(slug="sample-cafe-dev").exists()
    assert Venue.objects.filter(slug="real-cafe-dev").exists()
    assert SubscriptionPlan.objects.filter(name="طرح نمونه توسعه").exists()

    call_command("seed_dev_panorama", "--clear")

    assert not Venue.objects.filter(slug="sample-cafe-dev").exists()
    assert Venue.objects.filter(slug="real-cafe-dev").exists()
    assert SubscriptionPlan.objects.filter(name="طرح نمونه توسعه").exists()
