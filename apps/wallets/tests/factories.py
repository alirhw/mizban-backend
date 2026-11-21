"""Model factories for the wallets app (Wallet, WalletTransaction)."""
from __future__ import annotations

import uuid
import factory

from apps.venues.tests.factories import UserFactory
from apps.wallets.models import Wallet, WalletTransaction, WalletTransactionType


class WalletFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Wallet

    user = factory.SubFactory(UserFactory, role="CUSTOMER")
    balance_toman = 0


class WalletTransactionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = WalletTransaction

    wallet = factory.SubFactory(WalletFactory)
    type = WalletTransactionType.CREDIT
    amount_toman = 50_000
    balance_after_toman = 50_000
    reason = "Test wallet transaction"
    idempotency_key = factory.LazyFunction(lambda: f"WTX-{uuid.uuid4().hex[:16].upper()}")
