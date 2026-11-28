import { ApiError, type OperatingHoursOut, type VenueSubscriptionOut } from "@/lib/api";

export const OWNER_EMPTY_VENUES_TEXT = "هنوز ونیویی ثبت نکرده‌اید";
export const OWNER_FORBIDDEN_TEXT = "دسترسی ندارید";

export interface SubscriptionBadge {
  code: "ACTIVE" | "EXPIRING_SOON" | "EXPIRED" | "INACTIVE" | "UNKNOWN";
  label: string;
  detail: string;
  tone: "emerald" | "amber" | "red" | "neutral";
}

export const UNKNOWN_SUBSCRIPTION_BADGE: SubscriptionBadge = {
  code: "UNKNOWN",
  label: "نامشخص",
  detail: "اطلاعات اشتراک در دسترس نیست",
  tone: "neutral",
};

export function getSubscriptionBadge(
  sub:
    | Pick<VenueSubscriptionOut, "is_active" | "days_remaining" | "has_ever_subscribed">
    | null
    | undefined
): SubscriptionBadge {
  if (!sub) {
    return UNKNOWN_SUBSCRIPTION_BADGE;
  }
  if (sub.is_active) {
    if (sub.days_remaining <= 7) {
      return {
        code: "EXPIRING_SOON",
        label: "در حال انقضا",
        detail: `${sub.days_remaining} روز باقی‌مانده`,
        tone: "amber",
      };
    }
    return {
      code: "ACTIVE",
      label: "فعال",
      detail: `${sub.days_remaining} روز باقی‌مانده`,
      tone: "emerald",
    };
  }

  if (sub.has_ever_subscribed) {
    return {
      code: "EXPIRED",
      label: "منقضی‌شده",
      detail: "اشتراک منقضی شده است",
      tone: "red",
    };
  }

  return {
    code: "INACTIVE",
    label: "غیرفعال",
    detail: "اشتراک فعال نیست",
    tone: "red",
  };
}

export function getPanoramaStatusLabel(status: string | null): string {
  switch (status) {
    case "READY":
      return "آماده نمایش";
    case "PROCESSING":
      return "در حال پردازش";
    case "UPLOADED":
      return "بارگذاری‌شده";
    case "FAILED":
      return "خطا در پردازش";
    default:
      return "بدون تصویر ۳۶۰";
  }
}

export function getBookingStatusLabel(status: string): string {
  switch (status) {
    case "CONFIRMED":
      return "تایید شده";
    case "PENDING_PAYMENT":
      return "در انتظار پرداخت";
    case "CANCELLED":
      return "لغو شده";
    case "EXPIRED":
      return "منقضی شده";
    case "COMPLETED":
      return "تکمیل شده";
    case "INITIATED":
      return "آغاز شده";
    default:
      return status;
  }
}

export function formatMaskedPhone(phone: string): string {
  const trimmed = phone.trim();
  if (!trimmed) return "***";
  if (trimmed.includes("*")) return trimmed;
  if (trimmed.length >= 7) {
    return `${trimmed.slice(0, 4)}***${trimmed.slice(-3)}`;
  }
  return "***";
}

const TEHRAN_WEEKDAY_MAP: Record<string, number> = {
  Mon: 0,
  Tue: 1,
  Wed: 2,
  Thu: 3,
  Fri: 4,
  Sat: 5,
  Sun: 6,
};

function getTehranWeekday(date: Date): number {
  const short = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Tehran",
    weekday: "short",
  }).format(date);
  return TEHRAN_WEEKDAY_MAP[short] ?? 0;
}

function getTehranMinutesFromMidnight(date: Date): number {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Tehran",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const hour = Number(parts.find((p) => p.type === "hour")?.value ?? "0");
  const minute = Number(parts.find((p) => p.type === "minute")?.value ?? "0");
  return (hour === 24 ? 0 : hour) * 60 + minute;
}

function parseHhMmToMinutes(hhmm: string): number | null {
  const match = /^(\d{2}):(\d{2})/.exec(hhmm.trim());
  if (!match) return null;
  const h = Number(match[1]);
  const m = Number(match[2]);
  if (!Number.isInteger(h) || !Number.isInteger(m)) return null;
  return h * 60 + m;
}

export interface BlockedSlotValidationResult {
  valid: boolean;
  error: string | null;
}

export type BlockedSlotOperatingHoursInput = Pick<OperatingHoursOut, "open_time"> &
  Partial<Pick<OperatingHoursOut, "weekday" | "close_time" | "crosses_midnight">>;

/**
 * Validate a BlockedSlot start instant against past-time, weekday operating hours,
 * close_time / crosses_midnight bounds, and 120-minute (90+30) grid alignment.
 */
export function validateBlockedSlotInput(
  slotStartIso: string,
  operatingHours: BlockedSlotOperatingHoursInput[] = [],
  nowMs: number = Date.now()
): BlockedSlotValidationResult {
  const startMs = Date.parse(slotStartIso);
  if (Number.isNaN(startMs)) {
    return { valid: false, error: "زمان اسلات معتبر نیست." };
  }

  if (startMs <= nowMs) {
    return { valid: false, error: "امکان مسدود کردن اسلات گذشته وجود ندارد." };
  }

  const startDate = new Date(startMs);
  if (startDate.getUTCSeconds() !== 0 || startDate.getUTCMilliseconds() !== 0) {
    return { valid: false, error: "زمان اسلات با بازه کاری تراز نیست." };
  }

  const tehranMinutes = getTehranMinutesFromMidnight(startDate);
  if (operatingHours.length > 0) {
    const tehranWeekday = getTehranWeekday(startDate);
    const prevWeekday = (tehranWeekday + 6) % 7;
    const hasWeekdayInfo = operatingHours.some((oh) => oh.weekday !== undefined);
    const matchingDayHours = hasWeekdayInfo
      ? operatingHours.filter(
          (oh) =>
            oh.weekday === tehranWeekday ||
            (oh.crosses_midnight === true && oh.weekday === prevWeekday)
        )
      : operatingHours;

    if (matchingDayHours.length === 0) {
      return { valid: false, error: "مجموعه در این روز هفته فعال نیست." };
    }

    const matchesOpening = matchingDayHours.some((oh) => {
      const openMinutes = parseHhMmToMinutes(oh.open_time);
      if (openMinutes === null) return false;

      const isPrevDayCrossMidnight =
        hasWeekdayInfo && oh.weekday === prevWeekday && oh.crosses_midnight === true;
      const slotRelativeStart = isPrevDayCrossMidnight ? tehranMinutes + 24 * 60 : tehranMinutes;
      const diff = slotRelativeStart - openMinutes;
      if (diff < 0 || diff % 120 !== 0) return false;

      if (oh.close_time !== undefined) {
        const rawCloseMinutes = parseHhMmToMinutes(oh.close_time);
        if (rawCloseMinutes === null) return false;
        const effectiveCloseMinutes =
          oh.crosses_midnight || rawCloseMinutes <= openMinutes
            ? rawCloseMinutes + 24 * 60
            : rawCloseMinutes;
        if (slotRelativeStart + 120 > effectiveCloseMinutes) {
          return false;
        }
      }
      return true;
    });

    if (!matchesOpening) {
      return { valid: false, error: "زمان اسلات با بازه ۱۲۰ دقیقه‌ای مجموعه تراز نیست." };
    }
  } else if (tehranMinutes % 120 !== 0) {
    return { valid: false, error: "زمان اسلات با بازه ۱۲۰ دقیقه‌ای تراز نیست." };
  }

  return { valid: true, error: null };
}

export function isForbiddenError(err: unknown): boolean {
  return err instanceof ApiError && err.status === 403;
}
