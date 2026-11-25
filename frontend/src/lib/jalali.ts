const TEHRAN_TZ = "Asia/Tehran";

export interface FormatJalaliOptions {
  includeTime?: boolean;
  latinDigits?: boolean;
}

/**
 * Format an ISO UTC timestamp (or Date) into Jalali (Solar Hijri) for display only.
 * The backend stores and exchanges UTC ISO timestamps (ARCH-006).
 */
export function formatJalaliDate(
  isoInput: string | Date,
  options: FormatJalaliOptions = {}
): string {
  const date = typeof isoInput === "string" ? new Date(isoInput) : isoInput;
  if (Number.isNaN(date.getTime())) {
    throw new RangeError(`Invalid date input: ${String(isoInput)}`);
  }

  const locale = options.latinDigits ? "fa-IR-u-ca-persian-nu-latn" : "fa-IR-u-ca-persian";

  const formatOpts: Intl.DateTimeFormatOptions = {
    timeZone: TEHRAN_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  };

  if (options.includeTime) {
    formatOpts.hour = "2-digit";
    formatOpts.minute = "2-digit";
    formatOpts.hour12 = false;
  }

  return new Intl.DateTimeFormat(locale, formatOpts).format(date);
}

const MS_PER_DAY = 86_400_000;
const TWENTY_FOUR_HOURS_MS = 24 * 60 * 60 * 1000;

/**
 * Return the current (or offset) calendar date in Asia/Tehran as YYYY-MM-DD.
 */
export function getTehranDateIso(offsetDays = 0, nowMs: number = Date.now()): string {
  const target = new Date(nowMs + offsetDays * MS_PER_DAY);
  if (Number.isNaN(target.getTime())) {
    throw new RangeError(`Invalid nowMs/offsetDays: ${nowMs}, ${offsetDays}`);
  }

  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: TEHRAN_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(target);

  const year = parts.find((p) => p.type === "year")?.value;
  const month = parts.find((p) => p.type === "month")?.value;
  const day = parts.find((p) => p.type === "day")?.value;

  if (!year || !month || !day) {
    throw new RangeError("Failed to format Tehran date parts");
  }

  return `${year}-${month}-${day}`;
}

/**
 * Format a YYYY-MM-DD calendar date into Jalali (Solar Hijri) for display only.
 */
export function formatJalaliFromIsoDate(
  isoDate: string,
  options: FormatJalaliOptions = {}
): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate);
  if (!match) {
    throw new RangeError(`Invalid ISO date (expected YYYY-MM-DD): ${isoDate}`);
  }

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const utcNoon = new Date(Date.UTC(year, month - 1, day, 12, 0, 0));

  if (
    Number.isNaN(utcNoon.getTime()) ||
    utcNoon.getUTCFullYear() !== year ||
    utcNoon.getUTCMonth() !== month - 1 ||
    utcNoon.getUTCDate() !== day
  ) {
    throw new RangeError(`Invalid calendar date: ${isoDate}`);
  }

  return formatJalaliDate(utcNoon, options);
}

/**
 * Enforce the 24-hour lead-time rule (BR-001): returns true iff slotStartIso is at least 24 hours ahead of nowMs.
 */
export function isSlotAtLeast24HoursAhead(
  slotStartIso: string,
  nowMs: number = Date.now()
): boolean {
  const slotMs = Date.parse(slotStartIso);
  if (Number.isNaN(slotMs) || !Number.isFinite(nowMs)) {
    return false;
  }
  return slotMs - nowMs >= TWENTY_FOUR_HOURS_MS;
}
