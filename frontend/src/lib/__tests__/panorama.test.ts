import { describe, expect, it } from "vitest";
import type { PublicTablePinOut } from "@/lib/api";
import { formatToman, mapPinsToHotspots, smokingStatusLabel } from "@/lib/panorama";

function makePin(overrides: Partial<PublicTablePinOut> = {}): PublicTablePinOut {
  return {
    id: 1,
    table_number: "۱",
    capacity: 4,
    pitch: -12.5,
    yaw: 45.25,
    description: "میز کنار پنجره",
    reservation_fee_toman: 150000,
    is_smoking: false,
    ...overrides,
  };
}

describe("mapPinsToHotspots", () => {
  it("maps valid pins with exact pitch/yaw and attaches fee and smoking metadata", () => {
    const pins: PublicTablePinOut[] = [
      makePin({
        id: 10,
        table_number: "A1",
        pitch: -8.75,
        yaw: 120.5,
        reservation_fee_toman: 200000,
        is_smoking: true,
      }),
      makePin({
        id: 11,
        table_number: "B2",
        pitch: 0,
        yaw: -45,
        reservation_fee_toman: 0,
        is_smoking: false,
      }),
    ];

    const hotspots = mapPinsToHotspots(pins);

    expect(hotspots).toHaveLength(2);
    const [first, second] = hotspots;
    expect(first).toEqual({
      id: "pin-10",
      pinId: 10,
      pitch: -8.75,
      yaw: 120.5,
      label: "A1",
      pin: pins[0],
    });
    expect(first?.pin.reservation_fee_toman).toBe(200000);
    expect(first?.pin.is_smoking).toBe(true);

    expect(second?.pitch).toBe(0);
    expect(second?.yaw).toBe(-45);
    expect(second?.pin.reservation_fee_toman).toBe(0);
    expect(second?.pin.is_smoking).toBe(false);
  });

  it("excludes pins missing pitch or yaw coordinates", () => {
    const pins: PublicTablePinOut[] = [
      makePin({ id: 1, pitch: null, yaw: 10 }),
      makePin({ id: 2, pitch: 5, yaw: null }),
      makePin({ id: 3, pitch: null, yaw: null }),
      makePin({ id: 4, pitch: 15, yaw: -30 }),
    ];

    const hotspots = mapPinsToHotspots(pins);

    expect(hotspots).toHaveLength(1);
    expect(hotspots[0]?.pinId).toBe(4);
  });

  it("returns an empty array when there are no pins", () => {
    expect(mapPinsToHotspots([])).toEqual([]);
  });
});

describe("formatToman", () => {
  it("formats numbers in fa-IR with تومان suffix", () => {
    expect(formatToman(150000)).toBe(`${new Intl.NumberFormat("fa-IR").format(150000)} تومان`);
    expect(formatToman(0)).toBe(`${new Intl.NumberFormat("fa-IR").format(0)} تومان`);
  });
});

describe("smokingStatusLabel", () => {
  it("returns Persian smoking status strings", () => {
    expect(smokingStatusLabel(true)).toBe("سیگار آزاد است");
    expect(smokingStatusLabel(false)).toBe("سیگار ممنوع است");
  });
});
