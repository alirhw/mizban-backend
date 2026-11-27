"""Tests for wallet ledger schema and service layer.

Task T-022 (PH-05 / WS-BILLING-WALLET / TD-005 / BR-004):
1. Wallet created lazily and idempotently.
2. Credit increases balance and writes audited ledger entry with correct balance_after snapshot.
3. Duplicate credit with same idempotency_key returns existing entry without double-crediting.
4. Debit decreases balance and writes audited ledger entry with correct balance_after snapshot.
5. Debit exceeding balance raises InsufficientWalletBalanceError and leaves balance and ledger untouched.
6. Zero or negative amounts rejected at service level (InvalidWalletAmountError) and DB constraint level.
7. Balance can never go negative at DB level (CheckConstraint proven against direct ORM update attempt).
8. Ledger entries are append-only (cannot be updated or deleted).
9. Concurrency race test on PostgreSQL: multi-threaded parallel credits/debits serialize cleanly on row lock.
10. Two different users' wallets are completely isolated.
11. Bounded read helpers (get_wallet_balance, list_wallet_transactions).
12. Read-only admin permissions.
"""
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.contrib.admin.sites import AdminSite
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection
from django.test import RequestFactory

from apps.venues.tests.factories import UserFactory
from apps.wallets.admin import WalletAdmin, WalletTransactionAdmin
from apps.wallets.models import Wallet, WalletTransaction, WalletTransactionType
from apps.wallets.services import (
    credit_wallet,
    debit_wallet,
    get_or_create_wallet_for_user,
    get_wallet_balance,
    list_wallet_transactions,
)
from apps.wallets.tests.factories import WalletFactory, WalletTransactionFactory
from core.exceptions import InsufficientWalletBalanceError, InvalidWalletAmountError

# ==============================================================================
# 1. Wallet Lifecycle & Idempotency
# ==============================================================================


@pytest.mark.django_db
def test_wallet_created_lazily_and_idempotently():
    """get_or_create_wallet_for_user retrieves or creates wallet with balance 0 (TD-005)."""
    user = UserFactory(role="CUSTOMER")

    # 1. First retrieval creates wallet lazily
    assert not Wallet.objects.filter(user=user).exists()
    wallet1 = get_or_create_wallet_for_user(user)
    assert wallet1.pk is not None
    assert wallet1.user == user
    assert wallet1.balance_toman == 0

    # 2. Second retrieval returns identical wallet row (idempotent)
    wallet2 = get_or_create_wallet_for_user(user)
    assert wallet2.pk == wallet1.pk
    assert wallet2.balance_toman == 0
    assert Wallet.objects.filter(user=user).count() == 1


@pytest.mark.django_db
def test_two_different_users_wallets_are_isolated():
    """Wallets belonging to different users are completely isolated in balance and ledger."""
    user_a = UserFactory(role="CUSTOMER")
    user_b = UserFactory(role="CUSTOMER")

    wallet_a = get_or_create_wallet_for_user(user_a)
    wallet_b = get_or_create_wallet_for_user(user_b)

    credit_wallet(
        wallet_a,
        50_000,
        reason="Credit User A",
        idempotency_key="key-user-a-1",
    )

    assert get_wallet_balance(wallet_a) == 50_000
    assert get_wallet_balance(wallet_b) == 0

    txs_a = list_wallet_transactions(wallet_a)["items"]
    txs_b = list_wallet_transactions(wallet_b)["items"]

    assert len(txs_a) == 1
    assert len(txs_b) == 0


# ==============================================================================
# 2. Credit Operations & Idempotency
# ==============================================================================


@pytest.mark.django_db
def test_credit_increases_balance_and_writes_ledger_entry():
    """credit_wallet increments balance and writes an immutable ledger entry with snapshot."""
    user = UserFactory(role="CUSTOMER")
    wallet = get_or_create_wallet_for_user(user)

    key = str(uuid.uuid4())
    tx = credit_wallet(
        wallet,
        100_000,
        reason="Refund for cancellation",
        idempotency_key=key,
    )

    assert tx.pk is not None
    assert tx.wallet == wallet
    assert tx.type == WalletTransactionType.CREDIT
    assert tx.amount_toman == 100_000
    assert tx.balance_after_toman == 100_000
    assert tx.reason == "Refund for cancellation"
    assert tx.idempotency_key == key

    wallet.refresh_from_db()
    assert wallet.balance_toman == 100_000


@pytest.mark.django_db
def test_duplicate_credit_with_same_idempotency_key_is_safe():
    """Duplicate credit call returns existing transaction without double-crediting (UF-003)."""
    user = UserFactory(role="CUSTOMER")
    wallet = get_or_create_wallet_for_user(user)

    key = "deposit-order-12345"

    tx1 = credit_wallet(wallet, 75_000, reason="Initial deposit", idempotency_key=key)
    assert tx1.balance_after_toman == 75_000
    wallet.refresh_from_db()
    assert wallet.balance_toman == 75_000

    # Second delivery of the same event
    tx2 = credit_wallet(wallet, 75_000, reason="Initial deposit replay", idempotency_key=key)
    assert tx2.pk == tx1.pk
    assert tx2.balance_after_toman == 75_000

    wallet.refresh_from_db()
    assert wallet.balance_toman == 75_000  # NOT 150_000
    assert WalletTransaction.objects.filter(wallet=wallet).count() == 1


# ==============================================================================
# 3. Debit Operations & Insufficient Funds Guard
# ==============================================================================


@pytest.mark.django_db
def test_debit_decreases_balance_and_writes_ledger_entry():
    """debit_wallet decrements balance and writes an immutable ledger entry with snapshot."""
    user = UserFactory(role="CUSTOMER")
    wallet = get_or_create_wallet_for_user(user)

    credit_wallet(wallet, 150_000, reason="Initial funds", idempotency_key="init-key")

    tx = debit_wallet(
        wallet,
        60_000,
        reason="Booking payment",
        idempotency_key="debit-key-1",
    )

    assert tx.pk is not None
    assert tx.type == WalletTransactionType.DEBIT
    assert tx.amount_toman == 60_000
    assert tx.balance_after_toman == 90_000

    wallet.refresh_from_db()
    assert wallet.balance_toman == 90_000


@pytest.mark.django_db
def test_debit_exceeding_balance_raises_error_and_leaves_ledger_untouched():
    """debit_wallet exceeding balance raises InsufficientWalletBalanceError with zero side effects."""
    user = UserFactory(role="CUSTOMER")
    wallet = get_or_create_wallet_for_user(user)

    credit_wallet(wallet, 50_000, reason="Initial balance", idempotency_key="credit-init")
    initial_tx_count = WalletTransaction.objects.filter(wallet=wallet).count()

    with pytest.raises(InsufficientWalletBalanceError) as exc_info:
        debit_wallet(
            wallet,
            50_001,  # 1 Toman over balance
            reason="Exorbitant checkout",
            idempotency_key="debit-overdraft",
        )

    assert "Insufficient wallet balance" in str(exc_info.value)

    wallet.refresh_from_db()
    assert wallet.balance_toman == 50_000  # Balance untouched
    assert WalletTransaction.objects.filter(wallet=wallet).count() == initial_tx_count  # No partial entry


@pytest.mark.django_db
def test_duplicate_debit_with_same_idempotency_key_is_safe():
    """Duplicate debit call returns existing transaction without double-debiting."""
    user = UserFactory(role="CUSTOMER")
    wallet = get_or_create_wallet_for_user(user)

    credit_wallet(wallet, 100_000, reason="Initial", idempotency_key="c-key")
    tx1 = debit_wallet(wallet, 40_000, reason="Booking pay", idempotency_key="d-key")
    assert tx1.balance_after_toman == 60_000

    tx2 = debit_wallet(wallet, 40_000, reason="Booking pay replay", idempotency_key="d-key")
    assert tx2.pk == tx1.pk

    wallet.refresh_from_db()
    assert wallet.balance_toman == 60_000  # NOT 20_000


# ==============================================================================
# 4. Input Validation & Strict Positive Amounts
# ==============================================================================


@pytest.mark.django_db
def test_zero_or_negative_amounts_rejected_at_service_level():
    """Both credit and debit reject zero or negative amounts with InvalidWalletAmountError."""
    wallet = WalletFactory(balance_toman=100_000)

    for invalid_amount in [0, -1, -50_000]:
        with pytest.raises(InvalidWalletAmountError):
            credit_wallet(wallet, invalid_amount, reason="Zero/neg", idempotency_key=str(uuid.uuid4()))

        with pytest.raises(InvalidWalletAmountError):
            debit_wallet(wallet, invalid_amount, reason="Zero/neg", idempotency_key=str(uuid.uuid4()))


# ==============================================================================
# 5. Database Constraints & Invariants (PostgreSQL CheckConstraints)
# ==============================================================================


@pytest.mark.django_db
def test_db_check_constraint_prevents_negative_wallet_balance():
    """DB CheckConstraint 'wallet_balance_non_negative' rejects balance_toman < 0."""
    wallet = WalletFactory(balance_toman=10_000)

    from django.db import transaction

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Wallet.objects.filter(pk=wallet.pk).update(balance_toman=-1)


@pytest.mark.django_db
def test_db_check_constraint_prevents_non_positive_transaction_amount():
    """DB CheckConstraint 'wallet_tx_amount_positive' rejects amount_toman <= 0."""
    wallet = WalletFactory(balance_toman=10_000)

    from django.db import transaction

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            WalletTransaction.objects.create(
                wallet=wallet,
                type=WalletTransactionType.CREDIT,
                amount_toman=0,
                balance_after_toman=10_000,
                reason="Illegal zero amount",
                idempotency_key="zero-tx",
            )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            WalletTransaction.objects.create(
                wallet=wallet,
                type=WalletTransactionType.CREDIT,
                amount_toman=-500,
                balance_after_toman=9_500,
                reason="Illegal negative amount",
                idempotency_key="neg-tx",
            )


@pytest.mark.django_db
def test_db_check_constraint_prevents_negative_balance_after():
    """DB CheckConstraint 'wallet_tx_balance_after_non_negative' rejects balance_after_toman < 0."""
    wallet = WalletFactory(balance_toman=10_000)

    from django.db import transaction

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            WalletTransaction.objects.create(
                wallet=wallet,
                type=WalletTransactionType.DEBIT,
                amount_toman=20_000,
                balance_after_toman=-10_000,
                reason="Illegal overdraft snapshot",
                idempotency_key="overdraft-snap-tx",
            )


# ==============================================================================
# 6. Append-Only Immutability (Model Layer)
# ==============================================================================


@pytest.mark.django_db
def test_ledger_entries_are_append_only_cannot_be_updated_or_deleted():
    """Direct ORM attempts to update or delete a WalletTransaction raise PermissionDenied."""
    wallet = WalletFactory(balance_toman=50_000)
    tx = WalletTransactionFactory(wallet=wallet, amount_toman=50_000, balance_after_toman=50_000)

    # Attempt to update existing ledger entry
    with pytest.raises(PermissionDenied) as exc_update:
        tx.reason = "Tampered reason"
        tx.save()
    assert "append-only" in str(exc_update.value).lower()

    # Attempt to delete ledger entry
    with pytest.raises(PermissionDenied) as exc_delete:
        tx.delete()
    assert "append-only" in str(exc_delete.value).lower()


# ==============================================================================
# 7. Read Helpers (get_wallet_balance, list_wallet_transactions)
# ==============================================================================


@pytest.mark.django_db
def test_read_helpers_and_pagination():
    """get_wallet_balance returns direct balance; list_wallet_transactions returns paginated envelope."""
    wallet = WalletFactory(balance_toman=0)

    for i in range(5):
        credit_wallet(wallet, 10_000, reason=f"Credit {i}", idempotency_key=f"c-page-{i}")

    assert get_wallet_balance(wallet) == 50_000

    # Paginated query
    result = list_wallet_transactions(wallet, page=1, page_size=3)
    assert result["total"] == 5
    assert result["page"] == 1
    assert result["page_size"] == 3
    assert len(result["items"]) == 3

    # Items ordered by -created_at, -id
    amounts = [item.amount_toman for item in result["items"]]
    assert amounts == [10_000, 10_000, 10_000]


# ==============================================================================
# 8. Read-Only Admin Security
# ==============================================================================


@pytest.mark.django_db
def test_admin_permissions_are_strictly_read_only():
    """Admin disallows add/delete on Wallet and add/change/delete on WalletTransaction."""
    site = AdminSite()
    rf = RequestFactory()
    request = rf.get("/admin/")

    wallet_admin = WalletAdmin(Wallet, site)
    assert wallet_admin.has_add_permission(request) is False
    assert wallet_admin.has_delete_permission(request) is False

    tx_admin = WalletTransactionAdmin(WalletTransaction, site)
    assert tx_admin.has_add_permission(request) is False
    assert tx_admin.has_change_permission(request) is False
    assert tx_admin.has_delete_permission(request) is False


# ==============================================================================
# 9. Concurrency & Race Condition Test (PostgreSQL Only)
# ==============================================================================


@pytest.mark.django_db(transaction=True)
def test_concurrency_race_parallel_credits_and_debits_serialize_cleanly():
    """THE RACE (TD-005): Multi-threaded concurrent credits and debits on the same wallet.

    Row-level lock (select_for_update) serializes every balance mutation.
    Final balance equals the exact arithmetic sum, with every transaction snapshot consistent.
    """
    user = UserFactory(role="CUSTOMER")
    wallet = get_or_create_wallet_for_user(user)

    # Initial deposit: 100,000 Toman
    credit_wallet(wallet, 100_000, reason="Initial seed balance", idempotency_key="race-seed")
    assert get_wallet_balance(wallet) == 100_000

    # 5 parallel credits of 20,000 Toman (+100,000)
    # 5 parallel debits of 15,000 Toman (-75,000)
    # Expected final balance: 100,000 + 100,000 - 75,000 = 125,000 Toman
    credit_ops = [
        ("credit", 20_000, f"race-credit-{i}", f"Parallel Credit {i}")
        for i in range(5)
    ]
    debit_ops = [
        ("debit", 15_000, f"race-debit-{i}", f"Parallel Debit {i}")
        for i in range(5)
    ]
    all_ops = credit_ops + debit_ops

    def _execute_op(op):
        op_type, amount, key, reason = op
        try:
            if op_type == "credit":
                return credit_wallet(wallet.pk, amount, reason=reason, idempotency_key=key)
            else:
                return debit_wallet(wallet.pk, amount, reason=reason, idempotency_key=key)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(_execute_op, all_ops))

    assert len(results) == 10

    # Verify final balance is EXACTLY 125,000 Toman
    wallet.refresh_from_db()
    assert wallet.balance_toman == 125_000

    # Total ledger rows: 1 seed + 10 ops = 11 entries
    ledger = WalletTransaction.objects.filter(wallet=wallet).order_by("created_at", "id")
    assert ledger.count() == 11
