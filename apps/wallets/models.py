"""Domain models for the wallets app (Wallet, WalletTransaction).

Task T-022 (PH-05 / WS-BILLING-WALLET / TD-005 / BR-004):
- Wallet:
  * One-to-one per customer user.
  * Integer Toman balance (never float).
  * CheckConstraint: balance_toman >= 0 (the wallet may never go negative).
  * Lazily created via service (get_or_create_wallet_for_user).
- WalletTransaction:
  * One-sided append-only audited ledger.
  * Types: CREDIT, DEBIT.
  * CheckConstraint: amount_toman > 0.
  * Balance after snapshot: balance_after_toman.
  * ForeignKeys to source objects (Booking, PaymentTransaction) with PROTECT/SET_NULL.
  * Unique idempotency_key preventing double-credit / double-debit (UF-003).
  * Immutable: updates and deletions are strictly forbidden at the model layer.
"""
from __future__ import annotations

from typing import Any, NoReturn

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import models


class Wallet(models.Model):
    """Customer in-app wallet balance tracking (TD-005 / BR-004).

    Closed-loop store credit usable exclusively for future reservations.
    Never withdrawable or refundable to bank cards (BR-004).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="wallet",
        help_text="Customer user who owns this wallet.",
    )
    balance_toman = models.BigIntegerField(
        default=0,
        help_text="Current wallet balance in integer Toman (never negative, TD-005).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(balance_toman__gte=0),
                name="wallet_balance_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"Wallet(user_id={self.user_id}, balance={self.balance_toman} Toman)"


class WalletTransactionType(models.TextChoices):
    CREDIT = "CREDIT", "Credit"
    DEBIT = "DEBIT", "Debit"


class WalletTransaction(models.Model):
    """Audited append-only ledger transaction (TD-005).

    Every balance change on a Wallet creates exactly one immutable ledger entry.
    Rows are never updated or deleted.
    """

    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.PROTECT,
        related_name="transactions",
        help_text="Target wallet for this ledger entry (PROTECT prevents cascade delete).",
    )
    type = models.CharField(
        max_length=20,
        choices=WalletTransactionType.choices,
        db_index=True,
        help_text="Transaction direction: CREDIT (deposit) or DEBIT (spending).",
    )
    amount_toman = models.BigIntegerField(
        help_text="Transaction amount in integer Toman (strictly positive, TD-005).",
    )
    balance_after_toman = models.BigIntegerField(
        help_text="Snapshot of the wallet balance immediately after this transaction.",
    )
    reason = models.CharField(
        max_length=255,
        help_text="Human-readable reason, reference, or description for the transaction.",
    )
    booking = models.ForeignKey(
        "bookings.Booking",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wallet_transactions",
        help_text="Associated reservation booking if this entry originated from a booking.",
    )
    payment_transaction = models.ForeignKey(
        "billing.PaymentTransaction",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wallet_transactions",
        help_text="Associated gateway payment transaction if this entry originated from payment.",
    )
    idempotency_key = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="Unique client or service idempotency token preventing duplicate entry.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount_toman__gt=0),
                name="wallet_tx_amount_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(balance_after_toman__gte=0),
                name="wallet_tx_balance_after_non_negative",
            ),
        ]
        indexes = [
            models.Index(fields=["wallet", "created_at"], name="idx_wallet_tx_created_at"),
            models.Index(fields=["idempotency_key"], name="idx_wallet_tx_idemp"),
            models.Index(fields=["wallet", "type"], name="idx_wallet_tx_type"),
        ]

    def __str__(self) -> str:
        return (
            f"WalletTransaction(id={self.pk}, wallet_id={self.wallet_id}, "
            f"type={self.type}, amount={self.amount_toman} Toman, "
            f"balance_after={self.balance_after_toman} Toman)"
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Enforce append-only ledger immutability: existing entries cannot be updated."""
        if self.pk:
            raise PermissionDenied("Ledger entries are append-only and cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        """Enforce append-only ledger immutability: ledger entries cannot be deleted."""
        raise PermissionDenied("Ledger entries are append-only and cannot be deleted.")
