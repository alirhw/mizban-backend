# Spec 017 - Admin Financial Report (T-040 / FR-40, UC-10)
Status: Draft | Owner: Product / Finance | Lane: Full | Implements: FR-40, UC-10 | Architecture: ARCH-001, ARCH-006

## 1. Problem and goal
Platform admins currently have no aggregated financial reporting endpoint to inspect online reservation payment inflows, in-app wallet ledger credits/debits, and subscription revenue across a Tehran-local date range. This feature introduces `GET /api/v1/billing/admin/financial-report/` (**FR-40**, **UC-10**) backed by a service-layer DB aggregation (`apps/billing/services/report.py`) with strict `UserRole.ADMIN` authorization, Tehran-to-UTC half-open date filtering, PII-free output, and supporting composite/time indexes on `PaymentTransaction` and `WalletTransaction`.

## 2. User stories
- **US-01** As a platform admin (`UserRole.ADMIN`), I want to retrieve a financial report filtered by Tehran local dates (`from_date`, `to_date`) with optional `payment_status` filtering and bounded pagination, so that I can audit platform revenue and wallet ledger activity.
- **US-02** As a platform admin, I want `payments.total_toman` to reflect only `SUCCESS` transactions across the entire filtered date range regardless of `payment_status` filter or pagination, so that headline revenue totals are never distorted by view filters.
- **US-03** As a platform security owner, I want non-admin users (including `is_staff=True` users whose `role != UserRole.ADMIN`) to receive `403 FORBIDDEN`, and all report rows to omit `phone`, `email`, `card_pan_masked`, and `tracking_code`, so that financial reporting obeys least-privilege and privacy boundaries.

## 3. Project decisions (G1/G2 — PROJECT decisions, NOT SRS facts)
The following six parameters were decided at G1/G2 for v1 and are **PROJECT decisions, NOT SRS facts**:

1. **Role rule:**
   - `role == UserRole.ADMIN` ONLY (enforced in the service layer).
   - `is_staff=True` alone does **NOT** qualify and must raise `PermissionDenied` (`403 FORBIDDEN`).
2. **Time filter:**
   - `from_date` and `to_date` are accepted as Tehran local calendar dates in `YYYY-MM-DD` format (using `TEHRAN` from `core.jalali`).
   - Converted once at the service boundary to a half-open UTC range: `[from_date 00:00 Tehran, (to_date + 1 day) 00:00 Tehran)`.
   - Missing `to_date` defaults to up to `timezone.now()` (inclusive of current instant); missing `from_date` means from the beginning (no lower bound).
   - Invalid date format or `from_date > to_date` returns HTTP `422` (`VALIDATION_ERROR`).
3. **Totals rule:**
   - `payments.total_toman` sums `amount_toman` for `PaymentStatus.SUCCESS` rows **ONLY** over the whole filtered date range in the DB (`Sum`), and is **never** affected by the `payment_status` query filter or `limit`/`offset` pagination.
   - `payments.counts_by_status` aggregates counts of all `PaymentStatus` values over the whole filtered date range in the DB.
   - `wallet` reports DB `Sum`s `total_credit_toman` and `total_debit_toman` (integer Toman, `0` when empty) over the whole filtered date range.
4. **`subscriptions` section:**
   - Always returns `{"total_toman": 0, "count": 0, "rows": []}` until **FR-27** (online subscription payments) is implemented.
5. **Pagination:**
   - `limit` (default `50`, max `100`, clamped `1..100`) and `offset` (default `0`, clamped `>= 0`) are applied to each section's `rows` (`payments.rows`, `wallet.rows`, and `subscriptions.rows` which is always `[]`).
6. **Privacy:**
   - No `phone`, `email`, `card_pan_masked`, or `tracking_code` may appear anywhere in the response.
   - Users/customers are identified solely by `customer_id` (in `payments.rows`) and `user_id` (in `wallet.rows`).

## 4. Requirements (EARS)
- **REQ-REP-001** **Endpoint & Authentication (`apps/billing/api.py`):**
  The system shall expose `GET /api/v1/billing/admin/financial-report/` (`auth=auth`) returning `200` `FinancialReportOut`.
  - Unauthenticated requests shall return `401`.
  - Accepted query parameters: `from_date: str | None = None`, `to_date: str | None = None`, `payment_status: PaymentStatus | None = None`, `limit: int = 50`, `offset: int = 0`.
  - The Ninja view shall stay thin (`ARCH-001`), delegating authorization, date parsing, and DB aggregation to `apps/billing/services/report.py`.

- **REQ-REP-002** **Admin Role Authorization (Service Layer):**
  When `get_financial_report(user, ...)` is called, if `getattr(user, "role", None) != UserRole.ADMIN`, the service shall raise `PermissionDenied` (`403 FORBIDDEN`), even if `user.is_staff` or `user.is_superuser` is `True`.

- **REQ-REP-003** **Tehran Date Range Parsing & Validation (`ARCH-006`):**
  When `from_date` or `to_date` is provided, the service shall parse each strictly as `YYYY-MM-DD` (Gregorian calendar date interpreted in `core.jalali.TEHRAN`) and convert to UTC instants:
  - `start_utc = datetime.combine(from_date, time.min, tzinfo=TEHRAN).astimezone(UTC)` (omitted if `from_date` is `None`).
  - `end_utc = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=TEHRAN).astimezone(UTC)` (or `timezone.now()` if `to_date` is `None`).
  - Queries shall filter `created_at >= start_utc` (if set) and `created_at < end_utc` (or `<= now` when `to_date` is omitted).
  - If `from_date` or `to_date` fails `YYYY-MM-DD` parsing, or if both are provided and `from_date > to_date`, the system shall return HTTP `422` (`VALIDATION_ERROR`).

- **REQ-REP-004** **Payments Section Aggregation & Row Filtering:**
  Over the filtered date range:
  - `payments.total_toman`: integer DB `Sum("amount_toman")` over `PaymentTransaction` rows with `status=PaymentStatus.SUCCESS` (coalesced to `0`), unaffected by `payment_status` or `limit`/`offset`.
  - `payments.counts_by_status`: dict keyed by `PaymentStatus` values (`INITIATED`, `PENDING`, `SUCCESS`, `FAILED`, `TIMEOUT`) with integer counts over the filtered date range, unaffected by `payment_status` or `limit`/`offset`.
  - `payments.rows`: ordered deterministically (`-created_at, -id`), optionally filtered by `payment_status` if provided, paginated with clamped `limit` (`1..100`, default `50`) and `offset` (`>= 0`, default `0`).
  - Each payment row exposes only: `id`, `booking_id`, `customer_id`, `provider_name`, `amount_toman`, `status`, `created_at` (never `phone`, `email`, `card_pan_masked`, or `tracking_code`).

- **REQ-REP-005** **Wallet Section Aggregation & Row Pagination:**
  Over the filtered date range:
  - `wallet.total_credit_toman`: integer DB `Sum("amount_toman")` over `WalletTransaction` rows with `type=WalletTransactionType.CREDIT` (coalesced to `0`), unaffected by pagination.
  - `wallet.total_debit_toman`: integer DB `Sum("amount_toman")` over `WalletTransaction` rows with `type=WalletTransactionType.DEBIT` (coalesced to `0`), unaffected by pagination.
  - `wallet.rows`: ordered deterministically (`-created_at, -id`), paginated with clamped `limit` (`1..100`, default `50`) and `offset` (`>= 0`, default `0`).
  - Each wallet row exposes only: `id`, `user_id` (via `wallet.user_id`), `type`, `amount_toman`, `balance_after_toman`, `reason`, `booking_id`, `created_at` (never `phone` or `email`).

- **REQ-REP-006** **Subscriptions Stub Section:**
  `subscriptions` in `FinancialReportOut` shall always return `{"total_toman": 0, "count": 0, "rows": []}` until **FR-27** lands.

- **REQ-REP-007** **Database Indexes & Protected Migrations:**
  - `PaymentTransaction.Meta.indexes` (`apps/billing/models.py`) shall add `models.Index(fields=["status", "created_at"], name="idx_pay_status_created_at")`.
  - `WalletTransaction.Meta.indexes` (`apps/wallets/models.py`) shall add `models.Index(fields=["created_at"], name="idx_wallet_tx_time")` (alongside existing `idx_wallet_tx_created_at` on `["wallet", "created_at"]`).
  - Migrations shall be generated via `python manage.py makemigrations`; `apps/wallets/migrations/**` (and `apps/billing/migrations/**`) are flagged as protected paths requiring human gate review before applying.

## 5. Business rules touched
- **FR-40 / UC-10** — Admin financial report aggregating payments, wallet ledger credits/debits, and subscriptions stub.
- **BR-003 / ARCH-005** — Payment amounts are integer Toman (`amount_toman`) representing table reservation fee only.
- **BR-004 / TD-005** — Wallet transactions are append-only integer Toman `CREDIT`/`DEBIT` ledger entries.
- **ARCH-001** — Aggregation and authorization live in `apps/billing/services/report.py`; Ninja view in `apps/billing/api.py` stays thin.
- **ARCH-006** — All stored timestamps are UTC; Tehran local date boundaries (`TEHRAN` from `core.jalali`) are converted to UTC at the query boundary.

## 6. Non-functional targets
- **Security & Privacy:** Unauthenticated -> `401`; non-`ADMIN` (including `is_staff=True` with `CUSTOMER`/`VENUE_OWNER` role) -> `403 FORBIDDEN`; response schemas use `ConfigDict(extra="forbid")` and omit `phone`, `email`, `card_pan_masked`, and `tracking_code`.
- **Query Efficiency & Correctness:** Totals and status counts use DB `Sum`/`Count` aggregations (never Python loops over unpaginated rows); `wallet.rows` uses `select_related("wallet")` to avoid N+1 queries; `idx_pay_status_created_at` and `idx_wallet_tx_time` support range scans; `limit` clamped to `1..100`, `offset >= 0`.
- **Contract & Tests:** `python manage.py check`, `pytest apps/billing/tests/test_admin_financial_report.py` (PostgreSQL), and `./check-contract.sh` (after `api/openapi.snapshot.json` update under human gate) pass with 0 failures and 0 skipped tests.

## 7. Acceptance criteria (Gherkin)

```gherkin
Scenario: 1. Role enforcement — ADMIN allowed, is_staff non-ADMIN and CUSTOMER/VENUE_OWNER rejected (403 / 401)
  Given a CUSTOMER user C1 with is_staff=True and role="CUSTOMER"
    And a VENUE_OWNER user O1 with role="VENUE_OWNER"
    And an ADMIN user A1 with role="ADMIN"
  When an unauthenticated caller requests GET /api/v1/billing/admin/financial-report/
  Then HTTP 401 is returned
  When C1 or O1 requests GET /api/v1/billing/admin/financial-report/
  Then HTTP 403 with error_code "FORBIDDEN" is returned
  When A1 requests GET /api/v1/billing/admin/financial-report/
  Then HTTP 200 is returned with payments, wallet, and subscriptions sections.

Scenario: 2. Tehran local date half-open UTC boundary and invalid date validation (422)
  Given PaymentTransaction P1 created at 2026-06-15 20:30:00 UTC (2026-06-16 00:00:00 Asia/Tehran) with status=SUCCESS and amount_toman=100000
    And PaymentTransaction P2 created at 2026-06-15 20:29:59 UTC (2026-06-15 23:59:59 Asia/Tehran) with status=SUCCESS and amount_toman=50000
  When A1 requests GET /api/v1/billing/admin/financial-report/?from_date=2026-06-15&to_date=2026-06-15
  Then P2 is included and P1 is excluded, and payments.total_toman == 50000
  When A1 requests GET /api/v1/billing/admin/financial-report/?from_date=2026-06-20&to_date=2026-06-15
  Then HTTP 422 with error_code "VALIDATION_ERROR" is returned
  When A1 requests GET /api/v1/billing/admin/financial-report/?from_date=1405/03/25
  Then HTTP 422 with error_code "VALIDATION_ERROR" is returned.

Scenario: 3. Totals independence from payment_status filter and pagination, plus wallet sums and subscriptions stub
  Given in the date range there are PaymentTransactions: SUCCESS (100000), SUCCESS (200000), FAILED (50000)
    And WalletTransactions: CREDIT (150000), DEBIT (40000)
  When A1 requests GET /api/v1/billing/admin/financial-report/?payment_status=FAILED&limit=1&offset=0
  Then payments.total_toman == 300000
    And payments.counts_by_status == {"INITIATED": 0, "PENDING": 0, "SUCCESS": 2, "FAILED": 1, "TIMEOUT": 0}
    And payments.rows has length 1 with status="FAILED"
    And wallet.total_credit_toman == 150000 and wallet.total_debit_toman == 40000
    And wallet.rows has length 1
    And subscriptions == {"total_toman": 0, "count": 0, "rows": []}.

Scenario: 4. Privacy — PII and sensitive payment fields are excluded
  Given a PaymentTransaction with card_pan_masked="603799******1234", tracking_code="TRK-999", and customer with phone="+989121112233", email="c@example.com"
    And a WalletTransaction for that customer's wallet
  When A1 requests GET /api/v1/billing/admin/financial-report/
  Then the JSON response contains customer_id and user_id
    And the JSON response does NOT contain "phone", "email", "card_pan_masked", or "tracking_code" keys or values.
```

## 8. Out of scope (explicit)
- **CSV / PDF export:** Downloadable report exports are deferred to a follow-up task.
- **Payout actions:** Settlement/payout workflows to venue owners are out of scope.
- **FR-27 online subscription payments:** Real subscription payment aggregation is deferred to FR-27 (`subscriptions` remains a zeroed stub).
- **`frontend/` admin report page:** Building the Next.js admin financial report UI belongs to a separate frontend follow-up task.

## 9. Open questions
- None; all G1/G2 project decisions (role rule, Tehran date range, totals rule, subscriptions stub, pagination `50`/`100`, privacy exclusions, conditional indexes) are fixed for T-040.

## 10. Frontend Admin Financial Report Page (Follow-up (g))
- **Route & Navigation:** New client page `frontend/src/app/admin/financial-report/page.tsx` and Header link `"گزارش مالی"` in `frontend/src/components/Header.tsx` rendered only when `!loading && user?.role === "ADMIN"` (alongside `"مدیریت نظرها"`).
- **API Client (`frontend/src/lib/api.ts`):** Hand-written `FinancialReportOut`, `FinancialReportPaymentsSectionOut`, `FinancialReportPaymentRowOut`, `FinancialReportWalletSectionOut`, `FinancialReportWalletRowOut`, `FinancialReportSubscriptionsSectionOut`, and `getFinancialReport({ from_date?, to_date?, payment_status?, limit?, offset? })` (omits unset bounds).
- **Totals, Filters & Privacy Rules:**
  - `from_date` / `to_date` date inputs send Tehran `YYYY-MM-DD` values as picked and omit unset bounds (no client-side defaults or UTC conversion).
  - `payment_status` filters rows only; `payments.total_toman`, `payments.count`, and `payments.counts_by_status` always render server totals directly (never client-computed sums).
  - `wallet` renders `total_credit_toman`, `total_debit_toman`, `count`, and rows; `subscriptions` renders server values and empty state until FR-27 without invented data.
  - Zero phone, email, card, or tracking fields; `403 FORBIDDEN` renders a Persian admin-only message without raw `error_code`.
- **Tests:** `frontend/src/lib/__tests__/api.test.ts` and `frontend/src/lib/__tests__/AdminFinancialReport.test.tsx`.
