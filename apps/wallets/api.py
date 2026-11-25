"""Django Ninja router for the wallets app (Internal wallet and refund ledger).

Mounted centrally in config/api.py. Endpoints land here task by task;
views stay thin (Architecture Spec section 14): authenticate, validate
via schemas.py, delegate to services.py, map domain errors.
"""
from __future__ import annotations

from ninja import Router

from apps.accounts.auth import auth
from apps.wallets import services
from apps.wallets.schemas import WalletMeOut

router = Router(tags=["wallets"])


@router.get(
    "/me/",
    response={200: WalletMeOut},
    auth=auth,
    summary="Get authenticated customer's wallet balance and recent entries (PH-06-03-PRE)",
)
@router.get(
    "/me",
    response={200: WalletMeOut},
    auth=auth,
    summary="Get authenticated customer's wallet (trailing-slash alias)",
    include_in_schema=False,
)
def get_my_wallet_endpoint(request):
    """Read-only wallet balance and latest 20 ledger entries for the authenticated customer."""
    return services.get_customer_wallet_summary(request.auth, max_entries=20)
