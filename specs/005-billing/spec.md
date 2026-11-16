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
