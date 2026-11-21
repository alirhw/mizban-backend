# Tasks: Phase PH-05 — Billing & Payment Processing (WS-BILLING-WALLET)

> [!NOTE] Numbering Divergence Note
> This roadmap follows the task numbering and dependency ordering of `specs/005-billing/tasks.md`:
> - **T-022:** Internal Wallet Ledger Schema & Service (TD-005 foundation)
> - **T-023:** Wallet Refund & Credit Logic (BR-004 cancellation refunds built upon the ledger)
> - **T-024:** Split Receipt Generation (BR-003 platform share split)
>
> The combined project documentation (Chat-05) numbered these differently (T-022 Split Receipt, T-023 Wallet, T-024 Cancellation). The repository specification order is authoritative here because the wallet ledger is the foundational prerequisite on which cancellation refund credits execute.

## Roadmap & Tracking

- [x] **T-020 — Define Payment Gateway Adapter and PaymentTransaction Schema**
  - Implement `PaymentTransaction` model in `apps/billing/models.py`.
  - Migration `apps/billing/migrations/0001_initial.py` applied cleanly to PostgreSQL 16.15.
  - Gateway interface and `SandboxGatewayAdapter` in `apps/billing/services/gateway.py`.
  - Payment domain services in `apps/billing/services/payment.py` (`initiate_payment_for_booking`, `verify_payment_transaction`).
  - Document timeouts (8.0s), retry behaviour, lifecycle, and sandbox config.
  - **OPEN ITEMS RECORDED:**
    * Gateway Provider choice is OPEN (Product Owner decision pending).
    * Provider-specific callback parameters and verification contract are OPEN.
- [x] **T-021 — Implement Payment Callback and Booking Confirmation Endpoint**
  - Record ADR-006 (`docs/adr/0006-late-payment-callback-policy.md`) covering late payment callback policy, atomic slot re-check, and bank card refund requirement.
  - Forward migration `apps/billing/migrations/0002_paymenttransaction_refund_required.py` adding `refund_required = BooleanField(default=False)`.
  - Guarded transition `BookingStatus.EXPIRED -> BookingStatus.CONFIRMED` in `apps/bookings/models.py:VALID_TRANSITIONS` for late payment confirmations when slot remains free.
  - Confirmation service in `apps/billing/services/payment.py` (`handle_payment_callback`):
    * Step 1: Outside transaction.atomic(), execute server-to-server verification via `verify_payment_transaction`.
    * Step 2: Under transaction.atomic(), row-lock `TablePin` and `Booking` via `select_for_update()`, re-check slot occupancy excluding this booking.
    * Decision tree: (a) on-time free -> CONFIRMED; (b) late free -> CONFIRMED; (c) slot taken -> EXPIRED, `refund_required=True` to bank card; (d) cancelled -> CANCELLED, `refund_required=True`.
  - Callback endpoint in `apps/billing/api.py` handling `GET` and `POST` on `/api/v1/billing/callback/` and `/api/v1/billing/callback` (public, auth=None, trailing-slash tolerant).
  - Standard error envelopes: unknown/missing reference -> 404; malformed payloads -> 422; processed business outcomes -> 200.
  - Mount `/billing` router in `config/api.py`.
  - Comprehensive test suite in `apps/billing/tests/test_payment_callback.py` with 19 tests including PostgreSQL race condition test under row-level locking.
- [x] **T-022 — Implement Internal Wallet Ledger Schema & Service (TD-005 / BR-004)**
  - Initial migration `apps/wallets/migrations/0001_initial.py` applied locally to PostgreSQL 16.15 (**FLAGGED PENDING HUMAN REVIEW** per AGENTS.md).
  - Models in `apps/wallets/models.py`:
    * `Wallet`: OneToOne to User, `balance_toman` BigInteger default 0, DB `CheckConstraint(balance_toman >= 0)`.
    * `WalletTransaction`: One-sided append-only audited ledger, choices `CREDIT`/`DEBIT`, `amount_toman > 0`, `balance_after_toman >= 0`, nullable FKs to Booking and PaymentTransaction, unique `idempotency_key`, model-level immutability (updates/deletions blocked).
  - Services in `apps/wallets/services.py`:
    * `get_or_create_wallet_for_user`: idempotent lazy wallet creation.
    * `credit_wallet`: inside `transaction.atomic()`, row-locks Wallet via `select_for_update()`, checks idempotency, increments balance, writes ledger row with snapshot.
    * `debit_wallet`: inside `transaction.atomic()`, row-locks Wallet via `select_for_update()`, checks idempotency, validates balance ≥ debit (raises `InsufficientWalletBalanceError` if insufficient funds, with zero side effects), decrements balance, writes ledger row.
    * Read helpers: `get_wallet_balance`, `list_wallet_transactions` (bounded, paginated via `core.pagination`).
  - Read-only Django Admin in `apps/wallets/admin.py`: add/delete disabled on Wallet; add/change/delete disabled on WalletTransaction.
  - Invariants strictly enforced: closed-loop wallet (zero cash-out or withdrawal paths; BR-004/TD-005); ADR-006 late-payment refunds go to bank card only, never to wallet; no public API endpoint in this task.
  - Test suite in `apps/wallets/tests/test_wallet_ledger.py` (15 tests passed, including multi-threaded race condition on PostgreSQL).
- [ ] **T-023 — Implement Wallet Refund and Credit Logic (BR-004)**
- [ ] **T-024 — Split Receipt Generation (BR-003)**
