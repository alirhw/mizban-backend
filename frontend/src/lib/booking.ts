import { ApiError, type DesignAddonOut } from "./api";

export type BookingStep =
  | "idle"
  | "table"
  | "slot"
  | "addons"
  | "review"
  | "locked"
  | "paying"
  | "confirmed"
  | "failed"
  | "expired";

export interface BookingState {
  step: BookingStep;
  tablePinId: number | null;
  slotDate: string | null;
  slotStartIso: string | null;
  slotEndIso: string | null;
  addonIds: number[];
  bookingId: number | null;
  lockExpiresAt: string | null;
  amountOnlineToman: number | null;
  amountInPersonToman: number | null;
  errorMessage: string | null;
}

export const INITIAL_BOOKING_STATE: BookingState = {
  step: "idle",
  tablePinId: null,
  slotDate: null,
  slotStartIso: null,
  slotEndIso: null,
  addonIds: [],
  bookingId: null,
  lockExpiresAt: null,
  amountOnlineToman: null,
  amountInPersonToman: null,
  errorMessage: null,
};

export type BookingAction =
  | { type: "START" }
  | { type: "SELECT_TABLE"; tablePinId: number }
  | {
      type: "SELECT_SLOT";
      slotDate: string;
      slotStartIso: string;
      slotEndIso: string;
    }
  | { type: "SET_ADDONS"; addonIds: number[] }
  | { type: "TOGGLE_ADDON"; addonId: number }
  | { type: "PROCEED_TO_REVIEW" }
  | { type: "BACK_TO_TABLE" }
  | { type: "BACK_TO_SLOT" }
  | { type: "BACK_TO_ADDONS" }
  | {
      type: "LOCK_ACQUIRED";
      bookingId: number;
      lockExpiresAt: string | null;
      amountOnlineToman: number;
      amountInPersonToman: number;
    }
  | { type: "START_PAYMENT" }
  | { type: "PAYMENT_SUCCEEDED" }
  | { type: "PAYMENT_FAILED"; error?: unknown }
  | { type: "RETRY_PAYMENT" }
  | { type: "LOCK_EXPIRED" }
  | { type: "RESTART" };

const ALLOWED_TRANSITIONS: Record<BookingStep, ReadonlySet<BookingStep>> = {
  idle: new Set(["table"]),
  table: new Set(["slot", "idle"]),
  slot: new Set(["addons", "table", "idle"]),
  addons: new Set(["review", "slot", "table", "idle"]),
  review: new Set(["locked", "addons", "slot", "table", "failed", "idle"]),
  locked: new Set(["paying", "expired", "failed", "idle"]),
  paying: new Set(["confirmed", "failed", "expired"]),
  confirmed: new Set(["idle"]),
  failed: new Set(["paying", "locked", "expired", "idle"]),
  expired: new Set(["idle", "table"]),
};

export function canTransitionBookingStep(from: BookingStep, to: BookingStep): boolean {
  return ALLOWED_TRANSITIONS[from].has(to);
}

/**
 * Pure state machine reducer for the customer booking flow.
 */
export function bookingReducer(state: BookingState, action: BookingAction): BookingState {
  switch (action.type) {
    case "START": {
      if (!canTransitionBookingStep(state.step, "table")) return state;
      return { ...state, step: "table", errorMessage: null };
    }

    case "SELECT_TABLE": {
      if (state.step !== "table" && !canTransitionBookingStep(state.step, "slot")) {
        return state;
      }
      const tableChanged = state.tablePinId !== action.tablePinId;
      return {
        ...state,
        step: "slot",
        tablePinId: action.tablePinId,
        slotDate: tableChanged ? null : state.slotDate,
        slotStartIso: tableChanged ? null : state.slotStartIso,
        slotEndIso: tableChanged ? null : state.slotEndIso,
        errorMessage: null,
      };
    }

    case "SELECT_SLOT": {
      if (state.step !== "slot" && !canTransitionBookingStep(state.step, "addons")) {
        return state;
      }
      return {
        ...state,
        step: "addons",
        slotDate: action.slotDate,
        slotStartIso: action.slotStartIso,
        slotEndIso: action.slotEndIso,
        errorMessage: null,
      };
    }

    case "SET_ADDONS": {
      if (state.step !== "addons" && state.step !== "review") return state;
      return {
        ...state,
        addonIds: Array.from(new Set(action.addonIds)),
      };
    }

    case "TOGGLE_ADDON": {
      if (state.step !== "addons" && state.step !== "review") return state;
      const exists = state.addonIds.includes(action.addonId);
      return {
        ...state,
        addonIds: exists
          ? state.addonIds.filter((id) => id !== action.addonId)
          : [...state.addonIds, action.addonId],
      };
    }

    case "PROCEED_TO_REVIEW": {
      if (!canTransitionBookingStep(state.step, "review")) return state;
      return { ...state, step: "review", errorMessage: null };
    }

    case "BACK_TO_TABLE": {
      if (!canTransitionBookingStep(state.step, "table")) return state;
      return { ...state, step: "table", errorMessage: null };
    }

    case "BACK_TO_SLOT": {
      if (!canTransitionBookingStep(state.step, "slot")) return state;
      return { ...state, step: "slot", errorMessage: null };
    }

    case "BACK_TO_ADDONS": {
      if (!canTransitionBookingStep(state.step, "addons")) return state;
      return { ...state, step: "addons", errorMessage: null };
    }

    case "LOCK_ACQUIRED": {
      if (!canTransitionBookingStep(state.step, "locked")) return state;
      return {
        ...state,
        step: "locked",
        bookingId: action.bookingId,
        lockExpiresAt: action.lockExpiresAt,
        amountOnlineToman: action.amountOnlineToman,
        amountInPersonToman: action.amountInPersonToman,
        errorMessage: null,
      };
    }

    case "START_PAYMENT": {
      if (!canTransitionBookingStep(state.step, "paying")) return state;
      return { ...state, step: "paying", errorMessage: null };
    }

    case "PAYMENT_SUCCEEDED": {
      if (!canTransitionBookingStep(state.step, "confirmed")) return state;
      return { ...state, step: "confirmed", errorMessage: null };
    }

    case "PAYMENT_FAILED": {
      if (!canTransitionBookingStep(state.step, "failed")) return state;
      return {
        ...state,
        step: "failed",
        errorMessage: mapBookingErrorToPersian(action.error),
      };
    }

    case "RETRY_PAYMENT": {
      if (state.step !== "failed") return state;
      if (state.lockExpiresAt && computeLockRemainingSeconds(state.lockExpiresAt) <= 0) {
        return {
          ...state,
          step: "expired",
          errorMessage: "زمان قفل رزرو به پایان رسید؛ لطفاً دوباره تلاش کنید.",
        };
      }
      return { ...state, step: "locked", errorMessage: null };
    }

    case "LOCK_EXPIRED": {
      if (!canTransitionBookingStep(state.step, "expired")) return state;
      return {
        ...state,
        step: "expired",
        errorMessage: "زمان قفل رزرو به پایان رسید؛ لطفاً دوباره تلاش کنید.",
      };
    }

    case "RESTART": {
      return { ...INITIAL_BOOKING_STATE };
    }

    default: {
      return state;
    }
  }
}

export interface BookingSummary {
  onlineTotalToman: number;
  inPersonTotalToman: number;
  grandTotalToman: number;
  inPersonLabel: string;
  addonCount: number;
}

/**
 * Compute split-payment booking totals (BR-003):
 * - Online: table reservation fee only
 * - In-person: sum of selected design add-ons ('بدون افزودنی' when 0 addons)
 */
export function computeBookingSummary(
  tableFeeToman: number,
  selectedAddons: ReadonlyArray<Pick<DesignAddonOut, "fee">>
): BookingSummary {
  const onlineTotalToman = Math.max(0, tableFeeToman);
  const inPersonTotalToman = selectedAddons.reduce((sum, addon) => sum + Math.max(0, addon.fee), 0);
  const addonCount = selectedAddons.length;

  return {
    onlineTotalToman,
    inPersonTotalToman,
    grandTotalToman: onlineTotalToman + inPersonTotalToman,
    inPersonLabel: addonCount === 0 ? "بدون افزودنی" : "پرداخت در محل برای افزودنی‌های طراحی",
    addonCount,
  };
}

/**
 * Compute remaining seconds for a booking lock, clamped to 0 at or after expiry.
 */
export function computeLockRemainingSeconds(
  lockExpiresAtIso: string | null | undefined,
  nowMs: number = Date.now()
): number {
  if (!lockExpiresAtIso) {
    return 0;
  }
  const expiresMs = Date.parse(lockExpiresAtIso);
  if (Number.isNaN(expiresMs) || !Number.isFinite(nowMs)) {
    return 0;
  }
  return Math.max(0, Math.floor((expiresMs - nowMs) / 1000));
}

/**
 * Format remaining seconds as MM:SS, reaching '00:00' at expiry.
 */
export function formatCountdownMmSs(seconds: number): string {
  const safeSeconds = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  const minutes = Math.floor(safeSeconds / 60);
  const remSeconds = safeSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remSeconds).padStart(2, "0")}`;
}

function extractErrorCode(err: unknown): string | null {
  if (err instanceof ApiError) {
    return err.errorCode;
  }
  if (err && typeof err === "object") {
    const record = err as Record<string, unknown>;
    if (typeof record.errorCode === "string") return record.errorCode;
    if (typeof record.error_code === "string") return record.error_code;
  }
  return null;
}

/**
 * Map backend booking/payment errors to safe, user-friendly Persian messages.
 * Never exposes raw error_code values or stack traces.
 */
export function mapBookingErrorToPersian(err: unknown): string {
  const code = extractErrorCode(err);

  if (code === "SLOT_ALREADY_RESERVED") {
    return "این اسلات همین‌الان رزرو شد؛ یک اسلات دیگر انتخاب کنید";
  }

  if (code === "LEAD_TIME_VIOLATION") {
    return "رزرو میز فقط تا ۲۴ ساعت پیش از زمان شروع اسلات امکان‌پذیر است.";
  }

  if (code === "BOOKING_LOCK_EXPIRED" || code === "LOCK_EXPIRED") {
    return "زمان قفل رزرو به پایان رسید؛ لطفاً دوباره اسلات را انتخاب کنید.";
  }

  if (code === "WALLET_INSUFFICIENT_BALANCE") {
    return "موجودی کیف پول برای پرداخت هزینه رزرو میز کافی نیست؛ می‌توانید از درگاه پرداخت آنلاین استفاده کنید.";
  }

  if (
    code &&
    (code.startsWith("PAYMENT_") || code === "GATEWAY_ERROR" || code === "BILLING_ERROR")
  ) {
    return "پرداخت ناموفق بود؛ تا پایان زمان قفل رزرو می‌توانید دوباره تلاش کنید.";
  }

  return "خطایی در پردازش رزرو رخ داد؛ لطفاً دوباره تلاش کنید.";
}

export type PaymentMethodChoice = "wallet" | "gateway";

export interface WalletOptionAvailability {
  enabled: boolean;
  reason: "loading" | "unavailable" | "insufficient_balance" | "ready";
  note: string | null;
}

export function resolveWalletOptionAvailability(params: {
  loading: boolean;
  error: boolean;
  balanceToman: number | null;
  reservationFeeToman: number;
  forceInsufficient?: boolean;
}): WalletOptionAvailability {
  if (params.loading) {
    return {
      enabled: false,
      reason: "loading",
      note: "در حال بررسی موجودی کیف پول...",
    };
  }
  if (params.error || params.balanceToman === null) {
    return {
      enabled: false,
      reason: "unavailable",
      note: "امکان دریافت موجودی کیف پول وجود ندارد؛ می‌توانید از درگاه پرداخت آنلاین استفاده کنید.",
    };
  }
  if (params.forceInsufficient || params.balanceToman < params.reservationFeeToman) {
    return {
      enabled: false,
      reason: "insufficient_balance",
      note: "موجودی کیف پول برای پرداخت هزینه رزرو میز کافی نیست.",
    };
  }
  return {
    enabled: true,
    reason: "ready",
    note: null,
  };
}

export function isInsufficientWalletBalanceError(err: unknown): boolean {
  return extractErrorCode(err) === "WALLET_INSUFFICIENT_BALANCE";
}

export interface BookingResumeParams {
  pinId: number;
  slotDate: string;
  slotStartIso: string;
  slotLabel: string | null;
  addonIds: number[];
  step: "slot" | "addons" | "review";
}

export function buildBookingReturnUrl(
  venueSlug: string,
  params: {
    pinId: number;
    slotDate: string | null;
    slotStartIso: string | null;
    slotLabel?: string | null;
    addonIds: number[];
    step: "slot" | "addons" | "review";
  }
): string {
  const search = new URLSearchParams();
  search.set("pin", String(params.pinId));
  search.set("step", params.step);
  if (params.slotDate) {
    search.set("date", params.slotDate);
  }
  if (params.slotStartIso) {
    search.set("slot", params.slotStartIso);
  }
  if (params.slotLabel) {
    search.set("slotLabel", params.slotLabel);
  }
  if (params.addonIds.length > 0) {
    search.set("addons", params.addonIds.join(","));
  }
  return `/venues/${encodeURIComponent(venueSlug)}?${search.toString()}`;
}

export const SLOT_DURATION_MINUTES = 90;

export function computeSlotEndIso(slotStartIso: string): string {
  const startMs = Date.parse(slotStartIso);
  if (!Number.isFinite(startMs)) {
    return slotStartIso;
  }
  return new Date(startMs + SLOT_DURATION_MINUTES * 60 * 1000).toISOString();
}

function isValidIsoCalendarDate(dateStr: string): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr);
  if (!match) {
    return false;
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const dt = new Date(Date.UTC(year, month - 1, day));
  return (
    dt.getUTCFullYear() === year &&
    dt.getUTCMonth() === month - 1 &&
    dt.getUTCDate() === day
  );
}

export function parseBookingResumeParams(
  searchParams: Pick<URLSearchParams, "get">,
  availablePinIds: number[],
  availableAddonIds: number[]
): BookingResumeParams | null {
  const rawPin = searchParams.get("pin");
  if (!rawPin) return null;

  const pinId = Number(rawPin);
  if (!Number.isInteger(pinId) || !availablePinIds.includes(pinId)) {
    return null;
  }

  const slotDate = searchParams.get("date") ?? "";
  const slotStartIso = searchParams.get("slot") ?? "";
  if (!isValidIsoCalendarDate(slotDate) || !slotStartIso || !Number.isFinite(Date.parse(slotStartIso))) {
    return null;
  }

  const rawStep = searchParams.get("step");
  const step: "slot" | "addons" | "review" =
    rawStep === "review" ? "review" : "addons";

  const rawAddons = searchParams.get("addons") ?? "";
  const addonSet = new Set(availableAddonIds);
  const addonIds = rawAddons
    .split(",")
    .map((part) => Number(part.trim()))
    .filter((id) => Number.isInteger(id) && id > 0 && addonSet.has(id));

  const slotLabel = searchParams.get("slotLabel");

  return {
    pinId,
    slotDate,
    slotStartIso,
    slotLabel: slotLabel && slotLabel.trim() ? slotLabel.trim() : null,
    addonIds: Array.from(new Set(addonIds)),
    step,
  };
}

export function resolveCallbackReceiptConfirmed(
  receipt: { status: string } | null,
  receiptError: string | null
): boolean {
  return Boolean(
    !receiptError && receipt && (receipt.status === "CONFIRMED" || receipt.status === "COMPLETED")
  );
}

export function getOrCreateBookingIdempotencyKey(
  existing: { bookingId: number; key: string } | null,
  bookingId: number,
  mint: () => string
): { bookingId: number; key: string } {
  if (existing && existing.bookingId === bookingId) {
    return existing;
  }
  return { bookingId, key: mint() };
}
