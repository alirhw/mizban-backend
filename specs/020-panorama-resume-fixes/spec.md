# Spec 020 — Panorama, Venue Page & Resume Fixes (Frontend F-02)

This specification documents the 8 frontend fixes (`M2`, `M4`, `m6`, `m7`, `m19`, `m20`, `m28`, `m29`) in `VenuePanoramaExplorer`, `PanoramaViewer`, `BookingFlow` (`onStepChange` prop only), `venues/[slug]/page.tsx`, `lib/booking.ts`, and `lib/panorama.ts`.

## Scope & Expected Behaviour

1. **M2 — Resume across spaces (`VenuePanoramaExplorer.tsx`, `lib/booking.ts`):**
   - `parseRawResumePinId(searchParams)` reads the raw integer `pin` query param without an allowlist.
   - When `initialResume` is `null` but `rawResumePinId !== null`, `VenuePanoramaExplorer` searches the remaining spaces in order via `getPublicSpacePanorama`, skipping failing spaces and continuing to the next.
   - When the pin is found, it selects that space, opens `selectedPin` + `bookingPin`, and applies `parseBookingResumeParams` against that space's pins (preserving F-01's real-date validation and `"addons"` default step).
   - If no space contains the pin (or all fetches fail), a clear Persian alert (`"رزرو موردنظر یافت نشد؛ لطفاً دوباره میز را انتخاب کنید."`) is shown.
   - When there is no `pin` query param, no extra panoramas are fetched.
2. **M4 — Space tabs guarded during booking lock (`VenuePanoramaExplorer.tsx`, `BookingFlow.tsx`):**
   - `BookingFlow` accepts `onStepChange?: (step: BookingStep) => void` and reports step changes.
   - `VenuePanoramaExplorer` disables space tabs (`disabled`, `aria-disabled`, and a Persian hint) and returns early from `handleSelectSpace` when `bookingStep` is `"locked"`, `"paying"`, or `"failed"`. Pre-lock space switching continues to clear pin + booking state.
3. **m6 — Table-review fetch failure (`VenuePanoramaExplorer.tsx`):**
   - `tableReviewsState` tracks `error: string | null`. On fetch failure, `data` is set to `null` and an error banner with a `"تلاش مجدد"` button renders instead of `"هنوز نظری برای این میز ثبت نشده است."`.
4. **m7 — Table reviews pagination (`VenuePanoramaExplorer.tsx`):**
   - Uses `TABLE_REVIEWS_PAGE_SIZE = 20`, renders `"نمایش X از Y نظر"` using `review_count`, and provides a `"نمایش بیشتر"` button that fetches the next page via `offset` and appends results until all reviews are loaded.
5. **m19 — Selected-pin highlight on late mount (`PanoramaViewer.tsx`):**
   - The hotspot highlight `useEffect` depends on `[selectedPinId, loadedUrl]` so pins selected before Pannellum finishes loading still receive `aria-pressed="true"` and `ring-4 ring-amber-400 bg-amber-600` once loaded.
6. **m20 — One active pin (`VenuePanoramaExplorer.tsx`):**
   - When a `BookingFlow` is open, the details panel always shows `bookingPin`.
   - Clicking another pin on the panorama restarts the flow on that pin when not locked/paying, or ignores the click with a Persian alert when locked/paying.
   - Background clicks deselect only when no `BookingFlow` is open.
   - `"بستن"` closes both details and `BookingFlow` when not locked/paying, and is hidden while locked/paying.
7. **m28 — Venue page sub-request error states (`venues/[slug]/page.tsx`, `VenuePanoramaExplorer.tsx`):**
   - `getPublicVenueBySlug` keeps `404 -> notFound()` and re-throws other errors.
   - Non-404 errors in `listPublicVenueSpaces`, `getPublicSpacePanorama`, and `listVenueReviews` degrade to explicit error states (`spacesError`, `initialPanoramaError`, `venueReviewsError`) rather than throwing or rendering false empty states; `VenuePanoramaExplorer` provides a client-side `"تلاش مجدد"` for failed spaces.
8. **m29 — Pins without coordinates (`lib/panorama.ts`, `VenuePanoramaExplorer.tsx`):**
   - `getPinsWithoutCoordinates(pins)` returns pins lacking numeric `pitch` or `yaw`.
   - When non-empty, `VenuePanoramaExplorer` renders a visible note under the panorama listing those table numbers (`"میزهای X، Y روی تصویر ۳۶۰ درجه نمایش داده نمی‌شوند چون مختصات ندارند."`).
