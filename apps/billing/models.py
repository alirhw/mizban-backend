"""Domain models for the billing app (Payment transactions, split receipts).

Task T-020 (PH-05 / WS-BILLING-WALLET):
- PaymentTransaction model:
  * ForeignKey to Booking (PROTECT) and Customer (PROTECT).
  * Amount in integer Toman (BigIntegerField), currency="TOMAN".
  * State machine: INITIATED -> PENDING -> SUCCESS / FAILED / TIMEOUT.
  * Partial unique constraint on non-null provider_reference (authority).
  * Unique idempotency_key preventing duplicate payment requests.
  * provider_name for gateway factory registration.
  * Masked PAN only (card_pan_masked) - no raw cardholder/PCI data.
"""
from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models

from core.exceptions import InvalidStatusTransitionError


class PaymentStatus(models.TextChoices):
    INITIATED = "INITIATED", "Initiated"
    PENDING = "PENDING", "Pending"
    SUCCESS = "SUCCESS", "Success"
    FAILED = "FAILED", "Failed"
    TIMEOUT = "TIMEOUT", "Timeout"


VALID_PAYMENT_TRANSITIONS: dict[str, set[str]] = {
    PaymentStatus.INITIATED: {
        PaymentStatus.PENDING,
        PaymentStatus.FAILED,
        PaymentStatus.TIMEOUT,
    },
    PaymentStatus.PENDING: {
        PaymentStatus.SUCCESS,
        PaymentStatus.FAILED,
        PaymentStatus.TIMEOUT,
    },
    PaymentStatus.TIMEOUT: {
        PaymentStatus.PENDING,
        PaymentStatus.SUCCESS,
        PaymentStatus.FAILED,
    },
    PaymentStatus.SUCCESS: set(),
    PaymentStatus.FAILED: set(),
}


class PaymentTransaction(models.Model):
    """An online payment transaction through a payment gateway (ARCH-005).

    Covers table reservation fee only (platform share, BR-003). Design add-ons
    are payable to the venue in person.
    """

    booking = models.ForeignKey(
        "bookings.Booking",
        on_delete=models.PROTECT,
        related_name="payment_transactions",
        help_text="The reservation booking this payment is for.",
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payment_transactions",
        help_text="Customer paying for the reservation.",
    )
    amount_toman = models.BigIntegerField(
        help_text="Transaction amount in integer Toman (BR-003: table fee only).",
    )
    currency = models.CharField(
        max_length=10,
        default="TOMAN",
        help_text="Currency identifier (default: TOMAN).",
    )
    status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.INITIATED,
        db_index=True,
    )
    provider_name = models.CharField(
        max_length=50,
        default="sandbox",
        db_index=True,
        help_text="Gateway provider name for factory lookup (e.g. sandbox).",
    )
    provider_reference = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True,
        help_text="Gateway authority or reference token (unique when set).",
    )
    idempotency_key = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="Unique client or service idempotency token.",
    )
    redirect_url = models.TextField(
        blank=True,
        default="",
        help_text="Gateway payment URL for client browser redirection.",
    )
    tracking_code = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Reference/tracking code issued by gateway on successful settlement.",
    )
    card_pan_masked = models.CharField(
        max_length=30,
        blank=True,
        default="",
        help_text="Masked card PAN (e.g. 603799******1234) - never store raw PCI data.",
    )
    error_message = models.TextField(
        blank=True,
        default="",
        help_text="Error message or failure reason if transaction failed.",
    )
    refund_required = models.BooleanField(
        default=False,
        help_text=(
            "Whether this transaction requires a refund to customer bank card "
            "(e.g. late payment when slot occupied)."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    verified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when gateway verification was completed.",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount_toman__gte=0),
                name="payment_amount_non_negative",
            ),
            models.UniqueConstraint(
                fields=["provider_reference"],
                condition=models.Q(provider_reference__isnull=False),
                name="unique_payment_provider_reference",
            ),
        ]
        indexes = [
            models.Index(fields=["booking", "status"], name="idx_pay_booking_status"),
            models.Index(fields=["customer", "status"], name="idx_pay_customer_status"),
            models.Index(fields=["created_at"], name="idx_pay_created_at"),
        ]

    def __str__(self) -> str:
        return (
            f"PaymentTransaction(id={self.pk}, booking={self.booking_id}, "
            f"amount={self.amount_toman} {self.currency}, status={self.status})"
        )

    def transition_to(self, new_status: str, **kwargs: Any) -> None:
        """Validate and apply state transition."""
        allowed = VALID_PAYMENT_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise InvalidStatusTransitionError(
                f"Cannot transition payment transaction {self.pk or 'new'} from {self.status} to {new_status}"
            )
        self.status = new_status
        update_fields = ["status", "updated_at"]
        for key, value in kwargs.items():
            setattr(self, key, value)
            update_fields.append(key)
        if self.pk:
            self.save(update_fields=update_fields)
