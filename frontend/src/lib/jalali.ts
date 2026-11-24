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
