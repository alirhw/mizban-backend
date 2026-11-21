# Tasks: Phase PH-05 — Billing & Payment Processing (WS-BILLING-WALLET)

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
- [ ] **T-022 — Implement Internal Wallet Ledger Schema (ADR-004)**
- [ ] **T-023 — Implement Wallet Refund and Credit Logic (BR-004)**
- [ ] **T-024 — Split Receipt Generation (BR-003)**
