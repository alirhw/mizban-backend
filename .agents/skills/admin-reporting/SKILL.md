# Skill: Admin Financial Report (FR-40, UC-10)

## What it teaches
How the admin sees the platform's money — payment transactions (table
fee and subscription) and wallet transactions, with a time filter and
summed amounts — read-only, admin-only, and with the sums computed in
the database, never in Python over one page of rows.

## Steps
1. Admin-only: the endpoint requires role ADMIN (checked in the service,
   not just by hiding a link — "hidden in the UI" is never enforcement).
   A venue owner or customer calling it gets 403. Test all three roles.
   Whether `is_staff` alone also qualifies is pinned at G2 (proposal:
   role ADMIN only — the User model already has an ADMIN role).
2. Read-only: this task adds NO write endpoint, NO export, NO payout.
   CSV/PDF export is NOT in FR-40 — do not add it "while you're here".
3. Sources — read the two existing ledger tables, nothing else:
   - `billing.PaymentTransaction`: `amount_toman`, `status`. Sums count
     `SUCCESS` rows only — FAILED / TIMEOUT / INITIATED / PENDING rows
     are listed (if the spec wants them listed) but NEVER summed.
   - `wallets.WalletTransaction`: `amount_toman`, `type` (CREDIT/DEBIT),
     append-only ledger (TD-005) — the report reads it, never writes it.
   - Subscription payments: NONE exist yet (FR-27 online purchase is
     post-MVP; subscriptions are manual admin activation). The report
     must show an empty subscription section, not invent rows and not
     treat the absence as an error.
4. Filters (FR-40: "with a time filter and sum of amounts"): `from` /
   `to` as Tehran local dates, converted ONCE at the API boundary to a
   UTC range (ARCH-006), plus optional type/status filters pinned at
   G2. A missing `to` means "up to now"; a missing `from` means "from
   the beginning" — pin both defaults at G1, do not guess them in code.
5. Sums in the DB: `SUM(amount_toman)` aggregations in the query (one
   query per section), integer Toman, never float, never summed in
   Python over the returned page. The totals must cover the WHOLE
   filtered set, not just the current page — a total that changes when
   you turn the page is a bug.
6. Bounded pagination: default 50 rows, max 100 (pinned at G2). The
   endpoint must stay fast on a growing ledger — the Database Engineer
   confirms the indexes (`created_at`, `status`, `type`) at G2.
7. Privacy: the report out-schema contains only the fields the spec
   names. Do NOT include customer phone numbers unless the G1 spec
   explicitly requires them (proposal: no phone — use user id / masked
   identifier). The admin already sees users in Django Admin; that does
   not authorise phone numbers in this API response.
8. Money display: amounts arrive as integer Toman; the frontend formats
   them for display and never recalculates totals on the client.

## Example
```python
# services.py — totals over the whole filtered set, in the DB
payments = PaymentTransaction.objects.filter(
    status=PaymentStatus.SUCCESS, created_at__range=(start_utc, end_utc)
)
totals = payments.aggregate(total_toman=Sum("amount_toman"))
page = payments.order_by("-created_at")[:50]   # totals do NOT come from page
```

## Common mistakes
- Summing FAILED or PENDING payments into the total (money that never
  arrived, counted as revenue).
- Summing only the current page and calling it the total.
- Computing sums in Python with floats (rounding drift in Toman is
  still money).
- Letting a venue owner or customer reach the endpoint (role check in
  the view only, or no check at all).
- Inventing subscription payment rows to fill an empty section (FR-27
  is post-MVP — empty is the correct answer).
- Adding a CSV export or a payout action to a read-only report task.
