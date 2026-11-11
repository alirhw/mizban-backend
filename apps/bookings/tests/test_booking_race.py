"""FAIL-FIRST target: the double-booking race (TD-004 / task T-012).

Two customers initiate a booking for the SAME table pin and slot at the
SAME moment. Exactly one must win a PENDING_PAYMENT lock; the other must
be rejected with SlotAlreadyReservedError (-> HTTP 409
SLOT_ALREADY_RESERVED). Zero double-bookings is success criterion #3 of
the product definition.

Status: SKIPPED until tasks T-011 (Booking model) and T-012 (lock
service) land. The factories referenced below (user_factory /
table_pin_factory) arrive with those tasks - wire them up, remove the
skip marker, and make this pass. Do not weaken the assertions.

IMPORTANT: this test only proves anything against PostgreSQL.
select_for_update() is a no-op on SQLite, so a green run on SQLite is
meaningless - run it against the docker-compose Postgres.
"""
from concurrent.futures import ThreadPoolExecutor

import pytest

from apps.bookings.services import create_booking_lock
from core.exceptions import SlotAlreadyReservedError

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.skip(reason="pending T-011/T-012 models/services"),
]


def _attempt(kwargs):
    try:
        return ("created", create_booking_lock(**kwargs))
    except SlotAlreadyReservedError:
        return ("conflict", None)


def test_two_simultaneous_initiates_exactly_one_wins():
    # user_factory / table_pin_factory land with T-008 / T-011.
    pin = table_pin_factory()  # noqa: F821 - provided by T-011 factories
    slot = pin.next_bookable_slot()  # noqa: F821 - helper from the scheduling tasks
    kwargs = dict(table_pin=pin, slot_date=slot.date, slot_start_time=slot.start_time)
    attempts = [
        dict(user=user_factory(), **kwargs),  # noqa: F821 - provided by T-008 factories
        dict(user=user_factory(), **kwargs),  # noqa: F821
    ]

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(result for result, _ in pool.map(_attempt, attempts))

    assert outcomes == ["conflict", "created"]
