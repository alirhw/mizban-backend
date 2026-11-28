# Spec 005 — Payment Gateway Adapter & PaymentTransaction Schema

**Feature:** 005 — Billing & Payment Processing  
**Status:** Complete (Tasks T-020, T-021, T-022, T-023, T-024 Completed)  
**Governing ADR:** ADR-004 (Internal Wallet Transaction Policy, Audited Ledger)  
**Architecture Rules:** ARCH-005 (Payment Gateway & Double-Entry Ledger, no network call inside atomic transaction, exact amount verification, split receipt), ARCH-001 (Thin Views), ARCH-006 (UTC Instants)  
**Business Rules:** BR-003 (Platform Fee Split: 100% online platform reservation fee, in-person design items payable at venue), BR-004 (Wallet Refund Policy)  
**Technical Decisions:** TD-004 (Concurrency Lock & State Machine), TD-005 (Internal Wallet & Double-Entry Audit)  

---

## 1. Goal

Establish the online payment processing infrastructure for Miz Ban:
1. Provide an abstract, provider-agnostic **Payment Gateway Adapter** interface isolating provider-specific network calls, request/response formats, and status codes from core domain services.
2. Implement the **PaymentTransaction** model tracking the complete lifecycle of each online payment with database constraints, audit columns, and state machine validation.
3. Enforce **BR-003 split fee policy**: online charge covers the table reservation fee only (`amount_online_toman`); venue design add-ons are payable in person.
4. Guarantee **zero network calls inside database atomic blocks** (`transaction.atomic()`).
5. Provide a deterministic, zero-network **SandboxGatewayAdapter** supporting configurable success, failure, and timeout simulation modes for automated testing and local development.
6. Support server-side verification with exact amount matching, preventing client-side price tampering or spoofed callbacks.

---

## 2. Invariants & Rules

- **REQ-PAY-001 (Gateway Provider Choice is OPEN):**
  - **Status:** **OPEN DECISION** (Product Owner has not selected an IPG provider yet).
  - No real gateway SDK, merchant credentials, or vendor-specific endpoints are committed in T-020.
  - The domain service and data models interact exclusively through `PaymentGatewayAdapter`.
- **REQ-PAY-002 (Provider-Specific Callback Contract is OPEN):**
  - **Status:** **OPEN SPECIFICATION** (Detailed callback parameter names, e.g. `Authority`, `Status`, `RefId`, `trackId`, will be mapped in T-021 once the provider is chosen).
  - Server-side verification is mandatory; callback query parameters are treated as untrusted hints.
- **REQ-PAY-003 (Fee Split — BR-003):**
  - The payment transaction amount is strictly `booking.amount_online_toman` (the table reservation fee / platform share).
  - Design add-ons (`amount_in_person_toman`) are excluded from online payment.
- **REQ-PAY-004 (Transaction Boundary & No Network in Atomic):**
  - `PaymentTransaction` row is created and committed in `INITIATED` status before invoking external gateway network requests.
  - Database row locks (`select_for_update()`) are never held across external HTTP latency.
- **REQ-PAY-005 (State Machine & Terminal States):**
  - States: `INITIATED`, `PENDING`, `SUCCESS`, `FAILED`, `TIMEOUT`.
  - Allowed transitions:
    - `INITIATED` -> `{PENDING, FAILED, TIMEOUT}`
    - `PENDING` -> `{SUCCESS, FAILED, TIMEOUT}`
    - `TIMEOUT` -> `{PENDING, SUCCESS, FAILED}`
    - `SUCCESS` -> `set()` (Terminal, immutable)
    - `FAILED` -> `set()` (Terminal, immutable)
  - Any invalid transition raises `InvalidStatusTransitionError`.
- **REQ-PAY-006 (Timeout & Retry Policy):**
  - **Timeout:** 8.0 seconds hard ceiling on all gateway operations (`PAYMENT_GATEWAY_TIMEOUT_SECONDS = 8.0`).
  - **Retries:** **0 blind retries** on payment initiation to prevent duplicate transactions or double reservations. On timeout during initiation, status transitions to `TIMEOUT`.
  - **Callback Verification:** Callback verification is idempotent. Repeated verification requests for an already `SUCCESS` transaction return the existing record immediately without re-calling the gateway.
- **REQ-PAY-007 (Data Protection & PCI/Shaparak Compliance):**
  - No raw credit/debit card numbers, CVV2, expiration dates, or bank passwords are ever stored or logged.
  - Only masked card PAN (e.g. `603799******1234`) and official gateway tracking codes are persisted.

---

## 3. Architecture & Adapter Pattern

```
+-------------------------------------------------------------+
|                      Domain Service                         |
|     (initiate_payment_for_booking / verify_payment)         |
+------------------------------+------------------------------+
                               |
                               v
+-------------------------------------------------------------+
|                  PaymentGatewayAdapter (ABC)                |
|  + initiate(PaymentInitiateRequest) -> PaymentInitiateResult|
|  + verify(PaymentVerifyRequest) -> PaymentVerifyResult      |
|  + get_status(authority) -> PaymentStatusResult             |
+------------------------------+------------------------------+
                               |
               +---------------+---------------+
               |                               |
               v                               v
+-------------------------------+  +--------------------------+
|     SandboxGatewayAdapter     |  |   Future Real IPG       |
|  (In-Memory Mock, 0 Network)  |  |   (T-021+ Provider)     |
+-------------------------------+  +--------------------------+
```

---

## 4. Sandbox Gateway Configuration

The sandbox gateway adapter is registered as `"sandbox"` and is the default provider (`settings.PAYMENT_GATEWAY_PROVIDER = "sandbox"`).

Configurable simulation modes:
- `adapter.set_mode("success")`: Simulates standard approved initiation and verification with generated `SBX-...` authorities and `TRK-...` tracking codes.
- `adapter.set_mode("failure")`: Simulates gateway decline / rejection.
- `adapter.set_mode("timeout")`: Raises `PaymentGatewayTimeoutError` simulating an 8.0s gateway timeout.
- `adapter.reset()`: Resets mode to `"success"` and clears in-memory transactions.

---

## 5. Payment Callback and Confirmation (Task T-021)

**Governing Decision:** ADR-006 (`docs/adr/0006-late-payment-callback-policy.md`)  
**Endpoint:** `/api/v1/billing/callback/` (and `/api/v1/billing/callback`, trailing-slash tolerant per Architecture Spec section 14).  
**Methods:** `GET` and `POST`.  
**Authentication:** `auth=None` (Public: requests originate from client browsers returning from the IPG or direct server-to-server IPG webhooks).

### 5.1 Callback Decision Tree (ADR-006 / ARCH-ISSUE-02)

1. **Step 1 — Server-to-Server Verification (Outside `transaction.atomic()`):**
   - Extract `provider_reference` via gateway adapter (`extract_reference`).
   - If reference is missing or not found in database: return HTTP 404 (`NOT_FOUND` envelope).
   - If payload is malformed or invalid JSON: return HTTP 422 (`VALIDATION_ERROR` envelope).
   - Execute `verify_payment_transaction(provider_reference=ref, callback_params=params)`.
   - Never trust client parameters for status or amount; verify exact amount against stored `amount_toman`.
   - If verification returns `FAILED` or `TIMEOUT`: transaction is updated accordingly; booking remains unconfirmed; returns HTTP 200 with `refund_required=False`.

2. **Step 2 — Atomic Slot Re-Check & Row Locking (Inside `transaction.atomic()`):**
   - Acquire exclusive row lock on `TablePin` via `TablePin.objects.select_for_update().get(...)`.
   - Acquire exclusive row lock on `Booking` via `Booking.objects.select_for_update().get(...)`.
   - Check slot occupancy on that table pin and slot, **excluding this booking itself**.
   - **Outcomes:**
     * **Case A (On-Time Success):** Lock unexpired (`lock_expires_at > now`) and slot free $\to$ transition booking to `CONFIRMED`. `refund_required = False`.
     * **Case B (Late Callback — Slot Still Free):** Lock expired or booking lazily marked `EXPIRED`, but slot is free $\to$ transition booking to `CONFIRMED` via the ADR-006 guarded transition. `refund_required = False`.
     * **Case C (Late Callback — Slot Occupied):** Slot held by another `CONFIRMED` booking or active `PENDING_PAYMENT` hold $\to$ booking marked `EXPIRED`. Transaction remains `SUCCESS` with `refund_required = True`.
     * **Case D (Customer Cancelled):** Booking was `CANCELLED` $\to$ never resurrected. Booking remains `CANCELLED`, transaction has `refund_required = True`.
     * **Case E (Booking Already CONFIRMED — Duplicate Payment, T-045):** Booking is already `CONFIRMED` and another `SUCCESS` `PaymentTransaction` exists for the same booking (excluding this transaction) $\to$ booking remains `CONFIRMED`, this transaction remains `SUCCESS` and persists `refund_required = True`. (If no other `SUCCESS` transaction exists, `refund_required = False`.)

### 5.2 Mandatory Bank Card Refund Policy

When `refund_required = True` (Cases C, D, and E), the refund **must return to the customer's original bank card/account**, never to the in-app wallet. The in-app wallet under BR-004 and TD-005 is strictly reserved for voluntary customer cancellations initiated at least 36 hours before slot time. In this Sandbox phase, `refund_required = True` is recorded as an auditable flag on `PaymentTransaction`.

---

## 6. Internal Wallet Ledger (Task T-022)

**Governing Rules:** TD-005 (Internal Wallet & Double-Entry Ledger), BR-004 (Wallet Refund Policy), ARCH-001 (Thin Views & Service Discipline)  
**Status:** Implemented in `apps/wallets/` (Models + Services + Admin; no public API in this task).  
**Migration:** `apps/wallets/migrations/0001_initial.py` (**FLAGGED PENDING HUMAN REVIEW** per AGENTS.md).

### 6.1 Data Models & Constraints
1. **`Wallet` (`apps/wallets/models.py`):**
   - `user`: OneToOneField to `settings.AUTH_USER_MODEL` (`related_name="wallet"`).
   - `balance_toman`: `BigIntegerField(default=0)`.
   - `CheckConstraint(balance_toman >= 0)`: Database-level invariant that wallet balance can never go negative.
   - Lazily created via service function (`get_or_create_wallet_for_user`).
2. **`WalletTransaction` (`apps/wallets/models.py`):**
   - One-sided append-only audited ledger entry.
   - `type`: Choices `CREDIT` (deposit) or `DEBIT` (spending).
   - `amount_toman`: `BigIntegerField` with `CheckConstraint(amount_toman > 0)`.
   - `balance_after_toman`: `BigIntegerField` snapshot immediately after transaction, with `CheckConstraint(balance_after_toman >= 0)`.
   - `idempotency_key`: `CharField(max_length=100, unique=True, db_index=True)` preventing duplicate mutations (UF-003).
   - Traceability: Nullable FKs to `Booking` (`SET_NULL`) and `PaymentTransaction` (`SET_NULL`).
   - Append-Only Immutability: Model overrides `save()` and `delete()` to raise `PermissionDenied` on any attempt to update or delete existing ledger rows.

### 6.2 Service Layer Contract (`apps/wallets/services.py`)
All mutations go exclusively through the service layer inside `transaction.atomic()` with exclusive row-level locking via `select_for_update()`:
- `get_or_create_wallet_for_user(user) -> Wallet`: Idempotent lazy wallet creation.
- `credit_wallet(wallet, amount_toman, *, reason, idempotency_key, booking=None, payment_transaction=None) -> WalletTransaction`:
  * Validates `amount_toman > 0` (raises `InvalidWalletAmountError`).
  * Idempotent replay: returns existing transaction on duplicate `idempotency_key`.
  * Increments balance under `select_for_update()` and writes immutable ledger entry.
- `debit_wallet(wallet, amount_toman, *, reason, idempotency_key, booking=None, payment_transaction=None) -> WalletTransaction`:
  * Validates `amount_toman > 0` (raises `InvalidWalletAmountError`).
  * Idempotent replay: returns existing transaction on duplicate `idempotency_key`.
  * Insufficient balance guard: if debit > current balance, raises `InsufficientWalletBalanceError` with zero side effects (balance and ledger untouched).
  * Decrements balance under `select_for_update()` and writes immutable ledger entry.
- Read helpers: `get_wallet_balance` and `list_wallet_transactions` (bounded, paginated via `core.pagination`).

### 6.3 Closed-Loop Invariant & Boundary Rules
- **No Cash-Out / Withdrawal (BR-004 / TD-005):** Wallet funds are strictly closed-loop and can only be used for future platform reservations. Zero cash-out endpoints, functions, or admin actions exist.
- **ADR-006 Late Callback Separation:** Involuntary late-payment conflicts (`refund_required = True`) are refunded strictly to the customer's bank card and are never credited to the wallet.
- **Admin Audit View:** Registered in `apps/wallets/admin.py` with read-only permissions (`has_add_permission=False`, `has_delete_permission=False`, `has_change_permission=False`).

---

## 7. Cancellation & Wallet Refund Credit (Task T-023)

**Governing Rules:** BR-004 (Wallet Refund Policy), TD-005 (Internal Wallet), ADR-006 (Late Payment Callback Policy)  
**Status:** Implemented in `apps/bookings/services.py`, `apps/bookings/api.py`, and `apps/bookings/schemas.py`.

### 7.1 Policy & 36-Hour Threshold (BR-004)
- **Eligibility:** Voluntary customer cancellation on `CONFIRMED` bookings at least 36 hours prior to the reservation start time (`start_at - now >= 36 hours`).
- **Refund Amount:** Exactly 100% of the online platform reservation fee (`booking.amount_online_toman`).
- **In-Person Add-Ons:** `amount_in_person_toman` (design items/amenities) are payable at the venue in person; they are never charged online and never refunded to the wallet.
- **Closed-Loop Destination:** Credited directly to the customer's in-app wallet via `credit_wallet()` with `idempotency_key = f"cancel-refund-{booking.id}"`. Wallet funds can only be applied to future bookings (zero cash-out / bank payout).
- **Atomic Execution:** The `Booking` row is locked via `select_for_update()`; status transition (`CONFIRMED -> CANCELLED`) and wallet balance credit execute in a single database transaction (`transaction.atomic()`).

### 7.2 Decision Table

| Current Status | Condition | Outcome Status | Wallet Credit | Result / HTTP Error |
|---|---|---|---|---|
| `CONFIRMED` | $\ge 36\text{h}$ ahead | `CANCELLED` | 100% `amount_online_toman` | HTTP 200, `refunded_to_wallet_toman = amount` |
| `CONFIRMED` | $< 36\text{h}$ ahead | `CONFIRMED` (unchanged) | 0 Toman | HTTP 400 (`CancellationWindowClosedError`, code `CANCELLATION_WINDOW_CLOSED`) |
| `PENDING_PAYMENT` | Any time | `CANCELLED` | 0 Toman | HTTP 200, slot hold released immediately |
| `CANCELLED` | Any time | `CANCELLED` (idempotent) | 0 Toman | HTTP 200, `refunded_to_wallet_toman = 0` |
| `INITIATED`, `EXPIRED`, `COMPLETED` | Any time | Unchanged | 0 Toman | HTTP 409 (`BookingNotCancellableError`, code `BOOKING_NOT_CANCELLABLE`) |

### 7.3 Separation from ADR-006 Involuntary Late Conflicts
- An `EXPIRED` booking with an associated `PaymentTransaction(refund_required=True)` represents an involuntary late payment conflict (slot taken by another user).
- Per ADR-006, involuntary conflicts must be refunded to the customer's **bank card** (via banking settlement), NEVER to the in-app wallet.
- Attempting to cancel an `EXPIRED` booking via `cancel_booking` or `POST /api/v1/bookings/{id}/cancel/` raises `BookingNotCancellableError` (HTTP 409), ensuring late-conflict transactions are never converted to wallet credits.

### 7.4 API Endpoint
- **URL:** `POST /api/v1/bookings/{booking_id}/cancel/` (and `/cancel`, trailing-slash tolerant).
- **Authentication:** `auth=auth` (Django session cookie + CSRF per TD-006). Only the customer who owns the booking may cancel (HTTP 403 `PermissionDenied` otherwise).
- **Response Schema:** `BookingCancelOut(booking_id, status, refunded_to_wallet_toman, wallet_balance_toman)`.
- **Occupancy Impact:** Once cancelled, `is_table_slot_occupied` immediately excludes the booking, releasing the slot for other customers without delay.

---

## 8. Split Receipt (Task T-024)

**Governing Rules:** BR-003 (Platform Fee Split: 100% online platform reservation fee, in-person design items payable at venue), ARCH-005 (Split Receipt), ARCH-001 (Thin Views), ARCH-006 (UTC Instants + Jalali Presentation)  
**Status:** Implemented in `apps/bookings/services.py`, `apps/bookings/schemas.py`, `apps/bookings/api.py`, and `core/exceptions.py`.

### 8.1 Pure-Read Contract & Two-Section Structure
A split receipt is a **read-only, structured JSON document** for ONE booking. It performs zero writes, zero payments, zero settlements, and zero wallet interactions.

1. **Header:**
   - `booking_id`, `status`, `venue_name`, `venue_slug`, `table_number`
   - Aware UTC instants: `start_at`, `end_at` (ARCH-006)
   - Local convenience fields: `slot_date`, `slot_start_time`
   - Jalali presentation helpers: `jalali_date`, `jalali_start_datetime`, `jalali_end_datetime`
2. **Section 1 — `paid_online` (100% Platform Share):**
   - Single line for the table reservation fee (`amount_online_toman`), labelled as paid online / 100% platform share.
   - Safe payment display from the booking's `SUCCESS` `PaymentTransaction` (if one exists and stores them):
     - `provider_name` (nullable string)
     - `card_pan_masked` (nullable masked PAN, e.g. `603799******1234`)
   - **Never exposed:** raw gateway payloads, full card PAN, `provider_reference`, `redirect_url`, `tracking_code`, `idempotency_key`, or `error_message`.
3. **Section 2 — `payable_in_person` (Venue Design Add-Ons):**
   - Labelled as payable in person at the venue.
   - Itemised list (`items`) built from `BookingAddon` price snapshots (`addon_id`, `title`, `unit_fee_toman`, `line_total_toman`). Raising `DesignAddon.fee` after booking never alters the receipt.
   - Section total `total_in_person_toman` (0 with `items: []` when no add-ons were selected).
4. **Totals (all integer Toman, `_toman` suffix):**
   - `total_online_toman`
   - `total_in_person_toman`
   - `grand_total_toman = total_online_toman + total_in_person_toman`

### 8.2 Availability Rule
- A receipt exists **only** for bookings whose online fee was settled: `CONFIRMED` or `COMPLETED`.
- Any other status (`INITIATED`, `PENDING_PAYMENT`, `EXPIRED`, `CANCELLED`) raises `ReceiptNotAvailableError` (`error_code="RECEIPT_NOT_AVAILABLE"`, HTTP 409). Cancelled booking refunds are audited in the wallet ledger, not on a receipt.

### 8.3 Consistency Rule
- `total_in_person_toman` is computed from the `BookingAddon.price_snapshot_toman` lines and asserted equal to `booking.amount_in_person_toman`.
- If they ever disagree (e.g., corrupted stored total), `get_split_receipt` raises `ReceiptDataInconsistencyError` (`error_code="RECEIPT_DATA_INCONSISTENCY"`, HTTP 500) rather than silently returning conflicting totals.

### 8.4 API Endpoint & Performance
- **URL:** `GET /api/v1/bookings/{booking_id}/receipt/` (and `/receipt`, trailing-slash tolerant).
- **Authentication & Ownership:** `auth=auth`. Strictly the booking's own customer only (unauthenticated $\to$ 401; foreign customer, venue owner, or admin $\to$ 403; unknown booking $\to$ 404).
- **Response Schema:** `SplitReceiptOut` (with `extra="forbid"` on root and all nested schemas).
- **Bounded Query Performance:** Executed in 3 constant SQL queries (`Booking+Venue+TablePin`, `BookingAddon+DesignAddon`, and `SUCCESS` `PaymentTransaction` safe columns via `.only()`), guaranteeing zero N+1 queries.
- **Migrations:** Zero schema changes and zero migrations.

---

## 9. Payment Initiate Endpoint & Dev-Only Sandbox Page (Task T-028-PRE)

- **Endpoint:** `POST /api/v1/billing/initiate/` (and `/initiate`, `auth=auth` via Django session cookie + CSRF per TD-006, `CUSTOMER` role only).
- **Input (`PaymentInitiateIn`, `extra="forbid"`):** `{ booking_id, idempotency_key, callback_url }`. Amount is always derived server-side from `booking.amount_online_toman`.
- **Output (`201 PaymentInitiateOut`):** `{ transaction_id, booking_id, amount_toman, currency, status, provider_name, provider_reference, redirect_url }`.
- **Errors:** `401` unauthenticated, `403` non-owner or non-customer, `404` unknown booking, `400 INVALID_STATUS_TRANSITION` for non-payable status or expired lock, `422` validation / extra fields.
- **Settings Override (`SANDBOX_BASE_URL`):**
  - `config/settings/base.py` defaults `SANDBOX_BASE_URL` to `https://sandbox.mizban.local` (production never selects the sandbox adapter).
  - `config/settings/development.py` sets `SANDBOX_BASE_URL` to `http://127.0.0.1:8001` so `SandboxGatewayAdapter.initiate()` redirects to `http://127.0.0.1:8001/billing/sandbox/pay/{authority}/?callback_url=...`.
- **Dev-Only Sandbox Page (`GET /billing/sandbox/pay/{authority}/`):**
  - Gated strictly on `settings.DEBUG` (returns `404` whenever `DEBUG=False`).
  - Refuses to render (`404`) for unknown/expired/non-pending authorities or any non-sandbox provider.
  - Displays Persian UI («صفحه‌ی آزمایشی درگاه — فقط محیط توسعه») with booking id, Toman amount, and «پرداخت موفق (تست)» / «پرداخت ناموفق (تست)» actions that submit through `GET /api/v1/billing/callback/` and redirect back to `callback_url` in `DEBUG=True`.




