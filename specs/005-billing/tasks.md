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
- [x] **T-023 — Implement Wallet Refund and Credit Logic (BR-004)**
  - Domain service in `apps/bookings/services.py` (`cancel_booking(booking, *, actor, now=None)`):
    * Row-level locking on `Booking` via `select_for_update()` inside `transaction.atomic()`.
    * Actor authorization: customer ownership verified (raises `PermissionDenied` if actor is not the booking's customer).
    * (a) `CONFIRMED` and `start_at - now >= 36h`: transition to `CANCELLED`, credit 100% of `amount_online_toman` to customer wallet via `credit_wallet()` with `idempotency_key=f"cancel-refund-{booking.id}"` and `booking` audit FK. Transition and credit commit or roll back atomically.
    * (b) `CONFIRMED` and `start_at - now < 36h`: raises `CancellationWindowClosedError` (`error_code="CANCELLATION_WINDOW_CLOSED"`). Booking stays `CONFIRMED`, 0 wallet credit.
    * (c) `PENDING_PAYMENT`: transition to `CANCELLED` (releases slot hold immediately), 0 wallet credit.
    * (d) Already `CANCELLED`: idempotent replay, returns `refunded_to_wallet_toman = 0`.
    * (e) Any other status (`INITIATED`, `EXPIRED`, `COMPLETED`): raises `BookingNotCancellableError` (`error_code="BOOKING_NOT_CANCELLABLE"`). Explicitly blocks ADR-006 `EXPIRED` bookings with `refund_required=True` from wallet refund.
  - Customer cancellation API endpoint in `apps/bookings/api.py`:
    * `POST /api/v1/bookings/{booking_id}/cancel/` and `POST /api/v1/bookings/{booking_id}/cancel` (trailing-slash tolerant).
    * Requires customer authentication (`auth=auth`).
    * Error handling: 401 unauthenticated, 403 foreign user, 404 unknown booking, 400 window closed, 409 not cancellable.
    * Returns `BookingCancelOut(booking_id, status, refunded_to_wallet_toman, wallet_balance_toman)`.
  - Freed slot is immediately bookable (excluded from `is_table_slot_occupied`).
  - Zero database schema changes / migrations created.
  - Zero `refund_required` payments credited to wallet (ADR-006 boundary preserved).
  - Test suite in `apps/bookings/tests/test_cancellation.py` (14 comprehensive tests passed).
- [x] **T-024 — Split Receipt Generation (BR-003)**
  - Pure-read domain service `get_split_receipt(booking, *, actor)` in `apps/bookings/services.py`:
    * Bounded 3-query read (`select_related("venue", "table_pin")` + `prefetch_related` for `BookingAddon+DesignAddon` and safe columns of `SUCCESS` `PaymentTransaction`).
    * Header: booking id, status, venue name/slug, table_number, aware UTC `start_at`/`end_at`, local `slot_date`/`slot_start_time`, and Jalali helpers (`jalali_date`, `jalali_start_datetime`, `jalali_end_datetime`).
    * Section 1 (`paid_online`): table reservation fee (`amount_online_toman`, 100% platform share) plus safe payment metadata (`provider_name`, `card_pan_masked`) only if a `SUCCESS` `PaymentTransaction` exists; never raw payloads, full PAN, or `provider_reference`.
    * Section 2 (`payable_in_person`): itemised `BookingAddon` price snapshots (`addon_id`, `title`, `unit_fee_toman`, `line_total_toman`) and `total_in_person_toman`.
    * Totals: `total_online_toman`, `total_in_person_toman`, `grand_total_toman = online + in_person`.
    * Availability rule: `CONFIRMED` or `COMPLETED` only; all other statuses raise `ReceiptNotAvailableError` (`error_code="RECEIPT_NOT_AVAILABLE"`, HTTP 409).
    * Consistency guard: sum of `BookingAddon.price_snapshot_toman` must equal `booking.amount_in_person_toman`, else raises `ReceiptDataInconsistencyError` (`error_code="RECEIPT_DATA_INCONSISTENCY"`, HTTP 500).
    * Ownership: strictly the booking's own customer (403 for foreign customers, venue owners, or admins).
  - Typed Pydantic schemas with `extra="forbid"` and `_toman` money suffixes in `apps/bookings/schemas.py` (`SplitReceiptOut`, `SplitReceiptOnlineSectionOut`, `SplitReceiptInPersonSectionOut`, `SplitReceiptAddonLineOut`).
  - Endpoint `GET /api/v1/bookings/{booking_id}/receipt/` (and `/receipt` trailing-slash alias) in `apps/bookings/api.py` with `auth=auth`.
  - Refreshed `api/openapi.snapshot.json`.
  - Zero schema changes / zero migrations; zero money-moving code paths touched.
  - Test suite in `apps/bookings/tests/test_split_receipt.py` (19 tests passed, including PostgreSQL bounded query-count assertion).
