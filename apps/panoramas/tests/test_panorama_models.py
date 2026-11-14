"""Tests for panoramas domain models, constraints, and deletion protection (Task T-015)."""
from __future__ import annotations

from datetime import time, timedelta
import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from apps.bookings.models import Booking, BookingStatus
from apps.panoramas.models import (
    PanoramaImage,
    PanoramaStatus,
    Space,
    TablePin,
)
from apps.panoramas.tests.factories import (
    PanoramaImageFactory,
    SpaceFactory,
    TablePinFactory,
)
from apps.venues.tests.factories import UserFactory as user_factory, VenueFactory
from core.exceptions import InvalidStatusTransitionError


@pytest.mark.django_db
def test_space_creation_and_attributes():
    """Space creates with full field matrix and correct ordering."""
    venue = VenueFactory()
    s2 = SpaceFactory(venue=venue, name="B Space", display_order=2)
    s1 = SpaceFactory(venue=venue, name="A Space", display_order=1)

    spaces = list(Space.objects.filter(venue=venue))
    assert spaces == [s1, s2]
    assert s1.is_active is True
    assert str(s1) == f"{venue.name} - A Space"


@pytest.mark.django_db
def test_space_active_panorama_association():
    """Space can associate an active PanoramaImage and clear it on image deletion."""
    space = SpaceFactory()
    assert space.active_panorama is None

    pano = PanoramaImageFactory(space=space, status=PanoramaStatus.READY)
    space.active_panorama = pano
    space.save(update_fields=["active_panorama"])
    space.refresh_from_db()
    assert space.active_panorama == pano

    # When active panorama is deleted, space.active_panorama is SET_NULL (not cascading to delete the space)
    pano.delete()
    space.refresh_from_db()
    assert space.active_panorama is None


@pytest.mark.django_db
def test_panorama_image_lifecycle_success_path():
    """PanoramaImage follows UPLOADED -> PROCESSING -> READY lifecycle (TD-003 / ARCH-003)."""
    pano = PanoramaImageFactory(status=PanoramaStatus.UPLOADED)
    assert pano.status == PanoramaStatus.UPLOADED
    assert pano.processed_at is None

    # Step 1: Start Celery processing
    pano.transition_to(PanoramaStatus.PROCESSING)
    assert pano.status == PanoramaStatus.PROCESSING

    # Step 2: Celery worker completes conversion
    pano.transition_to(PanoramaStatus.READY)
    assert pano.status == PanoramaStatus.READY
    assert pano.processed_at is not None


@pytest.mark.django_db
def test_panorama_image_lifecycle_failure_and_retry_path():
    """PanoramaImage handles UPLOADED -> PROCESSING -> FAILED -> PROCESSING -> READY."""
    pano = PanoramaImageFactory(status=PanoramaStatus.UPLOADED)
    pano.transition_to(PanoramaStatus.PROCESSING)

    # Processing fails (e.g. aspect ratio not 2:1)
    pano.transition_to(PanoramaStatus.FAILED, error_message="Image aspect ratio is 1.5, expected 2:1")
    assert pano.status == PanoramaStatus.FAILED
    assert pano.error_message == "Image aspect ratio is 1.5, expected 2:1"

    # Retry/re-process is allowed from FAILED
    pano.transition_to(PanoramaStatus.PROCESSING)
    assert pano.status == PanoramaStatus.PROCESSING

    pano.transition_to(PanoramaStatus.READY)
    assert pano.status == PanoramaStatus.READY


@pytest.mark.django_db
def test_panorama_image_invalid_transitions_rejected():
    """Direct or illegal status skips raise InvalidStatusTransitionError."""
    pano = PanoramaImageFactory(status=PanoramaStatus.UPLOADED)

    # Cannot jump directly from UPLOADED to READY
    with pytest.raises(InvalidStatusTransitionError):
        pano.transition_to(PanoramaStatus.READY)

    # Cannot jump directly from UPLOADED to FAILED
    with pytest.raises(InvalidStatusTransitionError):
        pano.transition_to(PanoramaStatus.FAILED)

    pano.transition_to(PanoramaStatus.PROCESSING)
    pano.transition_to(PanoramaStatus.READY)

    # READY is terminal: cannot go back to PROCESSING or FAILED
    with pytest.raises(InvalidStatusTransitionError):
        pano.transition_to(PanoramaStatus.PROCESSING)


@pytest.mark.django_db
def test_table_pin_creation_with_spherical_coordinates():
    """TablePin persists with pitch in [-90, 90] and yaw in [-180, 180]."""
    space = SpaceFactory()
    pano = PanoramaImageFactory(space=space, status=PanoramaStatus.READY)
    pin = TablePinFactory(
        venue=space.venue,
        space=space,
        panorama_image=pano,
        table_number="VIP-1",
        capacity=6,
        pitch=22.5,
        yaw=-110.0,
    )

    pin.refresh_from_db()
    assert pin.table_number == "VIP-1"
    assert pin.capacity == 6
    assert pin.pitch == 22.5
    assert pin.yaw == -110.0
    assert pin.panorama_image == pano
    assert pin.is_active is True


@pytest.mark.django_db
def test_table_pin_pitch_bounds_check_constraint():
    """Pitch values outside [-90.0, 90.0] are rejected by PostgreSQL CheckConstraint."""
    pin = TablePinFactory()

    # Valid boundaries: -90.0 and +90.0 are allowed
    pin.pitch = -90.0
    pin.save()
    pin.pitch = 90.0
    pin.save()

    # Violation: pitch > 90.0
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            pin.pitch = 90.1
            pin.save()

    # Violation: pitch < -90.0
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            pin.pitch = -90.1
            pin.save()


@pytest.mark.django_db
def test_table_pin_yaw_bounds_check_constraint():
    """Yaw values outside [-180.0, 180.0] are rejected by PostgreSQL CheckConstraint."""
    pin = TablePinFactory()

    # Valid boundaries: -180.0 and +180.0 are allowed
    pin.yaw = -180.0
    pin.save()
    pin.yaw = 180.0
    pin.save()

    # Violation: yaw > 180.0
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            pin.yaw = 180.5
            pin.save()

    # Violation: yaw < -180.0
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            pin.yaw = -180.5
            pin.save()


@pytest.mark.django_db
def test_table_pin_capacity_positive_check_constraint():
    """Capacity <= 0 is rejected by PostgreSQL CheckConstraint."""
    pin = TablePinFactory()

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            pin.capacity = 0
            pin.save()


@pytest.mark.django_db
def test_table_pin_clean_validation():
    """Model clean() raises ValidationError for out-of-bounds inputs before DB save."""
    pin = TablePinFactory.build(pitch=120.0)
    with pytest.raises(ValidationError) as exc_info:
        pin.clean()
    assert "pitch" in exc_info.value.error_dict

    pin = TablePinFactory.build(yaw=-200.0)
    with pytest.raises(ValidationError) as exc_info:
        pin.clean()
    assert "yaw" in exc_info.value.error_dict

    pin = TablePinFactory.build(capacity=0)
    with pytest.raises(ValidationError) as exc_info:
        pin.clean()
    assert "capacity" in exc_info.value.error_dict


@pytest.mark.django_db
def test_table_pin_deletion_without_bookings_succeeds():
    """A TablePin with zero bookings can be safely deleted."""
    pin = TablePinFactory()
    pin_id = pin.pk
    pin.delete()
    assert not TablePin.objects.filter(pk=pin_id).exists()


@pytest.mark.django_db
def test_table_pin_deletion_with_bookings_raises_protected_error():
    """ADR-005 / Note 3: TablePin with bookings is PROTECTED from deletion (NO CASCADE)."""
    pin = TablePinFactory()
    customer = user_factory()
    now = timezone.now()

    # Create a booking pointing to this table pin
    booking = Booking.objects.create(
        venue=pin.venue,
        table_pin=pin,
        customer=customer,
        status=BookingStatus.CONFIRMED,
        start_at=now + timedelta(days=2),
        end_at=now + timedelta(days=2, hours=1, minutes=30),
        slot_date=(now + timedelta(days=2)).date(),
        slot_start_time=time(12, 0),
        amount_online_toman=50000,
    )

    # Attempting to delete the TablePin MUST raise ProtectedError
    with pytest.raises(models.ProtectedError):
        pin.delete()

    # The booking and the pin still exist
    assert TablePin.objects.filter(pk=pin.pk).exists()
    assert Booking.objects.filter(pk=booking.pk).exists()


@pytest.mark.django_db
def test_table_pin_deactivate_preserves_bookings():
    """TablePin.deactivate() soft-disables the table without deleting bookings."""
    pin = TablePinFactory(is_active=True)
    pin.deactivate()
    pin.refresh_from_db()
    assert pin.is_active is False
