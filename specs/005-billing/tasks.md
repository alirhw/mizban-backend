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
- [ ] **T-021 — Implement Payment Callback and Booking Confirmation Endpoint**
- [ ] **T-022 — Implement Internal Wallet Ledger Schema (ADR-004)**
- [ ] **T-023 — Implement Wallet Refund and Credit Logic (BR-004)**
- [ ] **T-024 — Split Receipt Generation (BR-003)**
