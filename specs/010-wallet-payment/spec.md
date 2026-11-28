# Spec 010 - Pay for a Booking with In-App Wallet (FR-17)
Status: Approved for build | Lane: Full (money + bookings/wallets) | Implements: FR-17, BR-003, BR-004 | Architecture: ARCH-001, ARCH-002, ARCH-005, ARCH-006, TD-005

## 1. Problem and goal
Customers who hold funds in their non-withdrawable in-app wallet (e.g., from prior reservation cancellations under **BR-004**) need to pay a booking's online table reservation fee directly from their wallet without going through an external payment gateway. This spec defines the atomic, idempotent, lock-ordered wallet payment service and API endpoint (`POST /api/v1/billing/wallet-pay/`) that debits the customer's wallet and confirms the reservation in one PostgreSQL transaction.

## 2. User stories
- **US-01** As a customer with sufficient in-app wallet balance, I want to pay the online table reservation fee for my `PENDING_PAYMENT` booking using my wallet, so that my booking is confirmed immediately without external gateway redirection.
- **US-02** As the platform system, I want wallet payments to enforce strict row-lock ordering, single-transaction atomicity, server-side fee calculation (table fee only per **BR-003**), and idempotency, so that concurrent requests never double-debit a wallet, over-confirm a booking, or leave partial side effects on failure.

## 3. Requirements (EARS)
- **REQ-WPAY-001** The system shall provide a domain service `pay_booking_with_wallet(*, user, booking_id, idempotency_key) -> PaymentTransaction` in `apps/billing/services/payment.py` (**ARCH-001**).
- **REQ-WPAY-002** **Idempotency fast-path & replay:** When `pay_booking_with_wallet` is called with an `idempotency_key` that already exists on a `PaymentTransaction`, the system shall return the existing `PaymentTransaction` without re-debiting the wallet or mutating booking state; if the booking is already `CONFIRMED` and a *different* `idempotency_key` is supplied, the system shall reject the request with `InvalidStatusTransitionError` (`400 INVALID_STATUS_TRANSITION`).
- **REQ-WPAY-003** **Single atomic transaction & lock order (ARCH-002 / TD-005):** `pay_booking_with_wallet` shall execute inside a single `transaction.atomic()` block and acquire row locks in the exact order:
  1. **Booking row first** via `Booking.objects.select_for_update()`.
  2. **Wallet row second** via `apps/wallets/services.py:debit_wallet` (which acquires `Wallet.objects.select_for_update()`).
- **REQ-WPAY-004** **Validation order:** Inside `transaction.atomic()` (after checking role or before acquiring locks for role), `pay_booking_with_wallet` shall validate in the following exact order:
  1. **Role check:** `user` must have `CUSTOMER` role (`UserRole.CUSTOMER`); otherwise raise `PermissionDenied` (`403`).
  2. **Booking existence:** `Booking` with `pk=booking_id` must exist; otherwise raise `Http404` (`404`).
  3. **Booking ownership:** `booking.customer_id == user.id` must hold; otherwise raise `PermissionDenied` (`403`).
  4. **Booking status:** `booking.status` must be strictly `BookingStatus.PENDING_PAYMENT` (`INITIATED` is not accepted; `CONFIRMED`, `CANCELLED`, `EXPIRED`, `COMPLETED`, and `INITIATED` shall raise `InvalidStatusTransitionError`, `400 INVALID_STATUS_TRANSITION`).
  5. **Unexpired lock:** `booking.lock_expires_at` must be strictly greater than `now` (`timezone.now()` in aware UTC, **ARCH-006**); if `booking.lock_expires_at is None` or `booking.lock_expires_at <= now`, raise `InvalidStatusTransitionError` (`400 INVALID_STATUS_TRANSITION`).
  6. **Server-side amount (BR-003 / ARCH-005):** `amount_toman = booking.amount_online_toman` must be strictly greater than `0` (integer Toman, table fee only; design add-ons in `amount_in_person_toman` are never charged to the wallet); otherwise raise `InvalidWalletAmountError` (`400 INVALID_WALLET_AMOUNT`).
- **REQ-WPAY-005** **Wallet debit before PaymentTransaction:** `pay_booking_with_wallet` shall call `debit_wallet` (from `apps/wallets/services.py`) *before* creating the `PaymentTransaction` row, passing:
  - `wallet`: `get_or_create_wallet_for_user(user)`
  - `amount_toman`: `booking.amount_online_toman`
  - `idempotency_key`: `f"booking-pay:{booking_id}"`
  - `reason`: `f"booking-pay:{booking_id}"`
  - `booking`: `booking`
  If the wallet balance is less than `amount_toman`, `debit_wallet` shall raise `InsufficientWalletBalanceError` (`400 WALLET_INSUFFICIENT_BALANCE`), rolling back the transaction with zero side effects (no wallet balance change, no `WalletTransaction`, no `PaymentTransaction`, booking remains `PENDING_PAYMENT`).
- **REQ-WPAY-006** **PaymentTransaction creation & state transitions:** Immediately after `debit_wallet` succeeds inside the same `transaction.atomic()`, `pay_booking_with_wallet` shall create one `PaymentTransaction` with:
  - `booking=booking`, `customer=booking.customer`
  - `amount_toman=booking.amount_online_toman`, `currency="TOMAN"`
  - `provider_name="wallet"`, `provider_reference=None`, `tracking_code=""`, `card_pan_masked=""`
  - `idempotency_key=idempotency_key` (the client-provided key)
  And shall transition the `PaymentTransaction` strictly through `INITIATED -> PENDING -> SUCCESS` with `verified_at=now` (aware UTC, **ARCH-006**).
- **REQ-WPAY-007** **Booking confirmation:** Inside the same `transaction.atomic()`, `pay_booking_with_wallet` shall transition the booking to confirmed via `booking.transition_to(BookingStatus.CONFIRMED)`.
- **REQ-WPAY-008** **API endpoint & schemas:** `apps/billing/api.py` shall expose:
  - `POST /api/v1/billing/wallet-pay/` (and trailing-slash alias `POST /api/v1/billing/wallet-pay` with `include_in_schema=False`)
  - Auth: `auth=auth`, restricted to `CUSTOMER` role (`403` for non-customers)
  - Request schema `WalletPayIn` in `apps/billing/schemas.py` (`ConfigDict(extra="forbid")`, `booking_id: int`, `idempotency_key: str` with `max_length=100`)
  - Response: `200 PaymentTransactionOut` (existing schema in `apps/billing/schemas.py`).
  - The Ninja view shall only authenticate, validate the schema, and delegate to `pay_booking_with_wallet` (**ARCH-001**).
- **REQ-WPAY-009** **Zero PII in logs:** Structured logs emitted by `pay_booking_with_wallet` and the wallet-pay endpoint shall record only `booking_id`, `tx_id`, and `amount_toman` — never phone numbers, OTP codes, tokens, email addresses, or secrets.
- **REQ-WPAY-010** **Read-model visibility:** A booking paid via wallet shall immediately be visible as `CONFIRMED` in `GET /api/v1/bookings/my/`, its split receipt shall be accessible at `GET /api/v1/bookings/{booking_id}/receipt/` (showing online table fee paid and design add-ons payable in person per **BR-003**), and the corresponding `DEBIT` ledger entry shall be visible in `GET /api/v1/wallets/me/`.
- **REQ-WPAY-011** **Frontend follow-up note:** The frontend payment-method choice UI in `frontend/` is a separate follow-up task and is not part of **T-034**.

## 4. Business rules touched
- **FR-17** — Pay for a table reservation using the customer's in-app wallet balance.
- **BR-003 / ARCH-005** — Online payment (including wallet payment) covers the table reservation fee (`amount_online_toman`) only; design add-on costs remain payable to the venue in person and appear on the split receipt.
- **BR-004 / TD-005** — Wallet is a closed-loop, non-withdrawable, audited ledger (`select_for_update()` + DB non-negative balance `CheckConstraint`); debits are integer Toman only and atomic.
- **ARCH-001** — Ninja view delegates exclusively to `apps/billing/services/payment.py`.
- **ARCH-002** — All state mutations occur inside `transaction.atomic()` with `select_for_update()` (booking row locked first, then wallet row).
- **ARCH-006** — All timestamps (`lock_expires_at` comparison, `verified_at`) use aware UTC (`timezone.now()`).

## 5. Non-functional targets
- **Atomicity & concurrency:** Tested on PostgreSQL 16; concurrent wallet-pay calls on the same booking serialize on `Booking` row lock with zero double-debits, zero deadlocks, and exactly one `CONFIRMED` transition.
- **Data integrity:** Zero negative wallet balances; zero orphaned `WalletTransaction` or `PaymentTransaction` rows on failure.
- **Privacy:** Zero PII in logs.
- **Quality & contract:** `manage.py check`, `pytest` (PostgreSQL), and `./check-contract.sh` (with updated `api/openapi.snapshot.json` reviewed under protected-path gate) pass cleanly; zero database migrations.

## 6. Acceptance criteria (Gherkin)

```gherkin
Scenario: 1. Happy path — customer pays PENDING_PAYMENT booking with sufficient wallet balance
  Given a CUSTOMER with wallet balance 200000 Toman
    And a PENDING_PAYMENT Booking owned by that customer with amount_online_toman = 150000 and lock_expires_at = now + 5 minutes
  When the customer calls POST /api/v1/billing/wallet-pay/ with booking_id and idempotency_key "wpay-1"
  Then HTTP 200 is returned with PaymentTransactionOut (provider_name="wallet", status="SUCCESS", amount_toman=150000, provider_reference=null, tracking_code="", card_pan_masked="", verified_at != null)
    And the wallet balance in PostgreSQL is 50000 Toman
    And one WalletTransaction(DEBIT, amount_toman=150000, reason="booking-pay:<booking_id>", idempotency_key="booking-pay:<booking_id>", booking=booking) exists
    And the Booking status in PostgreSQL is CONFIRMED.

Scenario: 2. Table fee only — design add-ons are not debited from wallet (BR-003 / ARCH-005)
  Given a CUSTOMER with wallet balance 300000 Toman
    And a PENDING_PAYMENT Booking with amount_online_toman = 100000 (table fee) and amount_in_person_toman = 250000 (design add-ons)
  When the customer pays with wallet
  Then the wallet is debited exactly 100000 Toman (remaining balance 200000 Toman)
    And PaymentTransaction.amount_toman equals 100000
    And GET /api/v1/bookings/<booking_id>/receipt/ shows online_total_toman = 100000 and in_person_total_toman = 250000.

Scenario: 3. Insufficient wallet balance — rejected with zero side effects
  Given a CUSTOMER with wallet balance 90000 Toman
    And a PENDING_PAYMENT Booking with amount_online_toman = 100000 and lock_expires_at = now + 5 minutes
  When the customer calls POST /api/v1/billing/wallet-pay/
  Then HTTP 400 is returned with error_code "WALLET_INSUFFICIENT_BALANCE"
    And the wallet balance remains 90000 Toman
    And 0 WalletTransaction rows are created
    And 0 PaymentTransaction rows are created
    And the Booking status remains PENDING_PAYMENT.

Scenario: 4. Non-CUSTOMER role rejected with 403
  Given an authenticated VENUE_OWNER (or ADMIN) user
  When they call POST /api/v1/billing/wallet-pay/
  Then HTTP 403 is returned
    And zero wallet or booking mutations occur.

Scenario: 5. Non-existent booking rejected with 404
  Given an authenticated CUSTOMER user
  When they call POST /api/v1/billing/wallet-pay/ for booking_id = 999999
  Then HTTP 404 is returned
    And zero wallet mutations occur.

Scenario: 6. Non-owner customer rejected with 403
  Given Customer A owns a PENDING_PAYMENT Booking
    And Customer B is another authenticated CUSTOMER with sufficient wallet balance
  When Customer B calls POST /api/v1/billing/wallet-pay/ for Customer A's booking_id
  Then HTTP 403 is returned
    And Customer B's wallet balance is untouched
    And Customer A's Booking remains PENDING_PAYMENT.

Scenario: 7. Invalid booking status rejected with 400 INVALID_STATUS_TRANSITION
  Given a Booking owned by the customer in status INITIATED, CONFIRMED, CANCELLED, EXPIRED, or COMPLETED
  When the customer calls POST /api/v1/billing/wallet-pay/ with a fresh idempotency_key
  Then HTTP 400 is returned with error_code "INVALID_STATUS_TRANSITION"
    And the wallet balance is untouched.

Scenario: 8. Expired booking lock rejected with 400 INVALID_STATUS_TRANSITION
  Given a PENDING_PAYMENT Booking owned by the customer with lock_expires_at = now - 1 second
  When the customer calls POST /api/v1/billing/wallet-pay/
  Then HTTP 400 is returned with error_code "INVALID_STATUS_TRANSITION"
    And the wallet balance is untouched
    And 0 PaymentTransaction rows are created.

Scenario: 9. Idempotent replay with same idempotency_key returns existing PaymentTransaction
  Given a customer successfully paid for a Booking with idempotency_key "wpay-idem-1"
  When the customer calls POST /api/v1/billing/wallet-pay/ again with the same idempotency_key "wpay-idem-1"
  Then HTTP 200 is returned with the same PaymentTransaction id
    And the wallet is NOT debited a second time
    And no duplicate WalletTransaction or PaymentTransaction rows are created.

Scenario: 10. Different idempotency_key on already-CONFIRMED booking is rejected
  Given a customer successfully paid for a Booking with idempotency_key "wpay-idem-1" (Booking is now CONFIRMED)
  When the customer calls POST /api/v1/billing/wallet-pay/ with a different idempotency_key "wpay-idem-2"
  Then HTTP 400 is returned with error_code "INVALID_STATUS_TRANSITION"
    And the wallet is NOT debited a second time.

Scenario: 11. Concurrent double-pay race on PostgreSQL debits once
  Given a CUSTOMER with wallet balance 200000 Toman
    And a PENDING_PAYMENT Booking with amount_online_toman = 100000 and unexpired lock
  When two concurrent threads call pay_booking_with_wallet on the same booking_id with distinct idempotency keys
  Then exactly one thread succeeds and confirms the booking
    And the other thread fails with InvalidStatusTransitionError
    And the final wallet balance in PostgreSQL is exactly 100000 Toman.

Scenario: 12. Read-model visibility and zero PII in logs
  Given a customer successfully pays for a Booking via wallet
  When the customer queries GET /api/v1/bookings/my/, GET /api/v1/bookings/<booking_id>/receipt/, and GET /api/v1/wallets/me/
  Then the booking appears with status "CONFIRMED" in /bookings/my/
    And the receipt is returned with status 200
    And the wallet ledger includes the DEBIT entry for "booking-pay:<booking_id>"
    And emitted application logs contain booking_id, tx_id, and amount_toman with zero PII.
```

## 7. Out of scope (explicit)
- External payment gateway flow (`initiate_payment_for_booking`, `verify_payment_transaction`, `handle_payment_callback`)
- Booking cancellation or wallet refund flow (already implemented under **BR-004**)
- Database schema changes or migrations (`apps/billing/migrations/`, `apps/wallets/migrations/`, `apps/bookings/migrations/` remain untouched)
- Frontend payment-method choice UI in `frontend/` (deferred to a follow-up frontend task, not T-034)
- Signature or behavior changes to `initiate_payment_for_booking`, `debit_wallet`, or `credit_wallet`

## 8. Open questions
- None. All business rules (**FR-17**, **BR-003**, **BR-004**, **TD-005**) and architectural constraints (**ARCH-001**, **ARCH-002**, **ARCH-005**, **ARCH-006**) are resolved.

---

## 9. Frontend Payment Choice (`BookingFlow`) — Follow-up (a)

### 9.1 Scope & Existing Backend Contract
This section specifies the **T-034 Frontend Follow-up (a)** in `frontend/`, integrating `BookingFlow` (`frontend/src/components/BookingFlow.tsx`) with the existing wallet and wallet-pay backend endpoints (no backend or OpenAPI snapshot changes):
- **Wallet balance endpoint:** `GET /api/v1/wallets/me/` (`getMyWallet()` -> `WalletMeOut` `{ balance_toman, ... }`, already present in `frontend/src/lib/api.ts`).
- **Wallet payment endpoint:** `POST /api/v1/billing/wallet-pay/`:
  - Request body: `WalletPayIn` `{ booking_id: number, idempotency_key: string }`
  - Success response (`200`): `PaymentTransactionOut` `{ id, booking_id, amount_toman, currency, status, provider_name, provider_reference, tracking_code, card_pan_masked, created_at, verified_at }`
  - Insufficient balance error (`400`): `error_code: "WALLET_INSUFFICIENT_BALANCE"`

### 9.2 Frontend Requirements (EARS)
- **REQ-WPAY-FE-001** **Typed API client (`frontend/src/lib/api.ts`):** `frontend/src/lib/api.ts` shall define `WalletPayIn` and `PaymentTransactionOut` interfaces matching `api/openapi.snapshot.json` and export `payBookingWithWallet(payload: WalletPayIn): Promise<PaymentTransactionOut>` calling `POST /billing/wallet-pay/`.
- **REQ-WPAY-FE-002** **Wallet balance fetch on active lock:** When `BookingFlow` (`frontend/src/components/BookingFlow.tsx`) enters or is in an active lock payment step (`state.step === "locked"` or `state.step === "failed"`), the component shall fetch `getMyWallet()` to retrieve `balance_toman` and determine whether the Wallet payment option is enabled.
- **REQ-WPAY-FE-003** **Payment method presentation & ordering:** In the payment step (`locked` / `paying` / `failed`), `BookingFlow` shall present two payment options with **Wallet** shown **first** and **Online Gateway** shown **second**:
  1. **Wallet:** Displays the customer's current wallet balance (`balance_toman`). Enabled **only** when `getMyWallet()` succeeded and `balance_toman >= selectedPin.reservation_fee_toman` (table reservation fee only per **BR-003 / BR-04**; design add-ons remain payable in person).
     - If `balance_toman < selectedPin.reservation_fee_toman`, the Wallet option shall be disabled with a clear Persian insufficient-balance note.
     - If `getMyWallet()` fails, the Wallet option shall be disabled with a clear Persian unavailable note while keeping **Online Gateway** usable.
  2. **Online Gateway:** Uses the existing `initiatePayment` flow (`handleStartPayment`) and remains selectable whenever the lock has not expired.
- **REQ-WPAY-FE-004** **Wallet payment submission & immediate confirmation:** When the customer submits payment with **Wallet** selected:
  - `BookingFlow` shall call `payBookingWithWallet({ booking_id, idempotency_key })`.
  - On `200 PaymentTransactionOut`, `BookingFlow` shall transition immediately to `"confirmed"` (`PAYMENT_SUCCEEDED`) with **no** external redirect, and render confirmation details including tracking/receipt info (`PaymentTransactionOut` / booking summary) and a link to `/bookings`.
- **REQ-WPAY-FE-005** **Insufficient-balance error handling & fallback:** If `payBookingWithWallet` returns `400` with `WALLET_INSUFFICIENT_BALANCE`, `BookingFlow` shall display a user-friendly Persian error message (never exposing raw `error_code` strings) and automatically switch the selected payment method to **Online Gateway** so the customer can retry immediately.
- **REQ-WPAY-FE-006** **Control disabling during submission / expiry:** Both payment method options and the submit button shall be disabled whenever `submittingPayment` is `true`, `state.step === "paying"`, or `remainingSeconds <= 0`.
- **REQ-WPAY-FE-007** **Zero raw error codes or PII in UI:** User-facing error banners in `BookingFlow` shall render Persian copy only and never expose raw backend `error_code` identifiers or sensitive customer PII.

### 9.3 Frontend Acceptance Criteria (Gherkin)
```gherkin
Scenario: FE-1. Wallet option enabled first when wallet balance covers table reservation fee
  Given a customer is on the locked payment step in BookingFlow with selectedPin.reservation_fee_toman = 150000
    And GET /api/v1/wallets/me/ returns balance_toman = 200000
  Then Wallet is displayed first and Online Gateway second
    And Wallet shows balance 200000 Toman and is enabled.

Scenario: FE-2. Wallet option disabled with Persian note when balance is insufficient
  Given a customer is on the locked payment step with selectedPin.reservation_fee_toman = 150000
    And GET /api/v1/wallets/me/ returns balance_toman = 90000
  Then Wallet is disabled with a clear Persian insufficient-balance note
    And Online Gateway remains enabled and usable.

Scenario: FE-3. Wallet option disabled with Persian note when getMyWallet() fails
  Given a customer is on the locked payment step
    And GET /api/v1/wallets/me/ fails with a network or server error
  Then Wallet is disabled with a clear Persian unavailable note
    And Online Gateway remains enabled and usable.

Scenario: FE-4. Successful wallet payment confirms immediately without redirect
  Given Wallet is selected and enabled in BookingFlow
  When the customer submits payment and POST /api/v1/billing/wallet-pay/ returns 200 PaymentTransactionOut
  Then BookingFlow transitions immediately to "confirmed" with no redirect
    And displays confirmation and tracking/receipt details with a link to /bookings.

Scenario: FE-5. 400 WALLET_INSUFFICIENT_BALANCE shows Persian message and switches to Online Gateway
  Given Wallet is selected and the customer submits payment
  When POST /api/v1/billing/wallet-pay/ returns 400 with error_code "WALLET_INSUFFICIENT_BALANCE"
  Then BookingFlow displays a user-friendly Persian message without raw "WALLET_INSUFFICIENT_BALANCE"
    And automatically switches the selected payment option to Online Gateway.

Scenario: FE-6. Controls disabled during submission or lock expiry
  Given BookingFlow is in the payment step
  When submittingPayment is true, state.step === "paying", or remainingSeconds <= 0
  Then both Wallet and Online Gateway options and the submit button are disabled.
```

### 9.4 Frontend Out of Scope (explicit)
- Wallet top-up / deposit UI
- Gateway callback page (`frontend/src/app/bookings/callback/`) edits
- Lock countdown timer mechanics edits
- Admin or venue-owner UI edits
- Backend Python code, migrations, or `api/openapi.snapshot.json` edits

### 9.5 Component Test Infrastructure & Coverage (Follow-up (a) Part 2)
- **Vitest jsdom setup:** `frontend/vitest.config.ts` adds `src/**/*.test.tsx` while keeping `environment: "node"` as the default so existing lib tests stay on Node; `frontend/src/lib/__tests__/BookingFlow.test.tsx` uses `// @vitest-environment jsdom` with `@testing-library/react`, `@testing-library/jest-dom/vitest`, and `@testing-library/user-event` (`@/lib/api`, `next/navigation`, `next/link`, and `@/lib/auth` mocked).
- **Covered cases (`BookingFlow.test.tsx`):** Wallet-first / Gateway-second rendering, insufficient balance (`balance_toman < fee`) disabled note vs `balance_toman === fee` enabled, `getMyWallet()` load failure fallback to gateway, wallet payment 200 immediate `confirmed` state without redirect, `400 WALLET_INSUFFICIENT_BALANCE` Persian alert + auto-switch to gateway, unchanged gateway `initiatePayment` redirect, double-click in-flight guard, and lock countdown `00:00` disabling both options.
