# Tasks 010 - Pay for a Booking with In-App Wallet (T-034 / FR-17)
Rules: one owner per task, max ~400 changed lines, tests named up front,
no two parallel tasks edit the same file, migrations for bookings/wallets
are flagged for human review (none for T-034).

| ID | Task | Owner | Depends on | Files (max) | Tests | DoD |
|----|------|-------|------------|-------------|-------|-----|
| **T-034-01** | Spec & Plan for in-app wallet booking payment (FR-17) | `requirements-analyst` / `planner` | None | `specs/010-wallet-payment/spec.md`, `specs/010-wallet-payment/tasks.md` | N/A (spec + Gherkin criteria) | Spec follows `000-template`; all EARS REQs, lock ordering, validation order, 12 Gherkin scenarios, out-of-scope list, and frontend follow-up note documented. |
| **T-034-02** | Wallet payment schema, service & endpoint | `finance-engineer` | T-034-01 | `apps/billing/schemas.py`, `apps/billing/services/payment.py`, `apps/billing/api.py` | Verified by `apps/billing/tests/test_wallet_payment.py` | `WalletPayIn` (`extra="forbid"`, `booking_id`, `idempotency_key` max 100); `pay_booking_with_wallet` in single `transaction.atomic()` locking booking first then wallet via `debit_wallet`, exact validation order, `PaymentTransaction` (`provider_name="wallet"`, `INITIATED -> PENDING -> SUCCESS`), `booking.transition_to(CONFIRMED)`, non-PII logs; `POST /api/v1/billing/wallet-pay/` + `/wallet-pay` alias (`CUSTOMER` only); zero migrations; <= 400 lines. |
| **T-034-03** | PostgreSQL test suite for wallet booking payment | `test-engineer` | T-034-01, T-034-02 | `apps/billing/tests/test_wallet_payment.py` | 12 tests in `apps/billing/tests/test_wallet_payment.py` | All 12 Gherkin scenarios (happy path, BR-003 table-fee-only, insufficient balance, 403 non-customer, 404 missing booking, 403 non-owner, invalid statuses incl. `INITIATED`, expired lock, idempotent replay, new key on `CONFIRMED`, PostgreSQL concurrent double-pay race, read-model visibility & zero PII logs) pass on PostgreSQL 16; 0 failed, 0 skipped. |
| **T-034-04** | Full-lane review & OpenAPI snapshot update | `code-reviewer` + `security-engineer` *(+ human gate for `api/openapi.snapshot.json`)* | T-034-02, T-034-03 | `api/openapi.snapshot.json` *(protected path — human gate)* | `manage.py check`, `pytest`, `./check-contract.sh` | Code Reviewer & Security Engineer approve Full-lane review; `api/openapi.snapshot.json` updated and `./check-contract.sh` passes cleanly. |

## Parallel groups
- **Group A (Spec & Plan):** `T-034-01`
- **Group B (Build & Tests — disjoint owned files):** `T-034-02` (`finance-engineer`: `apps/billing/schemas.py`, `apps/billing/services/payment.py`, `apps/billing/api.py`) and `T-034-03` (`test-engineer`: `apps/billing/tests/test_wallet_payment.py` — fail-first tests can be drafted in parallel, final verification runs after `T-034-02` lands)
- **Group C (Independent Review & Protected-Path Contract Update):** `T-034-04` (`code-reviewer` + `security-engineer` + human-gated `api/openapi.snapshot.json` update)

## Estimates
| Task | Estimated Diff | Estimated Tokens | Estimated Cost | Estimated Elapsed |
|------|----------------|------------------|----------------|-------------------|
| T-034-01 | ~170 lines (docs) | ~12k | ~$0.06 | ~5 min |
| T-034-02 | ~140–200 lines | ~18k | ~$0.10 | ~10 min |
| T-034-03 | ~280–360 lines | ~22k | ~$0.13 | ~12 min |
| T-034-04 | ~40 lines (`openapi.snapshot.json`) + review | ~14k | ~$0.08 | ~8 min |
| **Feature Total** | **~460–600 code+test lines (~170 spec)** | **~66k** | **~$0.37** | **~35 min** |
