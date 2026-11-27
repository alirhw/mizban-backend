"""Django Admin registration for the wallets app.

Task T-022 (PH-05 / WS-BILLING-WALLET / TD-005):
- Read-only audit views for Wallet and WalletTransaction.
- Disables add/delete on Wallet (balance cannot be edited via admin).
- Disables add/change/delete on WalletTransaction (append-only ledger audit trail).
"""
from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from apps.wallets.models import Wallet, WalletTransaction


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    """Read-only admin view for customer Wallets."""

    list_display = ("id", "user", "balance_toman", "created_at", "updated_at")
    search_fields = ("user__phone",)
    readonly_fields = ("user", "balance_toman", "created_at", "updated_at")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    """Read-only append-only ledger transaction audit view."""

    list_display = (
        "id",
        "wallet",
        "type",
        "amount_toman",
        "balance_after_toman",
        "reason",
        "idempotency_key",
        "created_at",
    )
    list_filter = ("type", "created_at")
    search_fields = (
        "idempotency_key",
        "reason",
        "wallet__user__phone",
    )
    readonly_fields = (
        "wallet",
        "type",
        "amount_toman",
        "balance_after_toman",
        "reason",
        "booking",
        "payment_transaction",
        "idempotency_key",
        "created_at",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False
