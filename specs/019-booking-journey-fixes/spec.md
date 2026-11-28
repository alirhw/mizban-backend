# Spec 019 — Booking-Journey Fixes (Frontend F-01)

This specification documents the 18 frontend booking-journey fixes (`B1`, `M1`, `M3`, `M5`, `M6`, `M11`, `m8`, `m9`, `m16`, `m17`, `m18`, `m21`, `m22`, `m23`, `m24`, `m27`, `m30`, plus automated tests) across `BookingFlow`, `/my-bookings`, `/bookings/callback`, and `lib/booking.ts`.

## Scope & Expected Behaviour

1. **B1 — Confirmed booking link (`BookingFlow.tsx`):**
   - The confirmed panel's "مشاهده رزروهای من" `<Link>` points to `/my-bookings` (not `/bookings`, which does not exist).
2. **M1 — Stale receipt guard (`my-bookings/page.tsx`):**
   - `handleOpenReceipt` tracks a monotonic request counter (`receiptRequestIdRef`). Late responses or errors for an earlier booking are ignored once another booking has been selected or a new load begins.
3. **M3 — Live countdown during payment & expiry fail-closed (`BookingFlow.tsx`):**
   - The 1-second countdown interval and `remainingSeconds` run during `"locked"`, `"paying"`, and `"failed"`.
   - When the lock expires during `"paying"`, `LOCK_EXPIRED` fires and the in-flight payment handlers check `stepRef.current === "expired"` before applying any result, never transitioning an expired flow to `"confirmed"` client-side.
4. **M5 — Failed load rendering (`my-bookings/page.tsx`):**
   - When `loadError` is set, only the error banner with a "تلاش مجدد" button is rendered; the empty-state message ("هنوز رزروی ثبت نکرده‌اید.") and wallet box (with fabricated `۰ تومان`) are hidden.
5. **M6 — Preserve manual payment method choice (`BookingFlow.tsx`):**
   - `userSelectedPaymentMethodRef` records when the customer explicitly selects `"wallet"` or `"gateway"`. Deferred `getMyWallet()` resolution or failure only sets the default payment method when the customer has not manually chosen one for the current booking.
6. **M11 — Explicit pagination (`my-bookings/page.tsx`):**
   - `listMyBookings` is fetched with `limit: 50` and `listMyReviews` with `limit: 20` and `offset`.
   - End-of-list is detected by a short page (`items.length < limit`).
   - "نمایش بیشتر رزروها" and "نمایش بیشتر نظرها" buttons append/merge subsequent pages and display current counts.
7. **m8 — Resumed slot end time (`BookingFlow.tsx`, `lib/booking.ts`):**
   - Resumed bookings compute `slotEndIso` as `slotStartIso + 90 minutes` via `computeSlotEndIso` (`SLOT_DURATION_MINUTES = 90`).
8. **m9 — Authoritative lock amount for wallet sufficiency (`BookingFlow.tsx`):**
   - Once a lock is acquired, both `canUseWallet` and `resolveWalletOptionAvailability` evaluate sufficiency against `state.amountOnlineToman ?? selectedPin.reservation_fee_toman`.
9. **m16 — Post-cancel refetch isolation (`my-bookings/page.tsx`):**
   - The post-cancel `listMyBookings` + `getMyWallet` refresh runs in its own `try/catch` (`refreshBookingsAndWallet`) after `CANCEL_SUCCEEDED`. A refresh failure keeps the cancellation success banner and displays a non-blocking refresh error with a retry button.
10. **m17 — Clear stale user data (`my-bookings/page.tsx`):**
    - `bookings`, `wallet`, `reviewsByBookingId`, and receipt state are cleared on load entry (including user changes) and on load failure so a previous user's data never renders under another session or an error banner.
11. **m18 — Loading state on return to slot step (`BookingFlow.tsx`):**
    - Leaving the `"slot"` step clears `slotsState.requestKey`, so returning to `"slot"` displays the loading indicator until the fresh `listVenueSlots` response arrives.
12. **m21 — Selected slot button indicator (`BookingFlow.tsx`):**
    - Slot buttons compare `state.slotStartIso === slot.start` and apply `aria-pressed={isSelected}` and selected styling (`border-stone-900 bg-stone-900 text-white`).
13. **m22 — Receipt-authoritative callback status (`bookings/callback/page.tsx`):**
    - When a valid `booking_id` is present, the callback page fetches `getBookingReceipt` and shows a neutral checking state while loading instead of assuming failure from a missing `booking_status` query param.
    - Confirmation is decided via `resolveCallbackReceiptConfirmed(receipt, receiptError)`. Non-confirmed receipts render with a clear warning banner rather than a confirmed badge.
14. **m23 — Callback receipt-error actions (`bookings/callback/page.tsx`):**
    - The receipt-error screen includes a retry button ("تلاش مجدد دریافت رسید") and a link to `/my-bookings` alongside "بازگشت به صفحه مجموعه".
15. **m24 — Disable cancel reset during request (`my-bookings/page.tsx`):**
    - The "انصراف" button in the cancel confirmation banner is disabled while `cancelState.step === "cancelling"`.
16. **m27 — Resume parser validation & default step (`lib/booking.ts`):**
    - `parseBookingResumeParams` validates `slotDate` as a real calendar `YYYY-MM-DD` date and `slotStartIso` via `Date.parse`, returning `null` for invalid dates/times.
    - Missing or invalid `step` defaults to `"addons"` when a valid slot is present.
17. **m30 — Synchronous double-submit guards (`BookingFlow.tsx`, `bookings/callback/page.tsx`):**
    - `handleConfirmAndLock` (`lockInFlightRef`) and `handleRetryPayment` (`retryInFlightRef`) use synchronous ref guards mirroring `paymentInFlightRef` to prevent duplicate in-flight submissions.
18. **Tests:**
    - Reproduction and verification tests in `frontend/src/lib/__tests__/BookingJourneyF01.test.tsx` and `frontend/src/lib/__tests__/booking.test.ts`.
