import type { PublicTablePinOut } from "@/lib/api";

export interface PanoramaHotspot {
  id: string;
  pinId: number;
  pitch: number;
  yaw: number;
  label: string;
  pin: PublicTablePinOut;
}

/**
 * Convert PublicTablePinOut records into Pannellum hotspot payloads.
 * Preserves exact pitch/yaw coordinates and excludes pins missing coordinates.
 */
export function mapPinsToHotspots(pins: PublicTablePinOut[]): PanoramaHotspot[] {
  return pins
    .filter(
      (pin): pin is PublicTablePinOut & { pitch: number; yaw: number } =>
        typeof pin.pitch === "number" && typeof pin.yaw === "number"
    )
    .map((pin) => ({
      id: `pin-${pin.id}`,
      pinId: pin.id,
      pitch: pin.pitch,
      yaw: pin.yaw,
      label: pin.table_number,
      pin,
    }));
}

export function getPinsWithoutCoordinates(pins: PublicTablePinOut[]): PublicTablePinOut[] {
  return pins.filter((pin) => typeof pin.pitch !== "number" || typeof pin.yaw !== "number");
}

export function formatToman(amount: number): string {
  return `${new Intl.NumberFormat("fa-IR").format(amount)} تومان`;
}

export function smokingStatusLabel(isSmoking: boolean): string {
  return isSmoking ? "سیگار آزاد است" : "سیگار ممنوع است";
}
