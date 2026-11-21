# Spec 005 — Payment Gateway Adapter & PaymentTransaction Schema

**Feature:** 005 — Billing & Payment Processing  
**Status:** In Progress (Task T-020 Completed)  
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

### 5.2 Mandatory Bank Card Refund Policy

When `refund_required = True` (Cases C and D), the refund **must return to the customer's original bank card/account**, never to the in-app wallet. The in-app wallet under BR-004 and TD-005 is strictly reserved for voluntary customer cancellations initiated at least 36 hours before slot time. In this Sandbox phase, `refund_required = True` is recorded as an auditable flag on `PaymentTransaction`.

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


