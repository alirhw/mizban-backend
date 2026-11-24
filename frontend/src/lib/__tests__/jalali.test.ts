import { describe, expect, it } from "vitest";

import { formatJalaliDate } from "../jalali";

describe("formatJalaliDate (ARCH-006 presentation-only Jalali)", () => {
  it("converts known ISO UTC dates across the Persian New Year boundary", () => {
    // 2026-03-20 (last day of 1404)
    expect(formatJalaliDate("2026-03-20T12:00:00Z", { latinDigits: true })).toBe("1404/12/29");
    // 2026-03-21 (Nowruz 1405)
    expect(formatJalaliDate("2026-03-21T12:00:00Z", { latinDigits: true })).toBe("1405/01/01");
    // Tehran UTC+03:30 rollover: 2026-03-20T21:00:00Z = 2026-03-21 00:30 Tehran
    expect(formatJalaliDate("2026-03-20T21:00:00Z", { latinDigits: true })).toBe("1405/01/01");
    // Mid-year date
    expect(formatJalaliDate("2026-11-24T10:30:00Z", { latinDigits: true })).toBe("1405/09/03");
  });

  it("formats Persian digits by default and supports includeTime", () => {
    const formatted = formatJalaliDate("2026-03-21T09:00:00Z", {
      includeTime: true,
      latinDigits: true,
    });
    expect(formatted).toContain("1405/01/01");
    expect(formatted).toContain("12:30");
  });

  it("throws RangeError on invalid date input", () => {
    expect(() => formatJalaliDate("not-a-date")).toThrow(RangeError);
  });
});
