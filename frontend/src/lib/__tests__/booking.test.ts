import { describe, expect, it } from "vitest";

import { ApiError } from "../api";
import {
  bookingReducer,
  buildBookingReturnUrl,
  computeBookingSummary,
  computeLockRemainingSeconds,
  computeSlotEndIso,
  formatCountdownMmSs,
  getOrCreateBookingIdempotencyKey,
  INITIAL_BOOKING_STATE,
  isInsufficientWalletBalanceError,
  mapBookingErrorToPersian,
  parseBookingResumeParams,
  parseRawResumePinId,
  resolveCallbackReceiptConfirmed,
  resolveWalletOptionAvailability,
} from "../booking";
import { formatJalaliFromIsoDate, getTehranDateIso, isSlotAtLeast24HoursAhead } from "../jalali";

describe("booking fee summary (BR-003)", () => {
  it("keeps online total equal to table fee and sums addons for in-person total", () => {
    const summary = computeBookingSummary(150_000, [{ fee: 80_000 }, { fee: 120_000 }]);

    expect(summary).toEqual({
      onlineTotalToman: 150_000,
      inPersonTotalToman: 200_000,
      grandTotalToman: 350_000,
      inPersonLabel: "پرداخت در محل برای افزودنی‌های طراحی",
      addonCount: 2,
    });
  });

  it("returns 'بدون افزودنی' when 0 addons are selected", () => {
    const summary = computeBookingSummary(150_000, []);

    expect(summary.onlineTotalToman).toBe(150_000);
    expect(summary.inPersonTotalToman).toBe(0);
    expect(summary.grandTotalToman).toBe(150_000);
    expect(summary.inPersonLabel).toBe("بدون افزودنی");
    expect(summary.addonCount).toBe(0);
  });
});

describe("24-hour lead time rule & Tehran Jalali date helpers (BR-002 / ARCH-006)", () => {
  it("returns false when slot is less than 24 hours ahead and true at or beyond 24 hours", () => {
    const nowMs = Date.parse("2026-05-01T10:00:00Z");
    const exactly24h = "2026-05-02T10:00:00Z";
    const under24h = "2026-05-02T09:59:59Z";
    const over24h = "2026-05-02T14:00:00Z";

    expect(isSlotAtLeast24HoursAhead(under24h, nowMs)).toBe(false);
    expect(isSlotAtLeast24HoursAhead(exactly24h, nowMs)).toBe(true);
    expect(isSlotAtLeast24HoursAhead(over24h, nowMs)).toBe(true);
    expect(isSlotAtLeast24HoursAhead("invalid-iso", nowMs)).toBe(false);
  });

  it("computes Tehran ISO date with offsetDays and formats Jalali from YYYY-MM-DD", () => {
    // 2026-03-20T21:00:00Z is already 2026-03-21 00:30 in Asia/Tehran
    const nowMs = Date.parse("2026-03-20T21:00:00Z");
    expect(getTehranDateIso(0, nowMs)).toBe("2026-03-21");
    expect(getTehranDateIso(1, nowMs)).toBe("2026-03-22");
    expect(formatJalaliFromIsoDate("2026-03-21", { latinDigits: true })).toBe("1405/01/01");
    expect(() => formatJalaliFromIsoDate("2026-02-31")).toThrow(RangeError);
  });
});

describe("lock countdown timer", () => {
  it("formats remaining seconds as mm:ss and reaches '00:00' at expiry", () => {
    const expiresIso = "2026-05-01T10:10:00Z";
    const atNineMinFiftyNine = Date.parse("2026-05-01T10:00:01Z");
    const atExpiry = Date.parse("2026-05-01T10:10:00Z");
    const pastExpiry = Date.parse("2026-05-01T10:12:00Z");

    const remStart = computeLockRemainingSeconds(expiresIso, atNineMinFiftyNine);
    expect(remStart).toBe(599);
    expect(formatCountdownMmSs(remStart)).toBe("09:59");

    const remExpiry = computeLockRemainingSeconds(expiresIso, atExpiry);
    expect(remExpiry).toBe(0);
    expect(formatCountdownMmSs(remExpiry)).toBe("00:00");

    expect(formatCountdownMmSs(computeLockRemainingSeconds(expiresIso, pastExpiry))).toBe("00:00");
    expect(formatCountdownMmSs(computeLockRemainingSeconds(null, atExpiry))).toBe("00:00");
  });
});

describe("booking state machine", () => {
  it("walks the full happy path idle -> table -> slot -> addons -> review -> locked -> paying -> confirmed", () => {
    let state = INITIAL_BOOKING_STATE;
    expect(state.step).toBe("idle");

    state = bookingReducer(state, { type: "START" });
    expect(state.step).toBe("table");

    state = bookingReducer(state, { type: "SELECT_TABLE", tablePinId: 42 });
    expect(state.step).toBe("slot");
    expect(state.tablePinId).toBe(42);

    state = bookingReducer(state, {
      type: "SELECT_SLOT",
      slotDate: "2026-05-02",
      slotStartIso: "2026-05-02T14:00:00Z",
      slotEndIso: "2026-05-02T15:30:00Z",
    });
    expect(state.step).toBe("addons");

    state = bookingReducer(state, { type: "TOGGLE_ADDON", addonId: 7 });
    state = bookingReducer(state, { type: "TOGGLE_ADDON", addonId: 9 });
    state = bookingReducer(state, { type: "TOGGLE_ADDON", addonId: 7 });
    expect(state.addonIds).toEqual([9]);

    state = bookingReducer(state, { type: "PROCEED_TO_REVIEW" });
    expect(state.step).toBe("review");

    state = bookingReducer(state, {
      type: "LOCK_ACQUIRED",
      bookingId: 101,
      lockExpiresAt: "2099-05-01T10:10:00Z",
      amountOnlineToman: 150_000,
      amountInPersonToman: 50_000,
    });
    expect(state.step).toBe("locked");
    expect(state.bookingId).toBe(101);

    state = bookingReducer(state, { type: "START_PAYMENT" });
    expect(state.step).toBe("paying");

    state = bookingReducer(state, { type: "PAYMENT_SUCCEEDED" });
    expect(state.step).toBe("confirmed");
  });

  it("supports paying -> failed -> retry while locked", () => {
    const lockedState = {
      ...INITIAL_BOOKING_STATE,
      step: "locked" as const,
      bookingId: 202,
      lockExpiresAt: "2099-05-01T10:10:00Z",
    };

    const payingState = bookingReducer(lockedState, { type: "START_PAYMENT" });
    expect(payingState.step).toBe("paying");

    const failedState = bookingReducer(payingState, {
      type: "PAYMENT_FAILED",
      error: new ApiError(502, "PAYMENT_GATEWAY_ERROR", "Gateway timeout"),
    });
    expect(failedState.step).toBe("failed");
    expect(failedState.errorMessage).toContain("پرداخت ناموفق");

    const retriedToLocked = bookingReducer(failedState, { type: "RETRY_PAYMENT" });
    expect(retriedToLocked.step).toBe("locked");
    expect(retriedToLocked.errorMessage).toBeNull();

    const retriedPaying = bookingReducer(retriedToLocked, { type: "START_PAYMENT" });
    expect(retriedPaying.step).toBe("paying");
  });

  it("supports locked -> expired -> restart and ignores invalid transitions", () => {
    const lockedState = {
      ...INITIAL_BOOKING_STATE,
      step: "locked" as const,
      bookingId: 303,
      lockExpiresAt: "2026-05-01T10:10:00Z",
    };

    // Cannot jump directly from locked to confirmed without paying
    expect(bookingReducer(lockedState, { type: "PAYMENT_SUCCEEDED" }).step).toBe("locked");

    const expiredState = bookingReducer(lockedState, { type: "LOCK_EXPIRED" });
    expect(expiredState.step).toBe("expired");
    expect(expiredState.errorMessage).toContain("پایان رسید");

    const restarted = bookingReducer(expiredState, { type: "RESTART" });
    expect(restarted).toEqual(INITIAL_BOOKING_STATE);
  });
});

describe("Persian booking error mapping", () => {
  it("maps domain error codes to Persian and never leaks raw error_code or stack traces", () => {
    const slotErr = new ApiError(409, "SLOT_ALREADY_RESERVED", "Raw backend detail");
    expect(mapBookingErrorToPersian(slotErr)).toBe(
      "این اسلات همین‌الان رزرو شد؛ یک اسلات دیگر انتخاب کنید"
    );
    expect(mapBookingErrorToPersian(slotErr)).not.toContain("SLOT_ALREADY_RESERVED");

    const leadErr = new ApiError(400, "LEAD_TIME_VIOLATION", "Must be >= 24h");
    const leadMsg = mapBookingErrorToPersian(leadErr);
    expect(leadMsg).toContain("۲۴ ساعت");
    expect(leadMsg).not.toContain("LEAD_TIME_VIOLATION");

    const payErr = new ApiError(502, "PAYMENT_FAILED", "Gateway stack trace at line 42");
    const payMsg = mapBookingErrorToPersian(payErr);
    expect(payMsg).toContain("پرداخت ناموفق");
    expect(payMsg).not.toContain("PAYMENT_FAILED");
    expect(payMsg).not.toContain("stack trace");

    const unknownErr = new Error(
      "TypeError: cannot read properties of undefined\n    at foo.ts:12"
    );
    const unknownMsg = mapBookingErrorToPersian(unknownErr);
    expect(unknownMsg).not.toContain("TypeError");
    expect(unknownMsg).not.toContain("foo.ts");
  });
});

describe("T-028-FIX regression helpers (B2, B3, B4)", () => {
  it("B2: only marks callback confirmed when fetched receipt succeeded with CONFIRMED/COMPLETED", () => {
    expect(resolveCallbackReceiptConfirmed(null, "خطا در دریافت رسید")).toBe(false);
    expect(resolveCallbackReceiptConfirmed(null, null)).toBe(false);
    expect(resolveCallbackReceiptConfirmed({ status: "PENDING_PAYMENT" }, null)).toBe(false);
    expect(resolveCallbackReceiptConfirmed({ status: "CONFIRMED" }, "err")).toBe(false);
    expect(resolveCallbackReceiptConfirmed({ status: "CONFIRMED" }, null)).toBe(true);
    expect(resolveCallbackReceiptConfirmed({ status: "COMPLETED" }, null)).toBe(true);
  });

  it("B3: builds and parses booking return URL for login redirect restoration", () => {
    const returnUrl = buildBookingReturnUrl("real-cafe-dev", {
      pinId: 12,
      slotDate: "2026-11-27",
      slotStartIso: "2026-11-27T11:30:00Z",
      slotLabel: "۱۵:۰۰ تا ۱۶:۳۰",
      addonIds: [1, 3],
      step: "review",
    });

    expect(returnUrl.startsWith("/venues/real-cafe-dev?")).toBe(true);
    const query = returnUrl.split("?")[1] ?? "";
    const parsed = parseBookingResumeParams(new URLSearchParams(query), [10, 12], [1, 2, 3]);

    expect(parsed).toEqual({
      pinId: 12,
      slotDate: "2026-11-27",
      slotStartIso: "2026-11-27T11:30:00Z",
      slotLabel: "۱۵:۰۰ تا ۱۶:۳۰",
      addonIds: [1, 3],
      step: "review",
    });

    expect(parseBookingResumeParams(new URLSearchParams(query), [99], [1, 3])).toBeNull();
  });

  it("B4: reuses the same idempotency key across retries for a booking and mints a new one on new booking", () => {
    let counter = 0;
    const mint = () => `idem-${++counter}`;

    const first = getOrCreateBookingIdempotencyKey(null, 42, mint);
    const retry = getOrCreateBookingIdempotencyKey(first, 42, mint);
    expect(first.key).toBe("idem-1");
    expect(retry.key).toBe("idem-1");

    const nextBooking = getOrCreateBookingIdempotencyKey(retry, 43, mint);
    expect(nextBooking.key).toBe("idem-2");
  });
});

describe("T-034 frontend: BookingFlow wallet payment choice", () => {
  it("maps WALLET_INSUFFICIENT_BALANCE to a Persian message without exposing the raw error code", () => {
    const err = new ApiError(400, "WALLET_INSUFFICIENT_BALANCE", "Raw insufficient balance");
    const msg = mapBookingErrorToPersian(err);

    expect(msg).toContain("موجودی کیف پول");
    expect(msg).not.toContain("WALLET_INSUFFICIENT_BALANCE");
    expect(msg).not.toContain("Raw insufficient balance");
  });

  it("isInsufficientWalletBalanceError returns true only for WALLET_INSUFFICIENT_BALANCE", () => {
    expect(
      isInsufficientWalletBalanceError(
        new ApiError(400, "WALLET_INSUFFICIENT_BALANCE", "Insufficient balance")
      )
    ).toBe(true);

    expect(
      isInsufficientWalletBalanceError(new ApiError(502, "PAYMENT_GATEWAY_ERROR", "Timeout"))
    ).toBe(false);
    expect(isInsufficientWalletBalanceError(new Error("WALLET_INSUFFICIENT_BALANCE"))).toBe(false);
    expect(isInsufficientWalletBalanceError(null)).toBe(false);
  });

  it("resolveWalletOptionAvailability returns loading state while wallet balance is loading", () => {
    expect(
      resolveWalletOptionAvailability({
        loading: true,
        error: false,
        balanceToman: null,
        reservationFeeToman: 150_000,
      })
    ).toEqual({
      enabled: false,
      reason: "loading",
      note: "در حال بررسی موجودی کیف پول...",
    });
  });

  it("resolveWalletOptionAvailability returns unavailable when error is true or balanceToman is null", () => {
    const onError = resolveWalletOptionAvailability({
      loading: false,
      error: true,
      balanceToman: 200_000,
      reservationFeeToman: 150_000,
    });
    expect(onError.enabled).toBe(false);
    expect(onError.reason).toBe("unavailable");
    expect(onError.note).toContain("درگاه پرداخت آنلاین");

    const onNull = resolveWalletOptionAvailability({
      loading: false,
      error: false,
      balanceToman: null,
      reservationFeeToman: 150_000,
    });
    expect(onNull.enabled).toBe(false);
    expect(onNull.reason).toBe("unavailable");
    expect(onNull.note).toContain("درگاه پرداخت آنلاین");
  });

  it("resolveWalletOptionAvailability returns insufficient_balance when balance < table fee or forceInsufficient is true", () => {
    const belowFee = resolveWalletOptionAvailability({
      loading: false,
      error: false,
      balanceToman: 149_999,
      reservationFeeToman: 150_000,
    });
    expect(belowFee.enabled).toBe(false);
    expect(belowFee.reason).toBe("insufficient_balance");
    expect(belowFee.note).toContain("کافی نیست");

    const forced = resolveWalletOptionAvailability({
      loading: false,
      error: false,
      balanceToman: 500_000,
      reservationFeeToman: 150_000,
      forceInsufficient: true,
    });
    expect(forced.enabled).toBe(false);
    expect(forced.reason).toBe("insufficient_balance");
    expect(forced.note).toContain("کافی نیست");
  });

  it("resolveWalletOptionAvailability returns ready when balance >= reservationFeeToman including exact equality", () => {
    expect(
      resolveWalletOptionAvailability({
        loading: false,
        error: false,
        balanceToman: 150_000,
        reservationFeeToman: 150_000,
      })
    ).toEqual({
      enabled: true,
      reason: "ready",
      note: null,
    });

    expect(
      resolveWalletOptionAvailability({
        loading: false,
        error: false,
        balanceToman: 250_000,
        reservationFeeToman: 150_000,
      })
    ).toEqual({
      enabled: true,
      reason: "ready",
      note: null,
    });
  });

  it("bookingReducer transitions locked -> START_PAYMENT -> PAYMENT_SUCCEEDED -> confirmed", () => {
    const lockedState = {
      ...INITIAL_BOOKING_STATE,
      step: "locked" as const,
      bookingId: 501,
      lockExpiresAt: "2099-05-01T10:10:00Z",
    };

    const payingState = bookingReducer(lockedState, { type: "START_PAYMENT" });
    expect(payingState.step).toBe("paying");

    const confirmedState = bookingReducer(payingState, { type: "PAYMENT_SUCCEEDED" });
    expect(confirmedState.step).toBe("confirmed");
  });

  it("bookingReducer transitions locked -> START_PAYMENT -> PAYMENT_FAILED -> RETRY_PAYMENT -> START_PAYMENT", () => {
    const lockedState = {
      ...INITIAL_BOOKING_STATE,
      step: "locked" as const,
      bookingId: 502,
      lockExpiresAt: "2099-05-01T10:10:00Z",
    };

    const payingState = bookingReducer(lockedState, { type: "START_PAYMENT" });
    expect(payingState.step).toBe("paying");

    const failedState = bookingReducer(payingState, {
      type: "PAYMENT_FAILED",
      error: new ApiError(400, "WALLET_INSUFFICIENT_BALANCE", "Insufficient balance"),
    });
    expect(failedState.step).toBe("failed");
    expect(failedState.errorMessage).toContain("موجودی کیف پول");
    expect(failedState.errorMessage).not.toContain("WALLET_INSUFFICIENT_BALANCE");

    const retriedState = bookingReducer(failedState, { type: "RETRY_PAYMENT" });
    expect(retriedState.step).toBe("locked");
    expect(retriedState.errorMessage).toBeNull();

    const restartedPaying = bookingReducer(retriedState, { type: "START_PAYMENT" });
    expect(restartedPaying.step).toBe("paying");
  });
});

describe("parseBookingResumeParams & computeSlotEndIso (m8, m27)", () => {
  it("m27: defaults missing or invalid step to addons when a valid slot is present", () => {
    const missingStep = new URLSearchParams("pin=10&date=2099-01-01&slot=2099-01-01T10:00:00Z");
    expect(parseBookingResumeParams(missingStep, [10], [1, 2])?.step).toBe("addons");

    const invalidStep = new URLSearchParams(
      "pin=10&date=2099-01-01&slot=2099-01-01T10:00:00Z&step=bogus"
    );
    expect(parseBookingResumeParams(invalidStep, [10], [1, 2])?.step).toBe("addons");

    const explicitReview = new URLSearchParams(
      "pin=10&date=2099-01-01&slot=2099-01-01T10:00:00Z&step=review"
    );
    expect(parseBookingResumeParams(explicitReview, [10], [1, 2])?.step).toBe("review");
  });

  it("m27: rejects impossible calendar dates and invalid slot timestamps", () => {
    expect(
      parseBookingResumeParams(
        new URLSearchParams("pin=10&date=2026-13-45&slot=2099-01-01T10:00:00Z"),
        [10],
        []
      )
    ).toBeNull();

    expect(
      parseBookingResumeParams(
        new URLSearchParams("pin=10&date=2026-02-30&slot=2099-01-01T10:00:00Z"),
        [10],
        []
      )
    ).toBeNull();

    expect(
      parseBookingResumeParams(
        new URLSearchParams("pin=10&date=2026-05-01&slot=not-a-timestamp"),
        [10],
        []
      )
    ).toBeNull();

    expect(parseBookingResumeParams(new URLSearchParams("pin=10"), [10], [])).toBeNull();
  });

  it("m8: computeSlotEndIso adds 90 minutes to slotStartIso", () => {
    const start = "2099-01-01T10:00:00.000Z";
    const end = computeSlotEndIso(start);
    expect(Date.parse(end) - Date.parse(start)).toBe(90 * 60 * 1000);
  });

  it("M2: parseRawResumePinId reads positive integer pin param without allowlist", () => {
    expect(parseRawResumePinId(new URLSearchParams("pin=22"))).toBe(22);
    expect(parseRawResumePinId(new URLSearchParams("pin=0"))).toBeNull();
    expect(parseRawResumePinId(new URLSearchParams("pin=abc"))).toBeNull();
    expect(parseRawResumePinId(new URLSearchParams(""))).toBeNull();
  });
});
