"""Pydantic in/out schemas for the wallets app.

Naming (Architecture Spec section 28): PascalCase with an explicit
In/Out suffix, e.g. WalletMeOut / WalletLedgerEntryOut.
"""
from __future__ import annotations

from datetime import datetime

from ninja import Schema
from pydantic import ConfigDict


class WalletLedgerEntryOut(Schema):
    """Read-only wallet ledger entry for the customer wallet view (PH-06-03-PRE)."""

    model_config = ConfigDict(extra="forbid")

    id: int
    direction: str
    amount_toman: int
    reason: str
    jalali_date: str
    created_at: datetime


class WalletMeOut(Schema):
    """Read-only customer wallet balance and latest ledger entries (PH-06-03-PRE)."""

    model_config = ConfigDict(extra="forbid")

    balance_toman: int
    entries: list[WalletLedgerEntryOut]
