"""Tests for payment gateway adapter, PaymentTransaction schema, and domain services.

Task T-020 (PH-05 / WS-BILLING-WALLET / ARCH-005):
- Model constraints (amount non-negative, unique provider_reference, unique idempotency_key).
- State machine transition rules and terminal states.
- Sandbox adapter contract (success, failure, timeout, amount mismatch, idempotency).
- Domain services: initiate_payment_for_booking and verify_payment_transaction.
"""
from datetime import timedelta
import uuid
import pytest

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.billing.models import PaymentStatus, PaymentTransaction, VALID_PAYMENT_TRANSITIONS
from apps.billing.services.gateway import (
    PaymentInitiateRequest,
    PaymentVerifyRequest,
    SandboxGatewayAdapter,
    get_gateway,
    reset_sandbox_gateway,
)
from apps.billing.services.payment import (
    initiate_payment_for_booking,
    verify_payment_transaction,
)
from apps.billing.tests.factories import PaymentTransactionFactory
from apps.bookings.models import BookingStatus
from apps.bookings.tests.factories import BookingFactory
from apps.venues.tests.factories import UserFactory
from core.exceptions import (
    InvalidStatusTransitionError,
    PaymentAlreadyProcessedError,
    PaymentAmountMismatchError,
    PaymentGatewayError,
    PaymentGatewayTimeoutError,
    PaymentVerificationFailedError,
)


@pytest.fixture(autouse=True)
def clean_sandbox_gateway():
    """Ensure sandbox gateway is in a clean default state for each test."""
    reset_sandbox_gateway()
    yield
    reset_sandbox_gateway()


# ---------------------------------------------------------------------------
# 1. Model Constraints and Invariants
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPaymentTransactionModelConstraints:
    def test_amount_non_negative_constraint(self):
        """DB CheckConstraint rejects negative amount_toman."""
        booking = BookingFactory(status=BookingStatus.PENDING_PAYMENT, amount_online_toman=50_000)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PaymentTransaction.objects.create(
                    booking=booking,
                    customer=booking.customer,
                    amount_toman=-1000,
                    idempotency_key=str(uuid.uuid4()),
                )

    def test_duplicate_idempotency_key_rejected(self):
        """Unique constraint on idempotency_key prevents duplicate entries."""
        booking = BookingFactory(status=BookingStatus.PENDING_PAYMENT, amount_online_toman=50_000)
        shared_key = f"key-{uuid.uuid4()}"
        PaymentTransaction.objects.create(
            booking=booking,
            customer=booking.customer,
            amount_toman=50_000,
            idempotency_key=shared_key,
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PaymentTransaction.objects.create(
                    booking=booking,
                    customer=booking.customer,
                    amount_toman=50_000,
                    idempotency_key=shared_key,
                )

    def test_duplicate_non_null_provider_reference_rejected(self):
        """Partial unique constraint rejects duplicate non-null provider_reference."""
        booking = BookingFactory(status=BookingStatus.PENDING_PAYMENT, amount_online_toman=50_000)
        ref = f"SBX-{uuid.uuid4().hex[:12].upper()}"
        PaymentTransaction.objects.create(
            booking=booking,
            customer=booking.customer,
            amount_toman=50_000,
            provider_reference=ref,
            idempotency_key=str(uuid.uuid4()),
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PaymentTransaction.objects.create(
                    booking=booking,
                    customer=booking.customer,
                    amount_toman=50_000,
                    provider_reference=ref,
                    idempotency_key=str(uuid.uuid4()),
                )

    def test_multiple_null_provider_references_allowed(self):
        """Partial unique constraint allows multiple rows with null provider_reference (e.g. INITIATED)."""
        booking = BookingFactory(status=BookingStatus.PENDING_PAYMENT, amount_online_toman=50_000)
        tx1 = PaymentTransaction.objects.create(
            booking=booking,
            customer=booking.customer,
            amount_toman=50_000,
            provider_reference=None,
            idempotency_key=str(uuid.uuid4()),
        )
        tx2 = PaymentTransaction.objects.create(
            booking=booking,
            customer=booking.customer,
            amount_toman=50_000,
            provider_reference=None,
            idempotency_key=str(uuid.uuid4()),
        )
        assert tx1.pk != tx2.pk
        assert tx1.provider_reference is None
        assert tx2.provider_reference is None

    def test_payment_transaction_str_representation(self):
        tx = PaymentTransactionFactory(amount_toman=75_000, status=PaymentStatus.PENDING)
        s = str(tx)
        assert "75000 TOMAN" in s
        assert "PENDING" in s


# ---------------------------------------------------------------------------
# 2. State Machine Transitions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPaymentTransactionStateMachine:
    def test_valid_transitions(self):
        """All documented transitions succeed and persist."""
        for current_state, next_states in VALID_PAYMENT_TRANSITIONS.items():
            for target_state in next_states:
                tx = PaymentTransactionFactory(status=current_state)
                tx.transition_to(target_state)
                tx.refresh_from_db()
                assert tx.status == target_state

    def test_illegal_transitions_raise_error(self):
        """Illegal transitions raise InvalidStatusTransitionError."""
        # INITIATED cannot go directly to SUCCESS (must pass through PENDING or TIMEOUT)
        tx = PaymentTransactionFactory(status=PaymentStatus.INITIATED)
        with pytest.raises(InvalidStatusTransitionError):
            tx.transition_to(PaymentStatus.SUCCESS)

        # SUCCESS is terminal
        tx_success = PaymentTransactionFactory(status=PaymentStatus.SUCCESS)
        for invalid_target in [PaymentStatus.INITIATED, PaymentStatus.PENDING, PaymentStatus.FAILED, PaymentStatus.TIMEOUT]:
            with pytest.raises(InvalidStatusTransitionError):
                tx_success.transition_to(invalid_target)

        # FAILED is terminal
        tx_failed = PaymentTransactionFactory(status=PaymentStatus.FAILED)
        for invalid_target in [PaymentStatus.INITIATED, PaymentStatus.PENDING, PaymentStatus.SUCCESS, PaymentStatus.TIMEOUT]:
            with pytest.raises(InvalidStatusTransitionError):
                tx_failed.transition_to(invalid_target)


# ---------------------------------------------------------------------------
# 3. Sandbox Gateway Adapter Contract
# ---------------------------------------------------------------------------


class TestSandboxGatewayAdapter:
    def test_initiate_success_path(self):
        adapter = SandboxGatewayAdapter(mode="success")
        req = PaymentInitiateRequest(
            amount_toman=100_000,
            callback_url="http://127.0.0.1:8000/api/v1/billing/callback/",
            description="Test payment",
            order_id="123",
        )
        result = adapter.initiate(req)
        assert result.success is True
        assert result.authority.startswith("SBX-")
        assert result.redirect_url.startswith("https://sandbox.mizban.local/pg/startpay/")
        assert result.raw_status == "100"

    def test_initiate_failure_mode(self):
        adapter = SandboxGatewayAdapter(mode="failure")
        req = PaymentInitiateRequest(
            amount_toman=100_000,
            callback_url="http://127.0.0.1:8000/api/v1/billing/callback/",
            description="Test payment",
            order_id="123",
        )
        result = adapter.initiate(req)
        assert result.success is False
        assert result.authority == ""
        assert "failure" in result.error_message.lower()

    def test_initiate_timeout_mode(self):
        adapter = SandboxGatewayAdapter(mode="timeout")
        req = PaymentInitiateRequest(
            amount_toman=100_000,
            callback_url="http://127.0.0.1:8000/api/v1/billing/callback/",
            description="Test payment",
            order_id="123",
        )
        with pytest.raises(PaymentGatewayTimeoutError) as exc:
            adapter.initiate(req)
        assert "timed out" in str(exc.value)

    def test_verify_success_path(self):
        adapter = SandboxGatewayAdapter(mode="success")
        init_res = adapter.initiate(
            PaymentInitiateRequest(
                amount_toman=75_000,
                callback_url="http://127.0.0.1:8000/cb",
                description="Test",
                order_id="1",
            )
        )
        verify_res = adapter.verify(
            PaymentVerifyRequest(authority=init_res.authority, amount_toman=75_000)
        )
        assert verify_res.success is True
        assert verify_res.status == "SUCCESS"
        assert verify_res.tracking_code.startswith("TRK-")
        assert verify_res.card_pan_masked == "603799******1234"
        assert verify_res.amount_toman == 75_000

    def test_verify_idempotent_duplicate_call(self):
        adapter = SandboxGatewayAdapter(mode="success")
        init_res = adapter.initiate(
            PaymentInitiateRequest(
                amount_toman=75_000,
                callback_url="http://127.0.0.1:8000/cb",
                description="Test",
                order_id="1",
            )
        )
        # First verify
        res1 = adapter.verify(PaymentVerifyRequest(authority=init_res.authority, amount_toman=75_000))
        assert res1.status == "SUCCESS"

        # Duplicate verify returns ALREADY_VERIFIED with same tracking code
        res2 = adapter.verify(PaymentVerifyRequest(authority=init_res.authority, amount_toman=75_000))
        assert res2.success is True
        assert res2.status == "ALREADY_VERIFIED"
        assert res2.tracking_code == res1.tracking_code

    def test_verify_amount_mismatch_detected(self):
        adapter = SandboxGatewayAdapter(mode="success")
        init_res = adapter.initiate(
            PaymentInitiateRequest(
                amount_toman=75_000,
                callback_url="http://127.0.0.1:8000/cb",
                description="Test",
                order_id="1",
            )
        )
        verify_res = adapter.verify(
            PaymentVerifyRequest(authority=init_res.authority, amount_toman=80_000)
        )
        assert verify_res.success is False
        assert verify_res.status == "FAILED"
        assert "Amount mismatch" in verify_res.error_message

    def test_verify_failure_mode(self):
        adapter = SandboxGatewayAdapter(mode="failure")
        verify_res = adapter.verify(
            PaymentVerifyRequest(authority="SBX-SAMPLE", amount_toman=50_000)
        )
        assert verify_res.success is False
        assert verify_res.status == "FAILED"

    def test_verify_timeout_mode(self):
        adapter = SandboxGatewayAdapter(mode="timeout")
        with pytest.raises(PaymentGatewayTimeoutError):
            adapter.verify(PaymentVerifyRequest(authority="SBX-SAMPLE", amount_toman=50_000))

    def test_get_status(self):
        adapter = SandboxGatewayAdapter(mode="success")
        init_res = adapter.initiate(
            PaymentInitiateRequest(
                amount_toman=50_000,
                callback_url="http://cb",
                description="test",
                order_id="1",
            )
        )
        st1 = adapter.get_status(init_res.authority)
        assert st1.status == "PENDING"
        adapter.verify(PaymentVerifyRequest(authority=init_res.authority, amount_toman=50_000))
        st2 = adapter.get_status(init_res.authority)
        assert st2.status == "SUCCESS"


# ---------------------------------------------------------------------------
# 4. Domain Services: initiate_payment_for_booking
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestInitiatePaymentService:
    def test_initiate_payment_success_lifecycle(self):
        now = timezone.now()
        customer = UserFactory(role="CUSTOMER")
        booking = BookingFactory(
            customer=customer,
            status=BookingStatus.PENDING_PAYMENT,
            amount_online_toman=60_000,
            amount_in_person_toman=40_000,
            locked_at=now,
            lock_expires_at=now + timedelta(minutes=10),
        )
        key = f"key-{uuid.uuid4()}"
        tx, redirect_url = initiate_payment_for_booking(
            user=customer,
            booking_id=booking.id,
            idempotency_key=key,
            callback_url="http://127.0.0.1:8000/cb",
        )
        assert tx.status == PaymentStatus.PENDING
        assert tx.provider_name == "sandbox"
        assert tx.amount_toman == 60_000  # Table fee only (BR-003)
        assert tx.currency == "TOMAN"
        assert tx.provider_reference.startswith("SBX-")
        assert redirect_url == tx.redirect_url
        assert redirect_url.startswith("https://sandbox.mizban.local/pg/startpay/")

    def test_initiate_payment_idempotency_returns_existing(self):
        now = timezone.now()
        customer = UserFactory(role="CUSTOMER")
        booking = BookingFactory(
            customer=customer,
            status=BookingStatus.PENDING_PAYMENT,
            amount_online_toman=60_000,
            locked_at=now,
            lock_expires_at=now + timedelta(minutes=10),
        )
        key = f"key-{uuid.uuid4()}"
        tx1, url1 = initiate_payment_for_booking(
            user=customer,
            booking_id=booking.id,
            idempotency_key=key,
            callback_url="http://127.0.0.1:8000/cb",
        )
        # Repeat call with exact same idempotency_key
        tx2, url2 = initiate_payment_for_booking(
            user=customer,
            booking_id=booking.id,
            idempotency_key=key,
            callback_url="http://127.0.0.1:8000/cb",
        )
        assert tx1.pk == tx2.pk
        assert url1 == url2
        assert PaymentTransaction.objects.filter(idempotency_key=key).count() == 1

    def test_foreign_customer_cannot_pay(self):
        now = timezone.now()
        owner_customer = UserFactory(role="CUSTOMER")
        attacker_customer = UserFactory(role="CUSTOMER")
        booking = BookingFactory(
            customer=owner_customer,
            status=BookingStatus.PENDING_PAYMENT,
            amount_online_toman=50_000,
            locked_at=now,
            lock_expires_at=now + timedelta(minutes=10),
        )
        with pytest.raises(PermissionDenied):
            initiate_payment_for_booking(
                user=attacker_customer,
                booking_id=booking.id,
                idempotency_key=str(uuid.uuid4()),
                callback_url="http://127.0.0.1:8000/cb",
            )

    def test_expired_lock_rejected(self):
        now = timezone.now()
        customer = UserFactory(role="CUSTOMER")
        booking = BookingFactory(
            customer=customer,
            status=BookingStatus.PENDING_PAYMENT,
            amount_online_toman=50_000,
            locked_at=now - timedelta(minutes=15),
            lock_expires_at=now - timedelta(minutes=5),
        )
        with pytest.raises(InvalidStatusTransitionError) as exc:
            initiate_payment_for_booking(
                user=customer,
                booking_id=booking.id,
                idempotency_key=str(uuid.uuid4()),
                callback_url="http://127.0.0.1:8000/cb",
            )
        assert "expired" in str(exc.value).lower()

    def test_non_payable_booking_status_rejected(self):
        customer = UserFactory(role="CUSTOMER")
        booking = BookingFactory(
            customer=customer,
            status=BookingStatus.CONFIRMED,
            amount_online_toman=50_000,
        )
        with pytest.raises(InvalidStatusTransitionError):
            initiate_payment_for_booking(
                user=customer,
                booking_id=booking.id,
                idempotency_key=str(uuid.uuid4()),
                callback_url="http://127.0.0.1:8000/cb",
            )

    def test_gateway_timeout_during_initiate_marks_timeout(self):
        now = timezone.now()
        customer = UserFactory(role="CUSTOMER")
        booking = BookingFactory(
            customer=customer,
            status=BookingStatus.PENDING_PAYMENT,
            amount_online_toman=50_000,
            locked_at=now,
            lock_expires_at=now + timedelta(minutes=10),
        )
        adapter = reset_sandbox_gateway()
        adapter.set_mode("timeout")

        key = f"key-{uuid.uuid4()}"
        with pytest.raises(PaymentGatewayTimeoutError):
            initiate_payment_for_booking(
                user=customer,
                booking_id=booking.id,
                idempotency_key=key,
                callback_url="http://127.0.0.1:8000/cb",
            )
        tx = PaymentTransaction.objects.get(idempotency_key=key)
        assert tx.status == PaymentStatus.TIMEOUT
        assert "timed out" in tx.error_message.lower()

    def test_gateway_failure_during_initiate_marks_failed(self):
        now = timezone.now()
        customer = UserFactory(role="CUSTOMER")
        booking = BookingFactory(
            customer=customer,
            status=BookingStatus.PENDING_PAYMENT,
            amount_online_toman=50_000,
            locked_at=now,
            lock_expires_at=now + timedelta(minutes=10),
        )
        adapter = reset_sandbox_gateway()
        adapter.set_mode("failure")

        key = f"key-{uuid.uuid4()}"
        with pytest.raises(PaymentGatewayError):
            initiate_payment_for_booking(
                user=customer,
                booking_id=booking.id,
                idempotency_key=key,
                callback_url="http://127.0.0.1:8000/cb",
            )
        tx = PaymentTransaction.objects.get(idempotency_key=key)
        assert tx.status == PaymentStatus.FAILED
        assert "failure" in tx.error_message.lower()


# ---------------------------------------------------------------------------
# 5. Domain Services: verify_payment_transaction
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestVerifyPaymentService:
    def test_verify_payment_success(self):
        now = timezone.now()
        customer = UserFactory(role="CUSTOMER")
        booking = BookingFactory(
            customer=customer,
            status=BookingStatus.PENDING_PAYMENT,
            amount_online_toman=80_000,
            locked_at=now,
            lock_expires_at=now + timedelta(minutes=10),
        )
        tx, _ = initiate_payment_for_booking(
            user=customer,
            booking_id=booking.id,
            idempotency_key=str(uuid.uuid4()),
            callback_url="http://127.0.0.1:8000/cb",
        )
        assert tx.status == PaymentStatus.PENDING

        verified_tx = verify_payment_transaction(provider_reference=tx.provider_reference)
        assert verified_tx.status == PaymentStatus.SUCCESS
        assert verified_tx.tracking_code.startswith("TRK-")
        assert verified_tx.card_pan_masked == "603799******1234"
        assert verified_tx.verified_at is not None

    def test_verify_payment_idempotent_replay(self):
        now = timezone.now()
        customer = UserFactory(role="CUSTOMER")
        booking = BookingFactory(
            customer=customer,
            status=BookingStatus.PENDING_PAYMENT,
            amount_online_toman=80_000,
            locked_at=now,
            lock_expires_at=now + timedelta(minutes=10),
        )
        tx, _ = initiate_payment_for_booking(
            user=customer,
            booking_id=booking.id,
            idempotency_key=str(uuid.uuid4()),
            callback_url="http://127.0.0.1:8000/cb",
        )
        v1 = verify_payment_transaction(provider_reference=tx.provider_reference)
        assert v1.status == PaymentStatus.SUCCESS

        # Replay should safely return same row without error
        v2 = verify_payment_transaction(provider_reference=tx.provider_reference)
        assert v2.pk == v1.pk
        assert v2.status == PaymentStatus.SUCCESS
        assert v2.tracking_code == v1.tracking_code

    def test_verify_unknown_reference_raises_error(self):
        with pytest.raises(PaymentVerificationFailedError):
            verify_payment_transaction(provider_reference="NON_EXISTENT_REF")

    def test_verify_terminal_failed_transaction_rejected(self):
        tx = PaymentTransactionFactory(status=PaymentStatus.FAILED, provider_reference=f"SBX-{uuid.uuid4().hex[:12]}")
        with pytest.raises(PaymentAlreadyProcessedError):
            verify_payment_transaction(provider_reference=tx.provider_reference)

    def test_verify_gateway_timeout_marks_timeout(self):
        tx = PaymentTransactionFactory(
            status=PaymentStatus.PENDING,
            amount_toman=50_000,
            provider_reference=f"SBX-{uuid.uuid4().hex[:12]}",
        )
        adapter = reset_sandbox_gateway()
        adapter.set_mode("timeout")

        with pytest.raises(PaymentGatewayTimeoutError):
            verify_payment_transaction(provider_reference=tx.provider_reference)

        tx.refresh_from_db()
        assert tx.status == PaymentStatus.TIMEOUT
        assert "timed out" in tx.error_message.lower()

    def test_verify_gateway_rejection_marks_failed(self):
        tx = PaymentTransactionFactory(
            status=PaymentStatus.PENDING,
            amount_toman=50_000,
            provider_reference=f"SBX-{uuid.uuid4().hex[:12]}",
        )
        adapter = reset_sandbox_gateway()
        adapter.set_mode("failure")

        with pytest.raises(PaymentVerificationFailedError):
            verify_payment_transaction(provider_reference=tx.provider_reference)

        tx.refresh_from_db()
        assert tx.status == PaymentStatus.FAILED
        assert "failure" in tx.error_message.lower()

    def test_initiate_non_positive_amount_rejected(self):
        now = timezone.now()
        customer = UserFactory(role="CUSTOMER")
        booking = BookingFactory(
            customer=customer,
            status=BookingStatus.PENDING_PAYMENT,
            amount_online_toman=0,
            locked_at=now,
            lock_expires_at=now + timedelta(minutes=10),
        )
        with pytest.raises(ValueError) as exc:
            initiate_payment_for_booking(
                user=customer,
                booking_id=booking.id,
                idempotency_key=str(uuid.uuid4()),
                callback_url="http://cb",
            )
        assert "greater than zero" in str(exc.value)

    def test_verify_amount_mismatch_marks_failed(self):
        tx = PaymentTransactionFactory(
            status=PaymentStatus.PENDING,
            amount_toman=50_000,
            provider_reference=f"SBX-{uuid.uuid4().hex[:12]}",
        )
        # Mock adapter to return mismatched amount
        class MismatchedGatewayAdapter(SandboxGatewayAdapter):
            def verify(self, request):
                from apps.billing.services.gateway import PaymentVerifyResult
                return PaymentVerifyResult(
                    success=True,
                    status="SUCCESS",
                    amount_toman=60_000,  # does not match 50_000
                    tracking_code="TRK-MISMATCH",
                )

        from apps.billing.services.gateway import register_gateway
        register_gateway("mismatch_test", MismatchedGatewayAdapter)

        with pytest.raises(PaymentAmountMismatchError) as exc:
            verify_payment_transaction(
                provider_reference=tx.provider_reference,
                gateway_name="mismatch_test",
            )
        assert "mismatch" in str(exc.value).lower()
        tx.refresh_from_db()
        assert tx.status == PaymentStatus.FAILED

    def test_get_gateway_invalid_provider_raises_error(self):
        with pytest.raises(ValueError) as exc:
            get_gateway("non_existent_provider")
        assert "unknown payment gateway provider" in str(exc.value).lower()

