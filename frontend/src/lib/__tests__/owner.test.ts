import { describe, expect, it } from "vitest";

import { formatJalaliDate } from "../jalali";
import {
  formatMaskedPhone,
  getBookingStatusLabel,
  getPanoramaStatusLabel,
  getSubscriptionBadge,
  OWNER_EMPTY_VENUES_TEXT,
  OWNER_FORBIDDEN_TEXT,
  validateBlockedSlotInput,
} from "../owner";

describe("owner subscription labels (PH-06-02)", () => {
  it("returns ACTIVE for active subscriptions with >7 days remaining", () => {
    const badge = getSubscriptionBadge({
      is_active: true,
      days_remaining: 30,
      has_ever_subscribed: true,
    });
    expect(badge.code).toBe("ACTIVE");
    expect(badge.label).toBe("فعال");
    expect(badge.detail).toContain("30");
  });

  it("returns EXPIRING_SOON when 1..7 days remain", () => {
    const badge = getSubscriptionBadge({
      is_active: true,
      days_remaining: 5,
      has_ever_subscribed: true,
    });
    expect(badge.code).toBe("EXPIRING_SOON");
    expect(badge.label).toBe("در حال انقضا");
    expect(badge.tone).toBe("amber");
  });

  it("returns EXPIRED or INACTIVE when subscription is inactive", () => {
    const expired = getSubscriptionBadge({
      is_active: false,
      days_remaining: 0,
      has_ever_subscribed: true,
    });
    expect(expired.code).toBe("EXPIRED");
    expect(expired.label).toBe("منقضی‌شده");

    const never = getSubscriptionBadge({
      is_active: false,
      days_remaining: 0,
      has_ever_subscribed: false,
    });
    expect(never.code).toBe("INACTIVE");
    expect(never.label).toBe("غیرفعال");
  });
});

describe("BlockedSlot validation (PH-06-02 / T-026)", () => {
  const nowMs = Date.parse("2026-11-25T10:00:00Z");

  it("rejects past slots", () => {
    const res = validateBlockedSlotInput(
      "2026-11-25T09:00:00Z",
      [{ open_time: "09:00:00" }],
      nowMs
    );
    expect(res.valid).toBe(false);
    expect(res.error).toContain("گذشته");
  });

  it("rejects misaligned slots against operating hours 120-minute grid", () => {
    // 09:00 Tehran = 05:30Z -> aligned slots are 05:30Z, 07:30Z, 09:30Z, 11:30Z...
    const misaligned = validateBlockedSlotInput(
      "2026-11-26T06:15:00Z",
      [{ open_time: "09:00:00" }],
      nowMs
    );
    expect(misaligned.valid).toBe(false);
    expect(misaligned.error).toContain("تراز");
  });

  it("accepts a valid future aligned slot", () => {
    // 11:00 Tehran = 07:30Z (09:00 + 120m)
    const valid = validateBlockedSlotInput(
      "2026-11-26T07:30:00Z",
      [{ open_time: "09:00:00" }],
      nowMs
    );
    expect(valid).toEqual({ valid: true, error: null });
  });
});

describe("owner dashboard helpers (PH-06-02)", () => {
  it("provides exact Persian empty-venues and forbidden copy", () => {
    expect(OWNER_EMPTY_VENUES_TEXT).toBe("هنوز ونیویی ثبت نکرده‌اید");
    expect(OWNER_FORBIDDEN_TEXT).toBe("دسترسی ندارید");
  });

  it("formats masked phone numbers and preserves already-masked server values", () => {
    expect(formatMaskedPhone("0912***789")).toBe("0912***789");
    expect(formatMaskedPhone("09123456789")).toBe("0912***789");
  });

  it("maps panorama and booking statuses and formats Jalali dates", () => {
    expect(getPanoramaStatusLabel("READY")).toBe("آماده نمایش");
    expect(getPanoramaStatusLabel(null)).toBe("بدون تصویر ۳۶۰");
    expect(getBookingStatusLabel("CONFIRMED")).toBe("تایید شده");
    expect(
      formatJalaliDate("2026-11-26T07:30:00Z", { includeTime: true, latinDigits: true })
    ).toMatch(/1405\/09\/05/);
  });

  it("M8: returns UNKNOWN badge when subscription is null", () => {
    const badge = getSubscriptionBadge(null);
    expect(badge.code).toBe("UNKNOWN");
    expect(badge.label).toBe("نامشخص");
    expect(badge.detail).toBe("اطلاعات اشتراک در دسترس نیست");
    expect(badge.tone).toBe("neutral");
  });

  it("m32: validates weekday, close_time, crosses_midnight, and 120-min empty-hours grid", () => {
    const baseNow = Date.parse("2026-11-25T10:00:00Z");
    // 2026-11-26 is Thursday -> Python weekday = 3
    const thursday11Tehran = "2026-11-26T07:30:00Z"; // 11:00 Tehran
    const thursday21Tehran = "2026-11-26T17:30:00Z"; // 21:00 Tehran (120m slot ends 23:00)

    const weekdayMismatch = validateBlockedSlotInput(
      thursday11Tehran,
      [{ weekday: 4, open_time: "09:00:00", close_time: "23:00:00", crosses_midnight: false }],
      baseNow
    );
    expect(weekdayMismatch.valid).toBe(false);

    const pastClose = validateBlockedSlotInput(
      thursday21Tehran,
      [{ weekday: 3, open_time: "09:00:00", close_time: "22:00:00", crosses_midnight: false }],
      baseNow
    );
    expect(pastClose.valid).toBe(false);

    const crossesMidnightOk = validateBlockedSlotInput(
      thursday21Tehran,
      [{ weekday: 3, open_time: "09:00:00", close_time: "02:00:00", crosses_midnight: true }],
      baseNow
    );
    expect(crossesMidnightOk.valid).toBe(true);

    // Empty operatingHours: 120-min grid -> 10:00 Tehran (600m) valid, 11:00 Tehran (660m) invalid
    expect(validateBlockedSlotInput("2026-11-26T06:30:00Z", [], baseNow).valid).toBe(true);
    expect(validateBlockedSlotInput("2026-11-26T07:30:00Z", [], baseNow).valid).toBe(false);
  });
});
