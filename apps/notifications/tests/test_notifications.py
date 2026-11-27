"""Tests for in-app notifications (Task T-039 / FR-36, BR-10, BR-16)."""
from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Any, cast

import pytest
from django.db import transaction
from django.test import Client
from django.utils import timezone

from apps.accounts.models import User, UserRole
from apps.bookings.models import Booking, BookingStatus
from apps.bookings.tests.factories import BookingFactory
from apps.notifications.models import Notification, NotificationType
from apps.notifications.services import create_notification, render_notification_copy
from apps.panoramas.models import TablePin
from apps.panoramas.tests.factories import TablePinFactory
from apps.venues.models import Venue, VenueReviewStatus
from apps.venues.tests.factories import UserFactory, VenueFactory
from apps.wallets.services import credit_wallet, get_or_create_wallet_for_user
from core.testing import authenticate_client

pytestmark = pytest.mark.django_db


def _user(**kwargs: Any) -> User:
    return cast(User, UserFactory(**kwargs))


def _venue(**kwargs: Any) -> Venue:
    return cast(Venue, VenueFactory(**kwargs))


def _pin(**kwargs: Any) -> TablePin:
    return cast(TablePin, TablePinFactory(**kwargs))


def _booking(**kwargs: Any) -> Booking:
    return cast(Booking, BookingFactory(**kwargs))


def _fund_wallet(user: User, amount_toman: int) -> None:
    wallet = get_or_create_wallet_for_user(user)
    credit_wallet(
        wallet,
        amount_toman,
        reason="test-seed",
        idempotency_key=f"seed-{uuid.uuid4().hex}",
    )


def _pending_booking(
    *,
    customer: User,
    owner: User | None = None,
    venue: Venue | None = None,
    amount_online_toman: int = 50_000,
    hours_ahead: int = 48,
    status: str = BookingStatus.PENDING_PAYMENT,
) -> Booking:
    now = timezone.now()
    target_venue = venue or _venue(owner=owner or _user(role=UserRole.VENUE_OWNER))
    pin = _pin(venue=target_venue, reservation_fee_toman=amount_online_toman)
    start_at = now + timedelta(hours=hours_ahead)
    return _booking(
        customer=customer,
        venue=target_venue,
        table_pin=pin,
        status=status,
        start_at=start_at,
        end_at=start_at + timedelta(minutes=90),
        slot_date=start_at.date(),
        slot_start_time=start_at.time(),
        amount_online_toman=amount_online_toman,
        amount_in_person_toman=0,
        locked_at=now,
        lock_expires_at=now + timedelta(minutes=10),
    )


def _post_json(client: Client, path: str, payload: dict[str, Any] | None = None) -> Any:
    if payload is None:
        return client.post(path)
    return client.post(path, data=json.dumps(payload), content_type="application/json")


def test_booking_confirm_creates_notification_for_owner() -> None:
    """1. Wallet-pay confirmation creates an unread BOOKING_CONFIRMED row for the venue owner."""
    owner = _user(role=UserRole.VENUE_OWNER)
    customer = _user(role=UserRole.CUSTOMER)
    _fund_wallet(customer, 100_000)
    booking = _pending_booking(customer=customer, owner=owner, amount_online_toman=50_000)

    client = authenticate_client(Client(), customer)
    resp = _post_json(
        client,
        "/api/v1/billing/wallet-pay/",
        {"booking_id": booking.id, "idempotency_key": f"wpay-{uuid.uuid4().hex}"},
    )
    assert resp.status_code == 200

    notifs = Notification.objects.filter(recipient=owner, type=NotificationType.BOOKING_CONFIRMED)
    assert notifs.count() == 1
    notif = notifs.get()
    assert notif.is_read is False
    assert notif.booking_id == booking.id
    assert notif.venue_id is None


def test_booking_cancel_creates_notification_for_owner() -> None:
    """2. Customer cancellation creates an unread BOOKING_CANCELLED row for the venue owner."""
    owner = _user(role=UserRole.VENUE_OWNER)
    customer = _user(role=UserRole.CUSTOMER)
    booking = _pending_booking(
        customer=customer,
        owner=owner,
        hours_ahead=48,
        status=BookingStatus.CONFIRMED,
    )

    client = authenticate_client(Client(), customer)
    resp = _post_json(client, f"/api/v1/bookings/{booking.id}/cancel/")
    assert resp.status_code == 200

    notifs = Notification.objects.filter(recipient=owner, type=NotificationType.BOOKING_CANCELLED)
    assert notifs.count() == 1
    notif = notifs.get()
    assert notif.is_read is False
    assert notif.booking_id == booking.id


def test_customer_receives_no_notification_on_confirm_or_cancel() -> None:
    """3. The customer gets zero Notification rows on booking confirm and cancel."""
    owner = _user(role=UserRole.VENUE_OWNER)
    customer = _user(role=UserRole.CUSTOMER)
    _fund_wallet(customer, 100_000)
    booking = _pending_booking(customer=customer, owner=owner, hours_ahead=48)

    client = authenticate_client(Client(), customer)
    confirm_resp = _post_json(
        client,
        "/api/v1/billing/wallet-pay/",
        {"booking_id": booking.id, "idempotency_key": f"wpay-{uuid.uuid4().hex}"},
    )
    assert confirm_resp.status_code == 200
    assert Notification.objects.filter(recipient=customer).count() == 0

    cancel_resp = _post_json(client, f"/api/v1/bookings/{booking.id}/cancel/")
    assert cancel_resp.status_code == 200
    assert Notification.objects.filter(recipient=customer).count() == 0


def test_notification_created_synchronously_on_confirm_and_cancel() -> None:
    """4. Notification rows exist immediately after confirm/cancel API calls return."""
    owner = _user(role=UserRole.VENUE_OWNER)
    customer = _user(role=UserRole.CUSTOMER)
    _fund_wallet(customer, 100_000)
    booking = _pending_booking(customer=customer, owner=owner, hours_ahead=48)

    client = authenticate_client(Client(), customer)
    confirm_resp = _post_json(
        client,
        "/api/v1/billing/wallet-pay/",
        {"booking_id": booking.id, "idempotency_key": f"wpay-{uuid.uuid4().hex}"},
    )
    assert confirm_resp.status_code == 200
    assert Notification.objects.filter(
        recipient=owner,
        type=NotificationType.BOOKING_CONFIRMED,
        booking_id=booking.id,
    ).exists()

    cancel_resp = _post_json(client, f"/api/v1/bookings/{booking.id}/cancel/")
    assert cancel_resp.status_code == 200
    assert Notification.objects.filter(
        recipient=owner,
        type=NotificationType.BOOKING_CANCELLED,
        booking_id=booking.id,
    ).exists()


def test_venue_approve_creates_notification_for_owner() -> None:
    """5. Admin venue approve creates a VENUE_APPROVED row with venue_id set and booking_id null."""
    admin = _user(role=UserRole.ADMIN, is_staff=True)
    owner = _user(role=UserRole.VENUE_OWNER)
    venue = _venue(owner=owner, review_status=VenueReviewStatus.PENDING_REVIEW, is_approved=False)

    client = authenticate_client(Client(), admin)
    resp = _post_json(client, f"/api/v1/venues/admin/venues/{venue.id}/approve")
    assert resp.status_code == 200

    notifs = Notification.objects.filter(recipient=owner, type=NotificationType.VENUE_APPROVED)
    assert notifs.count() == 1
    notif = notifs.get()
    assert notif.venue_id == venue.id
    assert notif.booking_id is None
    assert notif.is_read is False


def test_venue_reject_creates_notification_with_reason_in_body() -> None:
    """6. Admin venue reject creates a VENUE_REJECTED row with the rejection reason in body."""
    admin = _user(role=UserRole.ADMIN, is_staff=True)
    owner = _user(role=UserRole.VENUE_OWNER)
    venue = _venue(owner=owner, review_status=VenueReviewStatus.PENDING_REVIEW, is_approved=False)
    reason = "تصاویر پانوراما کیفیت کافی ندارند"

    admin_client = authenticate_client(Client(), admin)
    resp = _post_json(admin_client, f"/api/v1/venues/admin/venues/{venue.id}/reject", {"reason": reason})
    assert resp.status_code == 200

    notifs = Notification.objects.filter(recipient=owner, type=NotificationType.VENUE_REJECTED)
    assert notifs.count() == 1
    notif = notifs.get()
    assert notif.venue_id == venue.id
    assert notif.booking_id is None

    owner_client = authenticate_client(Client(), owner)
    list_resp = owner_client.get("/api/v1/notifications/")
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) == 1
    assert reason in items[0]["body"]


def test_list_notifications_scoped_to_requesting_user() -> None:
    """7. List returns only the requesting user's own rows (BR-16)."""
    owner_a = _user(role=UserRole.VENUE_OWNER)
    owner_b = _user(role=UserRole.VENUE_OWNER)
    customer = _user(role=UserRole.CUSTOMER)
    venue_a = _venue(owner=owner_a)
    venue_b = _venue(owner=owner_b)

    notif_a = Notification.objects.create(recipient=owner_a, type=NotificationType.VENUE_APPROVED, venue=venue_a)
    notif_b = Notification.objects.create(recipient=owner_b, type=NotificationType.VENUE_APPROVED, venue=venue_b)

    customer_resp = authenticate_client(Client(), customer).get("/api/v1/notifications/")
    assert customer_resp.status_code == 200
    assert customer_resp.json() == []

    owner_b_resp = authenticate_client(Client(), owner_b).get("/api/v1/notifications/")
    assert owner_b_resp.status_code == 200
    assert [item["id"] for item in owner_b_resp.json()] == [notif_b.id]

    owner_a_resp = authenticate_client(Client(), owner_a).get("/api/v1/notifications/")
    assert owner_a_resp.status_code == 200
    assert [item["id"] for item in owner_a_resp.json()] == [notif_a.id]


def test_list_notifications_ordering_and_pagination_clamping() -> None:
    """8. List is newest first; default limit is 50 and limit=150 clamps to 100."""
    owner = _user(role=UserRole.VENUE_OWNER)
    venue = _venue(owner=owner)
    base_time = timezone.now() - timedelta(hours=5)

    created_ids: list[int] = []
    for idx in range(110):
        notif = Notification.objects.create(recipient=owner, type=NotificationType.VENUE_APPROVED, venue=venue)
        Notification.objects.filter(pk=notif.pk).update(created_at=base_time + timedelta(seconds=idx))
        created_ids.append(notif.id)

    client = authenticate_client(Client(), owner)
    default_resp = client.get("/api/v1/notifications/")
    assert default_resp.status_code == 200
    default_items = default_resp.json()
    assert len(default_items) == 50
    assert [item["id"] for item in default_items] == list(reversed(created_ids))[:50]

    clamped_resp = client.get("/api/v1/notifications/?limit=150")
    assert clamped_resp.status_code == 200
    clamped_items = clamped_resp.json()
    assert len(clamped_items) == 100
    assert [item["id"] for item in clamped_items] == list(reversed(created_ids))[:100]


def test_unread_count_scoped_and_resets_after_read_all() -> None:
    """9. Unread count counts only the requesting user's unread rows and resets to 0 after read-all."""
    owner_a = _user(role=UserRole.VENUE_OWNER)
    owner_b = _user(role=UserRole.VENUE_OWNER)

    for _ in range(3):
        Notification.objects.create(recipient=owner_a, type=NotificationType.VENUE_APPROVED, is_read=False)
    Notification.objects.create(recipient=owner_a, type=NotificationType.VENUE_APPROVED, is_read=True)
    for _ in range(2):
        Notification.objects.create(recipient=owner_b, type=NotificationType.VENUE_APPROVED, is_read=False)

    client_a = authenticate_client(Client(), owner_a)
    count_resp = client_a.get("/api/v1/notifications/unread-count")
    assert count_resp.status_code == 200
    assert count_resp.json() == {"unread_count": 3}

    read_all_resp = _post_json(client_a, "/api/v1/notifications/read-all")
    assert read_all_resp.status_code == 200

    after_resp = client_a.get("/api/v1/notifications/unread-count")
    assert after_resp.status_code == 200
    assert after_resp.json() == {"unread_count": 0}

    client_b = authenticate_client(Client(), owner_b)
    b_count_resp = client_b.get("/api/v1/notifications/unread-count")
    assert b_count_resp.status_code == 200
    assert b_count_resp.json() == {"unread_count": 2}


def test_mark_single_notification_as_read_and_idempotent() -> None:
    """10. Marking a notification as read returns 200 with is_read=True; repeating is a 200 no-op."""
    owner = _user(role=UserRole.VENUE_OWNER)
    notif = Notification.objects.create(recipient=owner, type=NotificationType.VENUE_APPROVED, is_read=False)

    client = authenticate_client(Client(), owner)
    first_resp = _post_json(client, f"/api/v1/notifications/{notif.id}/read")
    assert first_resp.status_code == 200
    assert first_resp.json()["is_read"] is True

    notif.refresh_from_db()
    assert notif.is_read is True

    second_resp = _post_json(client, f"/api/v1/notifications/{notif.id}/read")
    assert second_resp.status_code == 200
    assert second_resp.json()["is_read"] is True


def test_mark_another_users_notification_as_read_returns_403() -> None:
    """11. Marking another user's notification as read returns 403 and leaves it unread."""
    owner_a = _user(role=UserRole.VENUE_OWNER)
    owner_b = _user(role=UserRole.VENUE_OWNER)
    notif = Notification.objects.create(recipient=owner_a, type=NotificationType.VENUE_APPROVED, is_read=False)

    client_b = authenticate_client(Client(), owner_b)
    resp = _post_json(client_b, f"/api/v1/notifications/{notif.id}/read")
    assert resp.status_code == 403

    notif.refresh_from_db()
    assert notif.is_read is False


def test_mark_all_as_read_scoped_and_returns_marked_count() -> None:
    """12. read-all marks only the requesting user's unread rows and returns the marked count."""
    owner_a = _user(role=UserRole.VENUE_OWNER)
    owner_b = _user(role=UserRole.VENUE_OWNER)

    for _ in range(3):
        Notification.objects.create(recipient=owner_a, type=NotificationType.VENUE_APPROVED, is_read=False)
    Notification.objects.create(recipient=owner_a, type=NotificationType.VENUE_APPROVED, is_read=True)
    for _ in range(2):
        Notification.objects.create(recipient=owner_b, type=NotificationType.VENUE_APPROVED, is_read=False)

    client_a = authenticate_client(Client(), owner_a)
    resp = _post_json(client_a, "/api/v1/notifications/read-all")
    assert resp.status_code == 200
    assert resp.json() == {"marked": 3}

    assert Notification.objects.filter(recipient=owner_a, is_read=False).count() == 0
    assert Notification.objects.filter(recipient=owner_b, is_read=False).count() == 2


def test_unauthenticated_endpoints_return_401() -> None:
    """13. Unauthenticated list, unread-count, read, and read-all all return 401."""
    client = Client()
    assert client.get("/api/v1/notifications/").status_code == 401
    assert client.get("/api/v1/notifications/unread-count").status_code == 401
    assert _post_json(client, "/api/v1/notifications/1/read").status_code == 401
    assert _post_json(client, "/api/v1/notifications/read-all").status_code == 401


def test_privacy_no_phone_or_email_in_serialized_responses() -> None:
    """14. Serialized list/read responses never contain phone numbers or emails, while naming venue/table/slot."""
    owner_phone = "09198765432"
    customer_phone = "09123456789"

    owner = _user(role=UserRole.VENUE_OWNER, phone=owner_phone)
    customer = _user(
        role=UserRole.CUSTOMER,
        phone=customer_phone,
    )
    venue = _venue(owner=owner, name="کافه روف‌تاپ")
    pin = _pin(venue=venue, table_number="VIP-7", reservation_fee_toman=50_000)
    start_at = timezone.now() + timedelta(hours=48)
    booking = _booking(
        customer=customer,
        venue=venue,
        table_pin=pin,
        status=BookingStatus.CONFIRMED,
        start_at=start_at,
        end_at=start_at + timedelta(minutes=90),
        slot_date=start_at.date(),
        slot_start_time=start_at.time(),
        amount_online_toman=50_000,
    )
    Notification.objects.create(
        recipient=owner,
        type=NotificationType.BOOKING_CONFIRMED,
        booking=booking,
    )

    client = authenticate_client(Client(), owner)
    list_resp = client.get("/api/v1/notifications/")
    assert list_resp.status_code == 200

    payload_obj = list_resp.json()[0]
    raw_text = list_resp.content.decode("utf-8")
    serialized = json.dumps(payload_obj, ensure_ascii=False)
    for forbidden in (
        owner_phone,
        customer_phone,
        "@",
    ):
        assert forbidden not in serialized
        assert forbidden not in raw_text
    for key in payload_obj:
        assert "phone" not in key.lower()
        assert "email" not in key.lower()
    assert "کافه روف‌تاپ" in payload_obj["body"]
    assert "VIP-7" in payload_obj["body"]


def test_delete_notification_endpoint_does_not_exist() -> None:
    """15. DELETE /api/v1/notifications/{notification_id}/ returns 404 (no delete route)."""
    owner = _user(role=UserRole.VENUE_OWNER)
    notif = Notification.objects.create(recipient=owner, type=NotificationType.VENUE_APPROVED)

    client = authenticate_client(Client(), owner)
    resp = client.delete(f"/api/v1/notifications/{notif.id}/")
    assert resp.status_code == 404


def test_failed_state_change_creates_no_notification() -> None:
    """16. A failed booking confirmation creates zero Notification rows."""
    owner = _user(role=UserRole.VENUE_OWNER)
    customer = _user(role=UserRole.CUSTOMER)
    _fund_wallet(customer, 100_000)
    booking = _pending_booking(
        customer=customer,
        owner=owner,
        status=BookingStatus.CANCELLED,
    )

    client = authenticate_client(Client(), customer)
    resp = _post_json(
        client,
        "/api/v1/billing/wallet-pay/",
        {"booking_id": booking.id, "idempotency_key": f"wpay-{uuid.uuid4().hex}"},
    )
    assert resp.status_code in (400, 409)
    assert Notification.objects.count() == 0


def test_mark_nonexistent_notification_as_read_returns_404() -> None:
    """17. Marking a non-existent notification as read returns 404."""
    owner = _user(role=UserRole.VENUE_OWNER)
    client = authenticate_client(Client(), owner)
    resp = _post_json(client, "/api/v1/notifications/999999/read")
    assert resp.status_code == 404


def test_set_null_fallback_rendering_and_atomic_rollback() -> None:
    """18. Fallback copy renders safely when FK is null, and atomic rollback deletes created rows."""
    owner = _user(role=UserRole.VENUE_OWNER)
    blank_reason_venue = _venue(owner=owner, name="کافه بی‌دلیل", rejection_reason="")

    for notif_type in (
        NotificationType.BOOKING_CONFIRMED,
        NotificationType.BOOKING_CANCELLED,
        NotificationType.VENUE_APPROVED,
        NotificationType.VENUE_REJECTED,
    ):
        notif = Notification.objects.create(recipient=owner, type=notif_type)
        title, body = render_notification_copy(notif)
        assert title
        assert body

    rejected_blank = Notification.objects.create(
        recipient=owner,
        type=NotificationType.VENUE_REJECTED,
        venue=blank_reason_venue,
    )
    _, rejected_body = render_notification_copy(rejected_blank)
    assert "کافه بی‌دلیل" in rejected_body

    unknown_notif = Notification.objects.create(recipient=owner, type="UNKNOWN_TYPE")
    unknown_title, unknown_body = render_notification_copy(unknown_notif)
    assert unknown_title
    assert unknown_body

    count_before = Notification.objects.count()
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            create_notification(
                recipient=owner,
                type=NotificationType.VENUE_APPROVED,
                venue=blank_reason_venue,
            )
            raise RuntimeError("force rollback")
    assert Notification.objects.count() == count_before


def test_handle_payment_callback_creates_booking_confirmed_notification() -> None:
    """Gateway callback confirmation creates BOOKING_CONFIRMED notification for venue owner."""
    from apps.billing.services.gateway import reset_sandbox_gateway
    from apps.billing.services.payment import handle_payment_callback, initiate_payment_for_booking

    reset_sandbox_gateway()
    owner = _user(role=UserRole.VENUE_OWNER)
    customer = _user(role=UserRole.CUSTOMER)
    booking = _pending_booking(customer=customer, owner=owner, amount_online_toman=50_000)

    tx, _ = initiate_payment_for_booking(
        user=customer,
        booking_id=booking.id,
        idempotency_key=f"cb-init-{uuid.uuid4().hex}",
        callback_url="http://127.0.0.1:3000/cb",
    )
    handle_payment_callback(
        callback_params={"authority": tx.provider_reference, "status": "OK"}
    )

    assert (
        Notification.objects.filter(
            recipient=owner,
            type=NotificationType.BOOKING_CONFIRMED,
            booking=booking,
        ).count()
        == 1
    )


def test_idempotent_cancel_booking_replay_creates_no_duplicate_notification() -> None:
    """Calling cancel_booking twice on the same booking creates only one BOOKING_CANCELLED notification."""
    from apps.bookings.services import cancel_booking

    owner = _user(role=UserRole.VENUE_OWNER)
    customer = _user(role=UserRole.CUSTOMER)
    booking = _pending_booking(
        customer=customer,
        owner=owner,
        hours_ahead=48,
        status=BookingStatus.CONFIRMED,
    )

    cancel_booking(booking.id, actor=customer)
    cancel_booking(booking.id, actor=customer)

    assert (
        Notification.objects.filter(
            recipient=owner,
            type=NotificationType.BOOKING_CANCELLED,
            booking=booking,
        ).count()
        == 1
    )


def test_admin_user_list_returns_zero_notifications() -> None:
    """ADMIN user gets an empty list even when booking/venue notifications exist."""
    admin = _user(role=UserRole.ADMIN)
    owner = _user(role=UserRole.VENUE_OWNER)
    venue = _venue(owner=owner, review_status=VenueReviewStatus.APPROVED)
    create_notification(
        recipient=owner,
        type=NotificationType.VENUE_APPROVED,
        venue=venue,
    )

    client = authenticate_client(Client(), admin)
    resp = client.get("/api/v1/notifications/")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_notifications_negative_offset_clamps_to_zero() -> None:
    """Negative offset clamps to 0 and returns the same first page as offset=0."""
    owner = _user(role=UserRole.VENUE_OWNER)
    venue = _venue(owner=owner)
    create_notification(recipient=owner, type=NotificationType.VENUE_APPROVED, venue=venue)
    create_notification(recipient=owner, type=NotificationType.VENUE_REJECTED, venue=venue)

    client = authenticate_client(Client(), owner)
    resp_neg = client.get("/api/v1/notifications/?offset=-10")
    resp_zero = client.get("/api/v1/notifications/?offset=0")
    assert resp_neg.status_code == 200
    assert resp_zero.status_code == 200
    assert resp_neg.json() == resp_zero.json()


def test_confirm_and_cancel_never_call_sms_sender(monkeypatch: pytest.MonkeyPatch) -> None:
    """Booking confirm and cancel must not invoke the SMS sender."""
    from apps.billing.services.payment import pay_booking_with_wallet
    from apps.bookings.services import cancel_booking

    sent_messages: list[tuple[str, str]] = []

    class FakeSmsSender:
        def send_otp(self, phone: str, code: str) -> None:
            sent_messages.append((phone, code))

    monkeypatch.setattr("apps.accounts.sms.get_sms_sender", lambda: FakeSmsSender())

    owner = _user(role=UserRole.VENUE_OWNER)
    customer = _user(role=UserRole.CUSTOMER)
    _fund_wallet(customer, 100_000)
    booking = _pending_booking(customer=customer, owner=owner, hours_ahead=48, amount_online_toman=50_000)

    pay_booking_with_wallet(
        user=customer,
        booking_id=booking.id,
        idempotency_key=f"sms-pay-{uuid.uuid4().hex}",
    )
    cancel_booking(booking.id, actor=customer)

    assert len(sent_messages) == 0


def test_deleted_booking_set_null_renders_cancelled_fallback_copy() -> None:
    """Deleting a booking sets notification.booking=NULL and renders cancelled fallback copy."""
    owner = _user(role=UserRole.VENUE_OWNER)
    customer = _user(role=UserRole.CUSTOMER)
    booking = _pending_booking(
        customer=customer,
        owner=owner,
        hours_ahead=48,
        status=BookingStatus.CANCELLED,
    )
    notif = create_notification(
        recipient=owner,
        type=NotificationType.BOOKING_CANCELLED,
        booking=booking,
    )

    client = authenticate_client(Client(), owner)
    live_resp = client.get("/api/v1/notifications/")
    assert live_resp.status_code == 200
    live_rows = live_resp.json()
    assert len(live_rows) == 1
    assert live_rows[0]["title"] == "رزرو لغو شد"
    assert booking.venue.name in live_rows[0]["body"]
    assert "لغو شد." in live_rows[0]["body"]

    booking.delete()
    notif.refresh_from_db()
    assert notif.booking_id is None

    fallback_resp = client.get("/api/v1/notifications/")
    assert fallback_resp.status_code == 200
    fallback_rows = fallback_resp.json()
    assert len(fallback_rows) == 1
    assert fallback_rows[0]["booking_id"] is None
    assert (fallback_rows[0]["title"], fallback_rows[0]["body"]) == (
        "رزرو لغو شد",
        "یک رزرو لغو شد.",
    )
