# Tasks 013 - Hygiene Follow-Ups (T-042)
Rules: one owner per task, max ~400 changed lines, tests named up front,
no two parallel tasks edit the same file, zero migrations.

| ID | Task | Owner | Depends on | Files (max) | Tests | DoD |
|----|------|-------|------------|-------------|-------|-----|
| **T-042-01** | Spec & Plan for T-042 hygiene follow-ups | `requirements-analyst` / `planner` | None | `specs/013-hygiene-followups/spec.md`, `specs/013-hygiene-followups/tasks.md` | N/A (spec + Gherkin criteria) | Spec follows `000-template`; all 10 scope items, gateway payload change notice, `core/observability.py:34` justification, and explicit out-of-scope list documented. |
| **T-042-02** | Harden venue schemas & add-on fee bounds | `platform-engineer` | T-042-01 | `apps/venues/schemas.py`, `apps/venues/services.py` | `apps/venues/tests/test_owner_addons.py`, `apps/venues/tests/test_owner_api.py` | `_DesignAddonInBase.fee` uses `StrictInt` + `Field(ge=0, le=9_223_372_036_854_775_807)`; `_validate_addon_fields` enforces `fee <= 9_223_372_036_854_775_807`; `VenueCreateIn` & `VenueUpdateIn` declare `model_config = ConfigDict(extra="forbid")`. |
| **T-042-03** | Add `extra="forbid"` to `TablePinCreateIn` & `TablePinUpdateIn` | `media-engineer` | T-042-01 | `apps/panoramas/schemas.py` | `apps/panoramas/tests/test_table_pins_api.py` | `TablePinCreateIn` and `TablePinUpdateIn` declare `model_config = ConfigDict(extra="forbid")`; unknown fields rejected with 422. |
| **T-042-04** | Fix stale `phone_number` in wallets admin & billing payment | `finance-engineer` | T-042-01 | `apps/wallets/admin.py`, `apps/billing/services/payment.py` | `apps/billing/tests/test_billing_initiate_and_sandbox.py`, `apps/wallets/tests/test_wallet_ledger.py` | `WalletAdmin` & `WalletTransactionAdmin` use `user__phone` / `wallet__user__phone`; `initiate_payment` passes `booking.customer.phone` to `PaymentInitiateRequest.customer_phone`; gateway payload change (`""` -> normalized phone) verified by test. |
| **T-042-05** | Fix `send_default_pii` `DeprecationWarning` in observability | `backend-api-engineer` | T-042-01 | `core/observability.py` | `apps/accounts/tests/test_observability_t031.py` | `init_sentry` resolves `send_default_pii` `DeprecationWarning` without suppressing warnings; `client.options["send_default_pii"] is False` and `"phone_number"` in `_SENSITIVE_KEYS` preserved. |
| **T-042-06** | Configure `CSRF_TRUSTED_ORIGINS` from env | `devops-engineer` | T-042-01 | `config/settings/base.py`, `.env.example` | `apps/accounts/tests/test_security_audit_t030.py` | `CSRF_TRUSTED_ORIGINS` parsed as comma-separated list defaulting to `[]` in `config/settings/base.py`; documented in `.env.example`. |
| **T-042-07** | Add reviewer-nit, schema-hardening, & reachable coverage tests | `test-engineer` | T-042-02, T-042-03, T-042-04, T-042-05, T-042-06 | `apps/venues/tests/test_owner_addons.py`, `apps/venues/tests/test_venue_review.py`, `apps/venues/tests/test_owner_api.py`, `apps/panoramas/tests/test_table_pins_api.py`, `apps/billing/tests/test_billing_initiate_and_sandbox.py`, `apps/bookings/tests/test_booking_auto_complete.py` | Same files | T-035 nits (title > 200, `StrictInt`/max `fee`, pre-warmed cache invalidation on DELETE, 401s); T-036 nits (`VenueRejectIn` `extra="forbid"`, 401s on `/submit`/`/approve`/`/reject`, cache invalidation on `/submit`/`/reject`); T-030 `extra="forbid"` & `phone` tests; reachable uncovered lines in T-034/T-035/T-036 touched files covered. |
| **T-042-08** | Annotate 8 `[annotation-unchecked]` mypy test helpers | `test-engineer` | T-042-01 | `apps/accounts/tests/test_observability_t031.py`, `apps/bookings/tests/test_concurrency_spike.py`, `apps/billing/tests/test_wallet_payment.py` *(if applicable)* | `mypy .` + `pytest` on modified test files | All 8 `[annotation-unchecked]` helpers (`test_observability_t031.py:28`, `test_concurrency_spike.py:147-150,260-261,397`) and any in `test_wallet_payment.py` annotated; `mypy .` emits 0 `[annotation-unchecked]` notes in these files. |
| **T-042-09** | Dependency audit ONLY (`pip-audit` + `npm audit`) | `security-engineer` | T-042-01 | `docs/security/t042-dependency-audit.md` | `pip-audit` (in `.venv` only), `npm audit` (in `frontend/`) | `pip-audit` installed in `.venv` only (`requirements*.txt` untouched); `pip-audit` and `frontend/ npm audit` outputs recorded in `docs/security/t042-dependency-audit.md`; zero dependencies upgraded. |
| **T-042-10** | Review, full verification & OpenAPI snapshot update | `code-reviewer` + `web-architect` *(+ human gate for `api/openapi.snapshot.json`)* | T-042-07, T-042-08, T-042-09 | `api/openapi.snapshot.json` *(protected path — human gate)* | `manage.py check`, `ruff check .`, `mypy .`, `pytest`, `./check-contract.sh` | Code Reviewer approves; `api/openapi.snapshot.json` updated for schema changes (`StrictInt`/max `fee`, `extra="forbid"`) and `./check-contract.sh` passes; all checks green with 0 warnings/failures/skips. |

## Parallel groups
- **Group A (Spec & Plan):** `T-042-01`
- **Group B1 (Disjoint Code, Config, Typing & Audit):**
  - `T-042-02` (`platform-engineer`: `apps/venues/schemas.py`, `apps/venues/services.py`)
  - `T-042-03` (`media-engineer`: `apps/panoramas/schemas.py`)
  - `T-042-04` (`finance-engineer`: `apps/wallets/admin.py`, `apps/billing/services/payment.py`)
  - `T-042-05` (`backend-api-engineer`: `core/observability.py`)
  - `T-042-06` (`devops-engineer`: `config/settings/base.py`, `.env.example`)
  - `T-042-08` (`test-engineer`: `test_observability_t031.py`, `test_concurrency_spike.py`, `test_wallet_payment.py`)
  - `T-042-09` (`security-engineer`: `docs/security/t042-dependency-audit.md`)
  *(All 7 tasks in Group B1 touch strictly disjoint files.)*
- **Group B2 (Tests & Coverage):** `T-042-07` (`test-engineer` — runs after B1 code changes land; disjoint from `T-042-08` files)
- **Group C (Review & Protected-Path Contract Update):** `T-042-10`

## Estimates
| Task | Estimated Diff | Estimated Tokens | Estimated Cost | Estimated Elapsed |
|------|----------------|------------------|----------------|-------------------|
| T-042-01 | ~170 lines (docs) | ~10k | ~$0.05 | ~5 min |
| T-042-02 | ~20 lines | ~5k | ~$0.03 | ~3 min |
| T-042-03 | ~10 lines | ~4k | ~$0.02 | ~2 min |
| T-042-04 | ~10 lines | ~5k | ~$0.03 | ~3 min |
| T-042-05 | ~15 lines | ~6k | ~$0.03 | ~4 min |
| T-042-06 | ~10 lines | ~4k | ~$0.02 | ~2 min |
| T-042-07 | ~180–240 lines | ~18k | ~$0.10 | ~10 min |
| T-042-08 | ~20 lines | ~6k | ~$0.03 | ~3 min |
| T-042-09 | ~60 lines (audit doc) | ~8k | ~$0.04 | ~4 min |
| T-042-10 | ~40 lines (`openapi.snapshot.json`) + review | ~12k | ~$0.07 | ~6 min |
| **Feature Total** | **~300–370 code+test lines (~230 docs)** | **~78k** | **~$0.42** | **~42 min** |
