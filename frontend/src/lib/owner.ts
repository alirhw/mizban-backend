import { ApiError, type OperatingHoursOut, type VenueSubscriptionOut } from "@/lib/api";

export const OWNER_EMPTY_VENUES_TEXT = "هنوز ونیویی ثبت نکرده‌اید";
export const OWNER_FORBIDDEN_TEXT = "دسترسی ندارید";

export interface SubscriptionBadge {
  code: "ACTIVE" | "EXPIRING_SOON" | "EXPIRED" | "INACTIVE";
  label: string;
  detail: string;
  tone: "emerald" | "amber" | "red";
}

export function getSubscriptionBadge(
  sub: Pick<VenueSubscriptionOut, "is_active" | "days_remaining" | "has_ever_subscribed">
): SubscriptionBadge {
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

/**
 * Validate a BlockedSlot start instant against past-time and 120-minute (90+30) grid alignment.
 */
export function validateBlockedSlotInput(
  slotStartIso: string,
  operatingHours: Pick<OperatingHoursOut, "open_time">[] = [],
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

  if (operatingHours.length > 0) {
    const tehranMinutes = getTehranMinutesFromMidnight(startDate);
    const matchesAnyOpening = operatingHours.some((oh) => {
      const openMinutes = parseHhMmToMinutes(oh.open_time);
      if (openMinutes === null) return false;
      const diff = tehranMinutes - openMinutes;
      return diff >= 0 && diff % 120 === 0;
    });
    if (!matchesAnyOpening) {
      return { valid: false, error: "زمان اسلات با بازه ۱۲۰ دقیقه‌ای مجموعه تراز نیست." };
    }
  } else {
    const tehranMinutes = getTehranMinutesFromMidnight(startDate);
    if (tehranMinutes % 30 !== 0) {
      return { valid: false, error: "زمان اسلات با بازه کاری تراز نیست." };
    }
  }

  return { valid: true, error: null };
}

export function isForbiddenError(err: unknown): boolean {
  return err instanceof ApiError && err.status === 403;
}
