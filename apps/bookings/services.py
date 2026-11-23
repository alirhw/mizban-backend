"""Booking service layer - atomic lock creation and cancellation.

Task T-012:
- create_booking_lock inside transaction.atomic() with TablePin.objects.select_for_update()
- On success creates Booking(status=PENDING_PAYMENT, locked_at=now, lock_expires_at=now + 10m)
- On contention the second concurrent initiate fails cleanly with SlotAlreadyReservedError (HTTP 409)
- Expired locks (lock_expires_at in the past) do not block a new lock
- Respects slot-generation rules (BR-001/BR-002) and availability interface
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import logging
from typing import TYPE_CHECKING, Any, Iterable, Optional, Union

from django.core.exceptions import PermissionDenied
from django.db import models, transaction
from django.http import Http404
from django.utils import timezone as dj_timezone

from apps.bookings.models import Booking, BookingAddon, BookingStatus
from core.exceptions import (
    BookingNotCancellableError,
    CancellationWindowClosedError,
    LeadTimeViolationError,
    ReceiptDataInconsistencyError,
    ReceiptNotAvailableError,
    SlotAlreadyReservedError,
)
from core.jalali import TEHRAN

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from apps.panoramas.models import TablePin

LOCK_TTL = timedelta(minutes=10)
SLOT_DURATION = timedelta(minutes=90)
LEAD_TIME_THRESHOLD = timedelta(hours=24)
CANCELLATION_WINDOW_THRESHOLD = timedelta(hours=36)
RECEIPT_AVAILABLE_STATUSES = {BookingStatus.CONFIRMED, BookingStatus.COMPLETED}


@dataclass(frozen=True)
class BookingCancelResult:
    """Outcome of a booking cancellation operation (Task T-023 / BR-004)."""

    booking_id: int
    status: str
    refunded_to_wallet_toman: int
    wallet_balance_toman: Optional[int] = None


@dataclass(frozen=True)
class SplitReceiptOnlineSection:
    """Paid-online section of a split receipt (BR-003: 100% platform share)."""

    label: str
    description: str
    amount_online_toman: int
    provider_name: Optional[str] = None
    card_pan_masked: Optional[str] = None


@dataclass(frozen=True)
class SplitReceiptAddonLine:
    """One itemised design add-on line payable in person at the venue (BR-003)."""

    addon_id: int
    title: str
    unit_fee_toman: int
    line_total_toman: int


@dataclass(frozen=True)
class SplitReceiptInPersonSection:
    """Payable-in-person section of a split receipt (BR-003)."""

    label: str
    items: list[SplitReceiptAddonLine]
    total_in_person_toman: int


@dataclass(frozen=True)
class SplitReceiptResult:
    """Read-only structured split receipt for one booking (Task T-024 / BR-003 / ARCH-005)."""

    booking_id: int
    status: str
    venue_name: str
    venue_slug: str
    table_number: str
    start_at: datetime
    end_at: datetime
    slot_date: date
    slot_start_time: time
    jalali_date: str
    jalali_start_datetime: str
    jalali_end_datetime: str
    paid_online: SplitReceiptOnlineSection
    payable_in_person: SplitReceiptInPersonSection
    total_online_toman: int
    total_in_person_toman: int
    grand_total_toman: int



def is_table_slot_occupied(
    table_pin: Union[TablePin, int],
    start_at: Optional[datetime] = None,
    slot_date: Optional[date] = None,
    slot_start_time: Optional[time] = None,
    now: Optional[datetime] = None,
) -> bool:
    """Check if a table pin is occupied by an active booking or lock.

    INTERFACE SPECIFICATION FOR TASK T-012 (Lock Service) & T-013 (Initiate Booking):
    A slot is considered occupied if any Booking exists with:
      - status == CONFIRMED, OR
      - status == PENDING_PAYMENT with lock_expires_at > now (active hold).
    Cancelled, expired, or completed bookings do not occupy the slot.
    ARCH-004: Computed at query-time from DB; never cached.
    """
    pin_id = table_pin if isinstance(table_pin, int) else table_pin.pk
    if now is None:
        now = dj_timezone.now()

    qs = Booking.objects.filter(table_pin_id=pin_id)
    if start_at is not None:
        qs = qs.filter(start_at=start_at)
    elif slot_date is not None and slot_start_time is not None:
        qs = qs.filter(slot_date=slot_date, slot_start_time=slot_start_time)
    else:
        raise ValueError("Must provide either start_at or both slot_date and slot_start_time.")

    return qs.filter(
        models.Q(status=BookingStatus.CONFIRMED)
        | models.Q(status=BookingStatus.PENDING_PAYMENT, lock_expires_at__gt=now)
    ).exists()


def filter_available_slots_for_table(
    table_pin: Union[TablePin, int],
    slots: list,
    now: Optional[datetime] = None,
) -> list:
    """Filter generated calendar slots against active bookings and locks."""
    if now is None:
        now = dj_timezone.now()

    available = []
    for slot in slots:
        if not is_table_slot_occupied(table_pin=table_pin, start_at=slot.start, now=now):
            available.append(slot)
    return available


def create_booking_lock(
    *,
    user: Any,
    table_pin: Union[TablePin, int],
    slot_date: date,
    slot_start_time: time,
    addon_ids: Iterable[int] = (),
    now: Optional[datetime] = None,
) -> Booking:
    """Acquire a 10-minute temporary reservation lock for a table pin and slot (TD-004).

    Guarantees:
    - Atomicity: Runs inside transaction.atomic() with select_for_update() on the TablePin row.
    - Concurrency safety: Zero double-bookings under concurrent attempts; exactly one wins.
    - BR-002: Rejects slots starting less than 24h from now with LeadTimeViolationError.
    - REQ-LOCK-005: Stale expired locks (lock_expires_at <= now) are marked EXPIRED and do not block.
    - Overlapping active locks (CONFIRMED or unexpired PENDING_PAYMENT) raise SlotAlreadyReservedError (409).
    """
    from apps.panoramas.models import TablePin
    from apps.venues.models import DesignAddon

    if now is None:
        now = dj_timezone.now()
    elif dj_timezone.is_naive(now):
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    # 1. Determine slot start/end in aware UTC (ARCH-006)
    local_start = datetime.combine(slot_date, slot_start_time, tzinfo=TEHRAN)
    start_at_utc = local_start.astimezone(timezone.utc)
    end_at_utc = start_at_utc + SLOT_DURATION

    # 2. BR-002: Lead time validation (>= 24 hours from now)
    if start_at_utc - now < LEAD_TIME_THRESHOLD:
        raise LeadTimeViolationError(
            "Bookings must be initiated at least 24 hours before the slot start time."
        )

    pin_id = table_pin if isinstance(table_pin, int) else table_pin.pk

    # 3. Concurrency-critical lock execution
    with transaction.atomic():
        # Lock the TablePin row to serialize concurrent booking attempts on the same table
        pin = TablePin.objects.select_for_update().get(pk=pin_id)

        # REQ-LOCK-005: Expire any stale locks that have elapsed unpaid
        # This frees the DB partial unique constraint and maintains correctness without celery
        Booking.objects.filter(
            table_pin_id=pin.pk,
            slot_date=slot_date,
            slot_start_time=slot_start_time,
            status=BookingStatus.PENDING_PAYMENT,
            lock_expires_at__lte=now,
        ).update(status=BookingStatus.EXPIRED, updated_at=now)

        # REQ-LOCK-003: Check if an active confirmed booking or active lock exists
        if Booking.objects.active_locks_for_slot(pin.pk, slot_date, slot_start_time, now=now).exists():
            raise SlotAlreadyReservedError(
                "This table is currently reserved or locked by another customer for this slot."
            )

        # Determine table reservation fee (read directly from pin, FR-004 / BR-003)
        amount_online_toman = pin.reservation_fee_toman

        # Create Booking row in PENDING_PAYMENT with 10-minute TTL
        booking = Booking.objects.create(
            venue=pin.venue,
            table_pin=pin,
            customer=user,
            status=BookingStatus.PENDING_PAYMENT,
            start_at=start_at_utc,
            end_at=end_at_utc,
            slot_date=slot_date,
            slot_start_time=slot_start_time,
            locked_at=now,
            lock_expires_at=now + LOCK_TTL,
            amount_online_toman=amount_online_toman,
            amount_in_person_toman=0,
        )

        # REQ-LOCK-006: Attach selected design addons with price snapshot (BR-003)
        if addon_ids:
            addons = DesignAddon.objects.filter(id__in=addon_ids, venue=pin.venue, is_active=True)
            total_addon_fee = 0
            booking_addons = []
            for addon in addons:
                booking_addons.append(
                    BookingAddon(
                        booking=booking,
                        design_addon=addon,
                        price_snapshot_toman=addon.fee,
                    )
                )
                total_addon_fee += addon.fee

            if booking_addons:
                BookingAddon.objects.bulk_create(booking_addons)
                booking.amount_in_person_toman = total_addon_fee
                booking.save(update_fields=["amount_in_person_toman", "updated_at"])

        return booking


def initiate_booking(
    *,
    user: Any,
    table_pin_id: int,
    slot_date: Union[date, str],
    slot_start_time: Union[time, str],
    venue_id: Optional[int] = None,
    addon_ids: Iterable[int] = (),
    now: Optional[datetime] = None,
) -> Booking:
    """Initiate a booking lock from an API request (Task T-013).

    Validates:
    - Role: caller must be CUSTOMER (raises PermissionDenied -> 403).
    - TablePin: exists and is_active (raises Http404 or TableNotBookableError -> 400).
    - Venue: if venue_id provided, must match pin.venue_id (VenueMismatchError -> 400).
    - BR-005: venue must be approved and have active subscription (VenueNotBookableError -> 400).
    - Operating hours: slot must be within venue operating hours if configured (InvalidSlotError -> 400).
    - Date / time parsing: converts Gregorian/Jalali strings to canonical date and time.
    - Concurrency & lead time: delegates to atomic create_booking_lock (TD-004).
    """
    from django.core.exceptions import PermissionDenied
    from django.http import Http404

    from apps.accounts.models import UserRole
    from apps.bookings.schemas import resolve_time
    from apps.panoramas.models import TablePin
    from apps.scheduling.services import get_venue_slots_for_date
    from core.exceptions import (
        InvalidSlotError,
        TableNotBookableError,
        VenueMismatchError,
        VenueNotBookableError,
    )
    from core.jalali import resolve_date

    if now is None:
        now = dj_timezone.now()
    elif dj_timezone.is_naive(now):
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    # 1. Role enforcement: CUSTOMER only
    if not user or getattr(user, "role", None) != UserRole.CUSTOMER:
        raise PermissionDenied("Only customers can initiate bookings.")

    # 2. Date and time resolution
    resolved_date = resolve_date(slot_date)
    resolved_time = resolve_time(slot_start_time)

    # 3. TablePin and Venue resolution
    pin = TablePin.objects.select_related("venue").filter(pk=table_pin_id).first()
    if not pin:
        raise Http404("Table pin not found.")

    if not pin.is_active:
        raise TableNotBookableError("This table is currently not available for reservations.")

    if venue_id is not None and pin.venue_id != venue_id:
        raise VenueMismatchError("The specified table does not belong to this venue.")

    venue = pin.venue
    # BR-005: Admin-approved and active subscription (single read path)
    if not venue.is_approved or not venue.has_active_subscription(now=now):
        raise VenueNotBookableError("This venue is not currently accepting reservations.")

    # 4. Validate that requested slot is in operating hours
    if venue.operating_hours.exists():
        slots = get_venue_slots_for_date(venue, on_date=resolved_date, now=now)
        if not any(s.start_time == resolved_time for s in slots):
            raise InvalidSlotError("The requested slot is outside the venue's operating hours.")

    # 5. Acquire atomic booking lock (TD-004)
    return create_booking_lock(
        user=user,
        table_pin=pin,
        slot_date=resolved_date,
        slot_start_time=resolved_time,
        addon_ids=addon_ids,
        now=now,
    )


def cancel_booking(
    booking: int | Booking,
    *,
    actor: Any,
    now: Optional[datetime] = None,
) -> BookingCancelResult:
    """Cancel a reservation booking and refund online platform fee to in-app wallet (BR-004 / UF-003).

    Decision Tree (Task T-023):
    (a) CONFIRMED and start_at - now >= 36h:
        - Transition booking to CANCELLED.
        - Credit customer's in-app wallet with 100% of amount_online_toman (table fee only;
          amount_in_person_toman is never refunded as it was not paid online).
        - Idempotency key: "cancel-refund-{booking_id}".
        - Both status change and wallet credit commit atomically together.
    (b) CONFIRMED but start_at - now < 36h:
        - Raise CancellationWindowClosedError (HTTP 400).
        - Booking remains CONFIRMED, zero wallet credit, zero ledger entries.
    (c) PENDING_PAYMENT:
        - Transition booking to CANCELLED (releases hold early).
        - Zero wallet credit, zero ledger entries (no money was collected).
    (d) Already CANCELLED:
        - Idempotent return: booking remains CANCELLED, refunded_to_wallet_toman = 0.
        - No second credit.
    (e) Any other status (INITIATED, EXPIRED, COMPLETED):
        - Raise BookingNotCancellableError (HTTP 409).
        - Specifically includes EXPIRED bookings carrying refund_required payment (ADR-006: bank card only, never wallet).

    Guarantees:
    - Atomicity: executed inside transaction.atomic() with select_for_update() row lock on the Booking.
    - Closed-loop: refunds are credited to the in-app wallet only; never to bank cards (BR-004).
    - Freed slot is bookable immediately by other customers (is_table_slot_occupied excludes CANCELLED).
    - Authorization: only the customer who created the booking (or staff) may cancel.
    """
    booking_id = booking.pk if hasattr(booking, "pk") else booking

    # Check existence & permissions fast-path
    target = Booking.objects.filter(pk=booking_id).first()
    if not target:
        raise Http404("Booking not found.")

    if target.customer_id != actor.id and not getattr(actor, "is_staff", False):
        raise PermissionDenied("You do not have permission to cancel this booking.")

    with transaction.atomic():
        # Acquire exclusive row lock on the Booking
        locked_booking = (
            Booking.objects.select_for_update()
            .select_related("customer")
            .filter(pk=booking_id)
            .first()
        )
        if not locked_booking:
            raise Http404("Booking not found.")

        # Re-check ownership under row lock
        if locked_booking.customer_id != actor.id and not getattr(actor, "is_staff", False):
            raise PermissionDenied("You do not have permission to cancel this booking.")

        current_time = now or dj_timezone.now()

        # Case (d): Already CANCELLED -> Idempotent replay
        if locked_booking.status == BookingStatus.CANCELLED:
            logger.info("Booking id=%s already cancelled; returning idempotent result", locked_booking.id)
            return BookingCancelResult(
                booking_id=locked_booking.id,
                status=BookingStatus.CANCELLED,
                refunded_to_wallet_toman=0,
                wallet_balance_toman=None,
            )

        # Case (a) & (b): CONFIRMED
        if locked_booking.status == BookingStatus.CONFIRMED:
            time_until_start = locked_booking.start_at - current_time
            if time_until_start < CANCELLATION_WINDOW_THRESHOLD:
                # Case (b): Inside 36h window -> REJECT with DomainError
                logger.warning(
                    "Booking id=%s cancellation rejected: inside 36h window (%s remaining)",
                    locked_booking.id,
                    time_until_start,
                )
                raise CancellationWindowClosedError(
                    "Reservations can only be cancelled at least 36 hours before the slot start time.",
                    details={
                        "booking_id": locked_booking.id,
                        "start_at": locked_booking.start_at.isoformat(),
                        "hours_until_start": round(time_until_start.total_seconds() / 3600.0, 2),
                    },
                )

            # Case (a): Valid cancellation >= 36h ahead -> CANCEL & refund online table fee
            locked_booking.transition_to(BookingStatus.CANCELLED)

            amount_to_refund = locked_booking.amount_online_toman
            wallet_balance = None
            if amount_to_refund > 0:
                from apps.wallets.services import credit_wallet, get_or_create_wallet_for_user

                wallet = get_or_create_wallet_for_user(locked_booking.customer)
                idempotency_key = f"cancel-refund-{locked_booking.id}"
                tx = credit_wallet(
                    wallet=wallet,
                    amount_toman=amount_to_refund,
                    reason=f"Cancellation refund for booking #{locked_booking.id}",
                    idempotency_key=idempotency_key,
                    booking=locked_booking,
                )
                wallet_balance = tx.balance_after_toman

            logger.info(
                "Booking id=%s cancelled successfully. Refunded %s Toman to wallet (new balance=%s)",
                locked_booking.id,
                amount_to_refund,
                wallet_balance,
            )
            return BookingCancelResult(
                booking_id=locked_booking.id,
                status=BookingStatus.CANCELLED,
                refunded_to_wallet_toman=amount_to_refund,
                wallet_balance_toman=wallet_balance,
            )

        # Case (c): PENDING_PAYMENT -> release hold, no refund
        if locked_booking.status == BookingStatus.PENDING_PAYMENT:
            locked_booking.transition_to(BookingStatus.CANCELLED)
            logger.info("Pending hold on booking id=%s cancelled and released early", locked_booking.id)
            return BookingCancelResult(
                booking_id=locked_booking.id,
                status=BookingStatus.CANCELLED,
                refunded_to_wallet_toman=0,
                wallet_balance_toman=None,
            )

        # Case (e): Any other status (INITIATED, EXPIRED, COMPLETED) -> 409
        logger.warning(
            "Booking id=%s cancellation rejected: invalid status '%s'",
            locked_booking.id,
            locked_booking.status,
        )
        raise BookingNotCancellableError(
            f"Booking in status '{locked_booking.status}' cannot be cancelled.",
            details={"booking_id": locked_booking.id, "current_status": locked_booking.status},
        )


def get_split_receipt(
    booking: int | Booking,
    *,
    actor: Any,
) -> SplitReceiptResult:
    """Build a read-only split receipt for one settled booking (Task T-024 / BR-003 / ARCH-005).

    Guarantees:
    - Pure read: creates no payment, no charge, no settlement, and no wallet mutation.
    - Bounded queries (3 constant SQL queries regardless of add-on count):
      1. Booking + Venue + TablePin (select_related)
      2. BookingAddon + DesignAddon (prefetch_related)
      3. Successful PaymentTransaction safe columns only (prefetch_related)
    - Ownership: strictly the booking's own customer (403 otherwise).
    - Availability: CONFIRMED or COMPLETED only (409 RECEIPT_NOT_AVAILABLE otherwise).
    - Consistency: sum of BookingAddon.price_snapshot_toman must match
      booking.amount_in_person_toman (otherwise raises ReceiptDataInconsistencyError).
    - Safe payment exposure: provider_name and card_pan_masked only if a SUCCESS
      PaymentTransaction exists and stores them; never raw payloads, full PAN,
      or provider_reference.
    """
    from apps.billing.models import PaymentStatus, PaymentTransaction

    booking_id = booking.pk if isinstance(booking, Booking) else booking

    booking_obj = (
        Booking.objects.select_related("venue", "table_pin")
        .prefetch_related(
            models.Prefetch(
                "addons",
                queryset=BookingAddon.objects.select_related("design_addon").order_by("id"),
                to_attr="_receipt_addons",
            ),
            models.Prefetch(
                "payment_transactions",
                queryset=PaymentTransaction.objects.filter(status=PaymentStatus.SUCCESS)
                .only("id", "booking_id", "provider_name", "card_pan_masked", "verified_at", "created_at")
                .order_by("-verified_at", "-created_at"),
                to_attr="_successful_payments",
            ),
        )
        .filter(pk=booking_id)
        .first()
    )

    if not booking_obj:
        raise Http404("Booking not found.")

    # Ownership check: strictly the booking's own customer (no venue-owner/admin access in T-024)
    if not actor or booking_obj.customer_id != actor.id:
        raise PermissionDenied("You do not have permission to view this receipt.")

    # Availability rule: only bookings whose online fee was settled
    if booking_obj.status not in RECEIPT_AVAILABLE_STATUSES:
        raise ReceiptNotAvailableError(
            f"Receipt is not available for booking in status '{booking_obj.status}'.",
            details={"booking_id": booking_obj.id, "current_status": booking_obj.status},
        )

    # In-person section from BookingAddon price snapshots
    addon_lines = [
        SplitReceiptAddonLine(
            addon_id=ba.design_addon_id,
            title=ba.design_addon.title,
            unit_fee_toman=ba.price_snapshot_toman,
            line_total_toman=ba.price_snapshot_toman,
        )
        for ba in booking_obj._receipt_addons
    ]
    computed_in_person_toman = sum(line.line_total_toman for line in addon_lines)

    # Consistency rule: computed line sum must match stored amount_in_person_toman
    if computed_in_person_toman != booking_obj.amount_in_person_toman:
        logger.error(
            "Split receipt data inconsistency for booking id=%s: computed=%s stored=%s",
            booking_obj.id,
            computed_in_person_toman,
            booking_obj.amount_in_person_toman,
        )
        raise ReceiptDataInconsistencyError(
            "Booking in-person total does not match the sum of its add-on line snapshots.",
            details={
                "booking_id": booking_obj.id,
                "computed_in_person_toman": computed_in_person_toman,
                "stored_in_person_toman": booking_obj.amount_in_person_toman,
            },
        )

    # Safe payment metadata from SUCCESS PaymentTransaction (if present)
    successful_tx = booking_obj._successful_payments[0] if booking_obj._successful_payments else None
    provider_name = (successful_tx.provider_name or None) if successful_tx else None
    card_pan_masked = (successful_tx.card_pan_masked or None) if successful_tx else None

    total_online_toman = booking_obj.amount_online_toman
    grand_total_toman = total_online_toman + computed_in_person_toman

    return SplitReceiptResult(
        booking_id=booking_obj.id,
        status=booking_obj.status,
        venue_name=booking_obj.venue.name,
        venue_slug=booking_obj.venue.slug,
        table_number=booking_obj.table_pin.table_number,
        start_at=booking_obj.start_at,
        end_at=booking_obj.end_at,
        slot_date=booking_obj.slot_date,
        slot_start_time=booking_obj.slot_start_time,
        jalali_date=booking_obj.jalali_date,
        jalali_start_datetime=booking_obj.jalali_start_datetime,
        jalali_end_datetime=booking_obj.jalali_end_datetime,
        paid_online=SplitReceiptOnlineSection(
            label="Paid online (100% platform share)",
            description=f"Table reservation fee ({booking_obj.table_pin.table_number})",
            amount_online_toman=total_online_toman,
            provider_name=provider_name,
            card_pan_masked=card_pan_masked,
        ),
        payable_in_person=SplitReceiptInPersonSection(
            label="Payable in person at the venue",
            items=addon_lines,
            total_in_person_toman=computed_in_person_toman,
        ),
        total_online_toman=total_online_toman,
        total_in_person_toman=computed_in_person_toman,
        grand_total_toman=grand_total_toman,
    )


