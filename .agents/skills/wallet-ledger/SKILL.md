# Skill: Wallet Ledger (TD-005 / BR-05 / BR-06)

## What it teaches
How the in-app wallet stays auditable and can never go negative or be
credited twice: a one-sided ledger where every balance change is a
transaction row, applied atomically under a row lock, on top of a database
CheckConstraint.

## Steps
1. Model: `Wallet` (one per user, `balance` BigInteger Toman) +
   `WalletTransaction` (wallet FK, signed amount, type, reference —
   e.g. the cancelled booking id, balance_after, created_at).
   Constraint: `CheckConstraint(balance >= 0)` on Wallet. The transactions
   table is append-only — never update or delete a row.
2. Every mutation goes through `apps/wallets/services.py` functions
   (`credit`, `debit`) — no other code writes `balance` directly.
3. Inside `transaction.atomic()`: `select_for_update()` the wallet row,
   check the idempotency key (see step 4), apply the change, insert the
   WalletTransaction with the resulting `balance_after`, commit.
4. Idempotency: each credit/debit carries a unique reference
   (e.g. `cancel-refund:{booking_id}`, `booking-pay:{booking_id}`) with a
   unique constraint on (wallet, reference). A repeated call returns the
   existing transaction instead of applying twice — this is what makes
   double-clicks, page refreshes and duplicate callbacks harmless (the
   UF-003 double-credit edge case).
5. Cancellation refund flow: the bookings service (its own transaction
   spanning booking + wallet per the design) locks the booking, verifies
   the ≥36h window (BR-05), sets CANCELLED, then calls `wallets.credit`
   with the booking reference. Refund = 100% of the table fee paid online.
6. Wallet money is closed-loop: usable for future bookings, never
   withdrawable to a bank account (BR-06). There is no payout code path —
   do not build one.
7. Paying with wallet at checkout: debit via the same service in the
   booking transaction; insufficient balance → domain error, no partial
   debit.

## Example
```python
# apps/wallets/services.py — the only door to balance changes
@transaction.atomic
def credit(*, wallet, amount_toman: int, reference: str, tx_type: str):
    existing = WalletTransaction.objects.filter(wallet=wallet, reference=reference).first()
    if existing:
        return existing                      # idempotent replay
    wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
    wallet.balance += amount_toman           # integer Toman, never float
    wallet.save(update_fields=["balance"])
    return WalletTransaction.objects.create(
        wallet=wallet, amount=amount_toman, type=tx_type,
        reference=reference, balance_after=wallet.balance,
    )
```

## Common mistakes
- A bare `balance` field updated with `+=` from views or callbacks
  (untraceable, race-prone — rejected in TD-005).
- Refunding on the GET/callback path without a reference key — the second
  delivery of the same event credits twice.
- Letting the DB constraint be the only guard: services check first and
  raise a domain error; the constraint is the last line, not the UX.
- Floats anywhere near money (rounding drift in Toman is still money).
- Building a "withdraw to card" path — explicitly out of scope (BR-06).
