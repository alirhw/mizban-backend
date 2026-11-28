# Spec 021 — Owner & Admin Fixes (Frontend F-03)

This specification documents the 16 frontend owner and admin fixes (`M7`, `M8`, `M9`, `M10`, `m1`, `m2`, `m3`, `m4`, `m5`, `m31`, `m32`, `m33`, `m34`, `m36`, `m41`, `m43`) across `OwnerVenueDashboard`, `/owner`, `NotificationsBell`, `/admin/reviews`, `/admin/financial-report`, and `lib/owner.ts`.

## Scope & Expected Behaviour

1. **M7 — Owner bookings pagination (`OwnerVenueDashboard.tsx`):**
   - Calls `listOwnerVenueBookings(venueId, { limit: 50, offset: 0 })`, displays `"نمایش X رزرو"`, and renders `"نمایش بیشتر"` until a short page (`< 50`) is returned.
   - Backend ordering (`apps/venues/services.py:526, 540`): `Booking.objects.filter(venue=venue).order_by("start_at", "id")`.
2. **M8 — Unknown subscription badge (`lib/owner.ts`, `owner/page.tsx`):**
   - Added `code: "UNKNOWN"`, `tone: "neutral"`, `label: "نامشخص"`, `detail: "اطلاعات اشتراک در دسترس نیست"` (`UNKNOWN_SUBSCRIPTION_BADGE`) when `getSubscriptionBadge(null | undefined)` is called on subscription-fetch failure, never fabricating `days_remaining: 0`.
3. **M9 — Per-section dashboard loading (`OwnerVenueDashboard.tsx`):**
   - `getOwnerVenue` is fetched first (`404 -> notFoundError`); subscription, spaces, bookings, and addons load via `Promise.allSettled` with independent per-section error states and retry buttons, keeping loaded sections visible and making `"اطلاعات اشتراک در دسترس نیست."` reachable.
4. **M10 — Financial report failed first load (`admin/financial-report/page.tsx`):**
   - When `!loading && !report && errorMessage`, renders the error banner with a `"تلاش مجدد"` button instead of `"در حال دریافت گزارش مالی..."`.
5. **m1 — Admin reviews error & paging end-of-list (`admin/reviews/page.tsx`):**
   - Load failures render only the error banner (never `"نظری با این فیلترها یافت نشد."`).
   - Empty pages at `offset > 0` keep previous rows visible and render `"به انتهای فهرست رسیدید"` with `"بازگشت به صفحه قبل"`.
6. **m2 — Operation-aware addon 409 mapping (`OwnerVenueDashboard.tsx`):**
   - `mapAddonErrorToPersian(err, operation, fallback)` returns the delete-specific `"قابل حذف نیست؛ می‌توانید آن را غیرفعال کنید."` message only when `operation === "delete"` (only `delete_venue_addon` raises `AddonInUseError` in `apps/venues/services.py:644-653`).
7. **m3 — Already-inactive in-use addon (`OwnerVenueDashboard.tsx`):**
   - On delete 409, active addons show `"غیرفعال کردن افزودنی"`, while already-inactive addons show a clear note that the addon is already inactive and cannot be deleted because it is used in past bookings (no deactivate button).
8. **m4 — Pin fee empty input (`OwnerVenueDashboard.tsx`):**
   - `handleSavePin` requires `/^\d+$/` on `editFee.trim()` and shows `"هزینه رزرو را وارد کنید."` when empty.
9. **m5 — Financial report show-more race (`admin/financial-report/page.tsx`):**
   - `handleShowMore` captures `filterGenRef.current` at click time and discards responses if filters changed mid-flight.
10. **m31 — Block-slot error mapping (`OwnerVenueDashboard.tsx`):**
    - `mapBlockSlotErrorToPersian` maps `SLOT_ALREADY_RESERVED`, `INVALID_SLOT`, `VALIDATION_ERROR`, `FORBIDDEN`, `NOT_FOUND`, and falls back to `err.message` or a generic message; dead `else` branch removed.
11. **m32 — Blocked-slot validation (`lib/owner.ts`):**
    - `validateBlockedSlotInput` checks Tehran weekday (`0=Monday .. 6=Sunday` matching `apps/venues/models.py:98-113`), `open_time` 120-minute grid alignment, `close_time` / `crosses_midnight` bounds (`slotEnd <= effectiveClose`), and uses a 120-minute grid (`tehranMinutes % 120 === 0`) for the empty-hours fallback.
12. **m33 — Per-space pin errors (`OwnerVenueDashboard.tsx`):**
    - `fetchSpacePins` uses `Promise.allSettled` and tracks `pinErrorsBySpaceId` with a per-space retry button instead of silently returning `[]`.
13. **m34 — Persian labels for displayed enums (`OwnerVenueDashboard.tsx`, `owner/page.tsx`, `admin/financial-report/page.tsx`):**
    - Subscription badges render Persian labels only (no raw `ACTIVE`/`INACTIVE`).
    - Financial report maps all 5 payment statuses (`INITIATED`, `PENDING`, `SUCCESS`, `FAILED`, `TIMEOUT`), wallet types (`CREDIT`/`DEBIT`), and known wallet reasons (unknown uppercase codes render `"—"`).
14. **m36 — Bell load-more race (`NotificationsBell.tsx`):**
    - `listRequestGenRef` invalidates in-flight `handleLoadMore` responses after a reopen/`loadFirstPage` reset.
15. **m41 — Review-status badge default (`OwnerVenueDashboard.tsx`):**
    - `getReviewStatusBadge` separates `case "DRAFT"` (`"پیش‌نویس"`) from `default` (`"نامشخص"`).
16. **m43 — Stale-while-revalidate on filter change (`admin/reviews/page.tsx`, `admin/financial-report/page.tsx`):**
    - Keeps previously loaded rows visible with a compact updating indicator while refetching after initial load.

## Out of Scope
- `m35` (admin-reviews venue dropdown) — deferred to backend T-046 (no admin venue-list endpoint in `api/openapi.snapshot.json`).
- `m38` (admin notification bell) — undecided product decision; `Header.tsx` unchanged.
