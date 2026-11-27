# Skill: Iranian Payment Gateway (BR-04 / ARCH-005)

## What it teaches
How Miz Ban takes money through an Iranian (Shaparak) gateway — Zarinpal-
style authority flow behind one adapter interface — with server-side
verification, exact amount matching, idempotent callbacks, and the split
receipt rule: online money is the table fee only.

## Steps
1. One interface in `apps/billing/` (factory/adapter pattern): 
   `request_payment(amount_toman, callback_url, description) -> (authority, redirect_url)`
   and `verify(authority, amount_toman) -> VerifyResult`. Provider
   specifics (merchant id from env, endpoints, status codes) stay inside
   the adapter; services never see them.
2. Start (booking service + billing service): create the
   `PaymentTransaction` row (booking ref, authority placeholder, amount =
   the booking's table fee from the DB — never an amount sent by the
   client), commit the transaction, THEN call `request_payment` —
   **no network call inside `transaction.atomic()`** — store the
   authority, return the redirect URL.
3. The charge is ONLY the table reservation fee (platform share, BR-04).
   Design add-on totals are computed for the receipt as "payable in
   person" and must never enter the gateway amount; the adapter call
   site asserts this split.
4. Callback (user returns with authority + status): this input is
   **untrusted** (it travelled through the user's browser). Call
   `verify(authority, stored_amount)` server-side with an 8s timeout.
   Only a successful verify with the exact stored amount confirms.
5. Idempotency: `authority` is unique. Confirming an already-confirmed
   transaction is a no-op that returns the existing result (duplicate
   callbacks, refresh, double-click). State changes run inside one
   transaction that locks the booking + payment rows
   (`select_for_update()`), per the booking-lock skill.
6. Failure/expiry: failed verify or user abandonment leaves the booking
   PENDING_PAYMENT until `lock_expires_at` passes; availability frees
   itself by timestamp (TD-004). No manual "unlock" code paths.
7. Receipt: after confirmation, issue the split receipt — paid-online
   (table fee, with gateway tracking code) and payable-in-person (add-ons
   total) as separate explicit lines. Both numbers come from DB rows.
8. Sandbox first: develop and test against the gateway's test
   environment; test success, failure, amount-mismatch and duplicate
   callback cases with the adapter mocked at its boundary.

## Example
```python
# apps/billing/services.py — the order that matters
with transaction.atomic():
    tx = PaymentTransaction.objects.create(booking=booking,
                                           amount=booking.table_fee)  # from DB
# committed — now it is legal to talk to the bank:
authority, url = gateway.request_payment(amount=tx.amount,
                                         callback_url=..., description=...)
tx.authority = authority; tx.save(update_fields=["authority"])
```

## Common mistakes
- Confirming on the callback's "OK" parameter without server-side verify.
- Verifying with an amount taken from the request/session instead of the
  stored transaction row.
- Charging table fee + add-ons together "temporarily" (breaks BR-04 and
  creates a settlement duty to venues that the product explicitly avoids).
- Gateway call inside the booking transaction (locks held during bank
  latency — banned by the doc's transaction rules).
- Non-unique authority handling: second callback → second confirmation →
  double wallet effects downstream.
- Logging full callback payloads (they can carry sensitive data — the
  repo rule: never log payment payloads or secrets).
