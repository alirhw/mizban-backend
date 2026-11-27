# Spec 013 - Hygiene Follow-Ups (T-042: T-030 / T-031 / T-034 / T-035 / T-036)
Status: Draft (G1 Pending) | Owner: Platform / Security | Lane: Standard | Implements: T-030, T-031, T-034, T-035, T-036 Low/Info Hygiene Follow-Ups | Architecture: ARCH-001, ARCH-004, NFR-005

## 1. Problem and goal
Recent security, observability, and feature reviews (T-030, T-031, T-034, T-035, T-036) surfaced accepted Low and Info findings: unbounded and boolean-coercible add-on fees, missing `extra="forbid"` on venue and table-pin input schemas, stale `user.phone_number` attribute references, hardcoded/missing `CSRF_TRUSTED_ORIGINS` env configuration, a `sentry-sdk` `DeprecationWarning` on `send_default_pii`, 8 `[annotation-unchecked]` mypy test helpers, missing isolated reviewer-nit tests, reachable uncovered lines in T-034/T-035/T-036 files, and an unexecuted dependency audit. This spec defines the exact behavioral, validation, configuration, typing, test, and audit requirements to close all 10 items without migrations, dependency upgrades, or new runtime dependencies.

## 2. User stories
- **US-01** As a security reviewer, I want design add-on `fee` inputs to reject booleans (`true`/`false`) and values above PostgreSQL `BigIntegerField` max (`9_223_372_036_854_775_807`), and `VenueCreateIn`/`VenueUpdateIn`/`TablePinCreateIn`/`TablePinUpdateIn` to reject unknown fields, so that type coercion, integer overflow, and mass-assignment vectors are blocked at the API boundary.
- **US-02** As an admin or payment operator, I want `WalletAdmin`/`WalletTransactionAdmin` search and `initiate_payment` gateway requests to reference `User.phone` (not the nonexistent `phone_number` attribute), so that admin search does not raise `FieldError` and the payment gateway receives the customer's real normalized phone number.
- **US-03** As a DevOps operator, I want `CSRF_TRUSTED_ORIGINS` configurable via a comma-separated environment variable defaulting to `[]` and documented in `.env.example`, so that HTTPS deployments can configure trusted origins without code edits.
- **US-04** As a maintainer, I want zero `send_default_pii` `DeprecationWarning` noise in observability init, zero `[annotation-unchecked]` notes in targeted test helpers, full test coverage of T-035/T-036 reviewer nits and reachable T-034/T-035/T-036 lines, and a clean `pip-audit` + `npm audit` report without upgrading packages, so that the codebase baseline is clean and auditable.

## 3. Requirements (EARS)

### Schema & Service Input Hardening (T-035 / T-030)
- **REQ-HYG-001** **Add-on fee upper bound (T-035 Security Low):** When a caller submits a design add-on create or update payload (`_DesignAddonInBase` in `apps/venues/schemas.py:36`) or calls `_validate_addon_fields` (`apps/venues/services.py:552`) with `fee > 9_223_372_036_854_775_807` (PostgreSQL `BigIntegerField` maximum), the system shall reject the input with HTTP `422` (`VALIDATION_ERROR`) at the schema layer and `DjangoValidationError` at the service layer instead of raising a database `DataError`/500.
- **REQ-HYG-002** **Add-on fee rejects booleans (T-035 Security Low):** When a caller submits JSON boolean `true` or `false` for `fee` in `_DesignAddonInBase` (`apps/venues/schemas.py:36`), the system shall use Pydantic `StrictInt` so boolean values are rejected with HTTP `422` (`VALIDATION_ERROR`) rather than coerced to `1` or `0`.
- **REQ-HYG-003** **Strict input schemas (`extra="forbid"`, T-030 Low):** `VenueCreateIn` (`apps/venues/schemas.py:100`), `VenueUpdateIn` (`apps/venues/schemas.py:109`), `TablePinCreateIn` (`apps/panoramas/schemas.py:28`), and `TablePinUpdateIn` (`apps/panoramas/schemas.py:84`) shall each declare `model_config = ConfigDict(extra="forbid")`. When any unknown field is supplied in a request body to those schemas, the system shall reject the request with HTTP `422` (`VALIDATION_ERROR`).

### Stale `phone_number` Attribute & PII Scrubbing (T-030 Low)
- **REQ-HYG-004** **Wallet admin search fields (`apps/wallets/admin.py:23,51`):** `WalletAdmin.search_fields` shall use `"user__phone"` (replacing `"user__phone_number"`), and `WalletTransactionAdmin.search_fields` shall use `"wallet__user__phone"` (replacing `"wallet__user__phone_number"`), matching `accounts.User.phone`.
- **REQ-HYG-005** **Payment initiation customer phone (`apps/billing/services/payment.py:144`):** When `initiate_payment` constructs `PaymentInitiateRequest`, it shall populate `customer_phone` from `booking.customer.phone` (via `getattr(booking.customer, "phone", "")`).
  - **Behavioral / Gateway Payload Change Notice:** Previously, `getattr(booking.customer, "phone_number", "")` always evaluated to `""` because `accounts.User` defines `phone`, not `phone_number`. Fixing this attribute causes `PaymentInitiateRequest.customer_phone` to carry the customer's real normalized phone number (e.g. `09123456789`) to the payment gateway adapter.
- **REQ-HYG-006** **Observability PII scrub list (`core/observability.py:34`):** `"phone_number"` shall remain in `_SENSITIVE_KEYS` alongside `"phone"` and `"mobile"` as defense-in-depth so third-party/external payloads or log dicts using `phone_number` continue to be redacted as `[REDACTED]`.

### Environment & Observability Configuration (T-030 Low / T-031)
- **REQ-HYG-007** **`CSRF_TRUSTED_ORIGINS` from environment (`config/settings/base.py`, `.env.example`):** `config/settings/base.py` shall configure `CSRF_TRUSTED_ORIGINS` from a comma-separated environment variable defaulting to `[]` (matching `ALLOWED_HOSTS=(list, [])` via `django-environ`), and `.env.example` shall document `CSRF_TRUSTED_ORIGINS=` with an empty/example comment.
- **REQ-HYG-008** **Fix `send_default_pii` `DeprecationWarning` (`core/observability.py:191`):** `init_sentry` in `core/observability.py` shall resolve the `DeprecationWarning` emitted for `send_default_pii` without suppressing warnings (no `warnings.filterwarnings` or pytest warning ignore), while preserving `client.options["send_default_pii"] is False` and PII scrubbing behavior.

### Test, Typing, Coverage & Audit Hygiene (T-030 / T-031 / T-034 / T-035 / T-036)
- **REQ-HYG-009** **Isolated tests for T-035/T-036 reviewer nits:**
  - T-035 (`apps/venues/tests/test_owner_addons.py`): isolated tests for add-on `title` > 200 chars (`422`), `fee` > `9_223_372_036_854_775_807` (`422`), boolean `fee` `true`/`false` (`422`), pre-warmed public venue cache invalidation on `DELETE`, and unauthenticated `401` on all owner add-on endpoints.
  - T-036 (`apps/venues/tests/test_venue_review.py`): isolated tests for `VenueRejectIn` `extra="forbid"` (`422`), unauthenticated `401` on `/submit`, `/approve`, and `/reject`, and public venue cache invalidation on `/submit` and `/reject`.
  - T-030 (`extra="forbid"`): tests confirming unknown fields return `422` on `VenueCreateIn`, `VenueUpdateIn`, `TablePinCreateIn`, and `TablePinUpdateIn`.
- **REQ-HYG-010** **Mypy `[annotation-unchecked]` test helpers:** Annotate the 8 `[annotation-unchecked]` test helper/function definitions reported by `mypy .` in `apps/accounts/tests/test_observability_t031.py:28` and `apps/bookings/tests/test_concurrency_spike.py:147-150,260-261,397`, and check `apps/billing/tests/test_wallet_payment.py` for any `[annotation-unchecked]` notes, so `mypy .` produces zero `[annotation-unchecked]` notes in those files.
- **REQ-HYG-011** **Reachable coverage in T-034/T-035/T-036 touched files:** Measure line/branch coverage on files touched by T-034, T-035, and T-036 and add tests for reachable uncovered lines/branches without weakening existing assertions or skipping tests.
- **REQ-HYG-012** **Dependency audit only (T-030 Medium):** Install `pip-audit` in the local `.venv` only (never in `requirements.txt` or `requirements-dev.txt`), run `pip-audit` on the backend `.venv` and `npm audit` in `frontend/`, and record findings in `docs/security/t042-dependency-audit.md`. Do NOT upgrade any dependencies.

## 4. Business rules touched
- **BR-003 / ARCH-005** — `DesignAddon.fee` remains integer Toman payable in person; bounded to `0 <= fee <= 9_223_372_036_854_775_807` with strict integer typing.
- **ARCH-004** — Public venue cache invalidation on add-on delete and venue review `/submit` and `/reject` verified via pre-warmed cache tests.
- **NFR-005 / Safety** — Real customer `phone` is passed only to the internal `PaymentInitiateRequest` gateway contract (never exposed in public schemas or logged unmasked); `phone_number` stays in `_SENSITIVE_KEYS`.

## 5. Non-functional targets
- **Type safety:** `mypy .` passes with 0 errors and 0 `[annotation-unchecked]` notes in `test_observability_t031.py`, `test_concurrency_spike.py`, and `test_wallet_payment.py`.
- **Warnings:** Running `pytest apps/accounts/tests/test_observability_t031.py` emits 0 `send_default_pii` `DeprecationWarning`s without any warning suppression filters.
- **Lint & Contract:** `python manage.py check`, `ruff check .`, `mypy .`, `pytest` (PostgreSQL), and `./check-contract.sh` (with `api/openapi.snapshot.json` updated under protected-path human gate) pass with 0 failures and 0 skipped tests.

## 6. Acceptance criteria (Gherkin)

```gherkin
Scenario: 1. Design add-on fee rejects booleans and > BigInteger max
  Given an authenticated VENUE_OWNER for Venue A
  When the owner calls POST /api/v1/venues/owner/venues/<venue_a_id>/addons/ with:
    | payload                                                  |
    | {"title": "Candles", "fee": true}                        |
    | {"title": "Candles", "fee": false}                       |
    | {"title": "Candles", "fee": 9223372036854775808}         |
  Then HTTP 422 with error_code "VALIDATION_ERROR" is returned for each payload
    And calling _validate_addon_fields("Candles", 9223372036854775808) raises DjangoValidationError.

Scenario: 2. Venue and TablePin create/update schemas reject unknown fields
  Given an authenticated VENUE_OWNER
  When the owner sends an unknown field "is_approved": true to VenueCreateIn or VenueUpdateIn
    Or sends an unknown field "venue_id": 999 to TablePinCreateIn or TablePinUpdateIn
  Then HTTP 422 with error_code "VALIDATION_ERROR" is returned.

Scenario: 3. Stale phone_number replaced with User.phone in wallets admin and billing payment
  Given a Customer with phone "09123456789" and an initiated booking payment
  When an admin searches WalletAdmin or WalletTransactionAdmin by "09123456789"
  Then Django Admin executes the query using user__phone / wallet__user__phone without FieldError
  When initiate_payment builds PaymentInitiateRequest for that booking
  Then PaymentInitiateRequest.customer_phone equals "09123456789" (instead of "")
    And core.observability._SENSITIVE_KEYS still contains "phone_number".

Scenario: 4. CSRF_TRUSTED_ORIGINS loads comma-separated origins from env
  Given CSRF_TRUSTED_ORIGINS is unset in environment
  Then settings.CSRF_TRUSTED_ORIGINS equals []
  Given CSRF_TRUSTED_ORIGINS="https://mizban.ir,https://admin.mizban.ir"
  Then settings.CSRF_TRUSTED_ORIGINS equals ["https://mizban.ir", "https://admin.mizban.ir"].

Scenario: 5. T-035/T-036 reviewer nits, mypy annotations, and Sentry DeprecationWarning
  When pytest runs apps/venues/tests/test_owner_addons.py, apps/venues/tests/test_venue_review.py, and apps/accounts/tests/test_observability_t031.py
  Then all reviewer-nit tests pass (422 oversized title, pre-warmed cache invalidation on DELETE/submit/reject, 401 unauthenticated, VenueRejectIn extra="forbid")
    And 0 DeprecationWarnings are emitted for send_default_pii
    And mypy . reports 0 [annotation-unchecked] notes in the targeted test files.

Scenario: 6. Dependency audit only (no upgrades)
  Given pip-audit is installed in local .venv only (not in requirements*.txt)
  When pip-audit and frontend npm audit are executed
  Then findings are documented in docs/security/t042-dependency-audit.md
    And requirements.txt, requirements-dev.txt, and frontend/package-lock.json remain unmodified.
```

## 7. Out of scope (explicit)
- **OTP IP rate-limit spoofing** (deferred to Phase D).
- **CI/CD pipeline setup** (GitHub Actions / runner setup).
- **Live `SENTRY_DSN` / production smoke testing**.
- **Real payment gateway or SMS.ir integration**.
- **Celery Beat scheduling** (periodic task wiring).
- **Database migrations** (zero migrations in T-042).
- **New runtime dependencies** (including `pip-audit`, which stays local to `.venv` only).
- **Upgrading dependencies** (T-042 performs dependency audit ONLY).

## 8. Open questions
- **Q1 (Gateway payload change):** Fixing `booking.customer.phone` in `apps/billing/services/payment.py:144` changes `PaymentInitiateRequest.customer_phone` from `""` to the customer's real normalized phone. Confirmed as intended fix for T-030 Low; sandbox/mock gateway tests must verify this behavior.
