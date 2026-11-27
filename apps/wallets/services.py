"""Service layer for the wallets app (Wallet balance mutations and audited ledger).

Task T-022 (PH-05 / WS-BILLING-WALLET / TD-005 / BR-004):
- ARCH-001 service discipline: This is the ONLY door to wallet balance changes.
- get_or_create_wallet_for_user: Idempotent lazy wallet creation.
- credit_wallet:
  * Selects wallet row with select_for_update() inside transaction.atomic().
  * Validates amount_toman > 0 (InvalidWalletAmountError).
  * Idempotent replay: duplicate idempotency_key returns existing transaction.
  * Increments balance and writes append-only ledger row with balance_after_toman snapshot.
- debit_wallet:
  * Same lock discipline inside transaction.atomic().
  * Validates amount_toman > 0 (InvalidWalletAmountError).
  * Validates sufficient balance; if debit exceeds balance, raises InsufficientWalletBalanceError
    with zero side effects (no partial debit, no ledger entry).
  * Decrements balance and writes append-only ledger row with balance_after_toman snapshot.
- Read helpers: get_wallet_balance, list_wallet_transactions (bounded, paginated).
- Concurrency safety: Two concurrent operations on the same wallet serialize on row lock;
  final balance equals the exact arithmetic sum.
- Closed-loop invariant: No withdrawal or cash-out functions (BR-004 / TD-005).
"""
from __future__ import annotations

import logging
from typing import Any

from django.db import transaction

from apps.wallets.models import Wallet, WalletTransaction, WalletTransactionType
from core.exceptions import InsufficientWalletBalanceError, InvalidWalletAmountError
from core.pagination import paginate

logger = logging.getLogger(__name__)


def get_or_create_wallet_for_user(user: Any) -> Wallet:
    """Retrieve or lazily create an in-app wallet for a customer user (TD-005).

    Guarantees:
    - Idempotent: repeated calls return the same wallet.
    - Initial balance is 0 Toman.
    """
    user_id = user.pk if hasattr(user, "pk") else user
    wallet, created = Wallet.objects.get_or_create(user_id=user_id)
    if created:
        logger.info("Created new wallet id=%s for user_id=%s with 0 Toman balance", wallet.pk, user_id)
    return wallet


def credit_wallet(
    wallet: Wallet | int,
    amount_toman: int,
    *,
    reason: str,
    idempotency_key: str,
    booking: Any = None,
    payment_transaction: Any = None,
) -> WalletTransaction:
    """Deposit funds into a customer's wallet and write an audited ledger entry (TD-005).

    Guarantees:
    - Atomicity: executes under transaction.atomic() with select_for_update() row lock.
    - Idempotency: duplicate idempotency_key returns existing transaction without double-crediting.
    - Strict validation: amount_toman must be an integer > 0 (InvalidWalletAmountError).
    - Writes immutable WalletTransaction with balance_after_toman snapshot.
    """
    if not isinstance(amount_toman, int) or amount_toman <= 0:
        raise InvalidWalletAmountError(
            f"Wallet credit amount must be a strictly positive integer, got: {amount_toman}"
        )

    # Idempotency fast-path
    existing = WalletTransaction.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        logger.info(
            "Wallet credit idempotency hit for key %s (tx id=%s, amount=%s)",
            idempotency_key,
            existing.pk,
            existing.amount_toman,
        )
        return existing

    wallet_id = wallet.pk if isinstance(wallet, Wallet) else wallet

    with transaction.atomic():
        # Re-check idempotency under transaction boundary
        existing = WalletTransaction.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing

        # Acquire exclusive row-level lock on the Wallet
        locked_wallet = Wallet.objects.select_for_update().get(pk=wallet_id)

        # Increment balance in integer Toman
        locked_wallet.balance_toman += amount_toman
        locked_wallet.save(update_fields=["balance_toman", "updated_at"])

        # Write immutable append-only ledger transaction
        tx = WalletTransaction.objects.create(
            wallet=locked_wallet,
            type=WalletTransactionType.CREDIT,
            amount_toman=amount_toman,
            balance_after_toman=locked_wallet.balance_toman,
            reason=reason,
            idempotency_key=idempotency_key,
            booking=booking,
            payment_transaction=payment_transaction,
        )
        logger.info(
            "Wallet id=%s credited +%s Toman (new balance=%s, tx id=%s, booking_id=%s, reason=%s)",
            locked_wallet.pk,
            amount_toman,
            locked_wallet.balance_toman,
            tx.pk,
            getattr(booking, "pk", None),
            reason,
        )
        return tx


def debit_wallet(
    wallet: Wallet | int,
    amount_toman: int,
    *,
    reason: str,
    idempotency_key: str,
    booking: Any = None,
    payment_transaction: Any = None,
) -> WalletTransaction:
    """Spend funds from a customer's wallet and write an audited ledger entry (TD-005).

    Guarantees:
    - Atomicity: executes under transaction.atomic() with select_for_update() row lock.
    - Idempotency: duplicate idempotency_key returns existing transaction without double-debiting.
    - Strict validation: amount_toman must be an integer > 0 (InvalidWalletAmountError).
    - Insufficient funds guard: if debit > current balance, raises InsufficientWalletBalanceError
      and leaves balance and ledger completely untouched (no partial debit).
    - Writes immutable WalletTransaction with balance_after_toman snapshot.
    """
    if not isinstance(amount_toman, int) or amount_toman <= 0:
        raise InvalidWalletAmountError(
            f"Wallet debit amount must be a strictly positive integer, got: {amount_toman}"
        )

    # Idempotency fast-path
    existing = WalletTransaction.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        logger.info(
            "Wallet debit idempotency hit for key %s (tx id=%s, amount=%s)",
            idempotency_key,
            existing.pk,
            existing.amount_toman,
        )
        return existing

    wallet_id = wallet.pk if isinstance(wallet, Wallet) else wallet

    with transaction.atomic():
        # Re-check idempotency under transaction boundary
        existing = WalletTransaction.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing

        # Acquire exclusive row-level lock on the Wallet
        locked_wallet = Wallet.objects.select_for_update().get(pk=wallet_id)

        # Insufficient balance check (TD-005: wallet may never go negative)
        if locked_wallet.balance_toman < amount_toman:
            logger.warning(
                "Wallet id=%s insufficient balance (%s Toman) for debit of %s Toman",
                locked_wallet.pk,
                locked_wallet.balance_toman,
                amount_toman,
            )
            raise InsufficientWalletBalanceError(
                f"Insufficient wallet balance ({locked_wallet.balance_toman} Toman) for debit of {amount_toman} Toman.",
                details={
                    "wallet_id": locked_wallet.pk,
                    "current_balance": locked_wallet.balance_toman,
                    "requested_debit": amount_toman,
                },
            )

        # Decrement balance in integer Toman
        locked_wallet.balance_toman -= amount_toman
        locked_wallet.save(update_fields=["balance_toman", "updated_at"])

        # Write immutable append-only ledger transaction
        tx = WalletTransaction.objects.create(
            wallet=locked_wallet,
            type=WalletTransactionType.DEBIT,
            amount_toman=amount_toman,
            balance_after_toman=locked_wallet.balance_toman,
            reason=reason,
            idempotency_key=idempotency_key,
            booking=booking,
            payment_transaction=payment_transaction,
        )
        logger.info(
            "Wallet id=%s debited -%s Toman (new balance=%s, tx id=%s, reason=%s)",
            locked_wallet.pk,
            amount_toman,
            locked_wallet.balance_toman,
            tx.pk,
            reason,
        )
        return tx


def get_wallet_balance(wallet: Wallet | int) -> int:
    """Retrieve current wallet balance in integer Toman directly from the database."""
    wallet_id = wallet.pk if isinstance(wallet, Wallet) else wallet
    balance = Wallet.objects.filter(pk=wallet_id).values_list("balance_toman", flat=True).first()
    if balance is None:
        raise Wallet.DoesNotExist(f"Wallet with id {wallet_id} does not exist.")
    return balance


def list_wallet_transactions(
    wallet: Wallet | int,
    *,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """Retrieve paginated ledger transaction history for a wallet (bounded reads)."""
    wallet_id = wallet.pk if isinstance(wallet, Wallet) else wallet
    qs = (
        WalletTransaction.objects.filter(wallet_id=wallet_id)
        .select_related("booking", "payment_transaction")
        .order_by("-created_at", "-id")
    )
    return paginate(qs, page=page, page_size=page_size)


def get_customer_wallet_summary(user: Any, *, max_entries: int = 20) -> dict[str, Any]:
    """Read-only customer wallet balance and recent ledger entries (PH-06-03-PRE).

    - CUSTOMER role only (VENUE_OWNER/non-customer raises PermissionDenied -> 403).
    - Does NOT create a Wallet row on read: customers without a wallet receive balance 0 and [].
    - Reuses get_wallet_balance() so balance matches BookingCancelOut.wallet_balance_toman.
    """
    from django.core.exceptions import PermissionDenied
    from apps.accounts.models import UserRole
    from core.jalali import format_jalali

    if getattr(user, "role", None) != UserRole.CUSTOMER:
        raise PermissionDenied("Only customers can access their wallet.")

    wallet = Wallet.objects.filter(user=user).first()
    if wallet is None:
        return {"balance_toman": 0, "entries": []}

    balance = get_wallet_balance(wallet)
    txs = list(
        WalletTransaction.objects.filter(wallet=wallet)
        .order_by("-created_at", "-id")[:max_entries]
    )
    return {
        "balance_toman": balance,
        "entries": [
            {
                "id": tx.id,
                "direction": "credit" if tx.type == WalletTransactionType.CREDIT else "debit",
                "amount_toman": tx.amount_toman,
                "reason": tx.reason,
                "jalali_date": format_jalali(tx.created_at, fmt="%Y/%m/%d %H:%M"),
                "created_at": tx.created_at,
            }
            for tx in txs
        ],
    }
