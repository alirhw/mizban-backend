import { ApiError, type BookingCancelOut, type CustomerBookingOut } from "@/lib/api";
import { formatToman } from "@/lib/panorama";

export const WALLET_NON_WITHDRAWABLE_NOTE =
  "موجودی کیف پول غیرقابل برداشت نقدی است و فقط برای رزروهای آینده در میزبان قابل استفاده است.";

export type CancelStep = "idle" | "confirming" | "cancelling" | "done" | "failed";

export interface CancelState {
  step: CancelStep;
  targetBooking: CustomerBookingOut | null;
  result: BookingCancelOut | null;
  errorMessage: string | null;
}

export const INITIAL_CANCEL_STATE: CancelState = {
  step: "idle",
  targetBooking: null,
  result: null,
  errorMessage: null,
};

export type CancelAction =
  | { type: "OPEN_CONFIRM"; booking: CustomerBookingOut }
  | { type: "START_CANCEL" }
  | { type: "CANCEL_SUCCEEDED"; result: BookingCancelOut }
  | { type: "CANCEL_FAILED"; error: unknown }
  | { type: "RESET" };

export function cancelReducer(state: CancelState, action: CancelAction): CancelState {
  switch (action.type) {
    case "OPEN_CONFIRM":
      return {
        step: "confirming",
        targetBooking: action.booking,
        result: null,
        errorMessage: null,
      };
    case "START_CANCEL":
      if (state.step !== "confirming" && state.step !== "failed") return state;
      return { ...state, step: "cancelling", errorMessage: null };
    case "CANCEL_SUCCEEDED":
      if (state.step !== "cancelling") return state;
      return {
        ...state,
        step: "done",
        result: action.result,
        errorMessage: null,
      };
    case "CANCEL_FAILED":
      if (state.step !== "cancelling") return state;
      return {
        ...state,
        step: "failed",
        errorMessage: mapMyBookingsErrorToPersian(action.error),
      };
    case "RESET":
      return { ...INITIAL_CANCEL_STATE };
    default:
      return state;
  }
}

export interface CancelConfirmationSummary {
  hasRefund: boolean;
  refundText: string;
  addonsNote: string;
}

export function getCancelConfirmationSummary(
  booking: Pick<CustomerBookingOut, "status" | "is_cancellable" | "cancel_refund_toman">
): CancelConfirmationSummary {
  const addonsNote = "هزینه افزودنی‌های طراحی که پرداخت حضوری در کافه است، مشمول بازپرداخت نیست.";

  if (booking.status === "CONFIRMED" && booking.cancel_refund_toman > 0) {
    return {
      hasRefund: true,
      refundText: `مبلغ ${formatToman(booking.cancel_refund_toman)} (۱۰۰٪ هزینه رزرو آنلاین) به کیف پول درون‌برنامه‌ای شما برمی‌گردد.`,
      addonsNote,
    };
  }

  if (booking.status === "PENDING_PAYMENT") {
    return {
      hasRefund: false,
      refundText: "بدون بازپرداخت — هنوز مبلغی آنلاین پرداخت نشده است و فقط قفل میز آزاد می‌شود.",
      addonsNote,
    };
  }

  return {
    hasRefund: false,
    refundText: "لغو این رزرو امکان‌پذیر نیست یا مشمول بازپرداخت کیف پول نمی‌شود.",
    addonsNote,
  };
}

export function mapMyBookingsErrorToPersian(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.errorCode) {
      case "CANCELLATION_WINDOW_CLOSED":
        return "لغو رزرو با بازپرداخت فقط تا ۳۶ ساعت پیش از زمان شروع اسلات امکان‌پذیر است.";
      case "BOOKING_NOT_CANCELLABLE":
        return "این رزرو در وضعیت فعلی قابل لغو نیست.";
      case "RECEIPT_NOT_AVAILABLE":
        return "رسید فقط برای رزروهای تاییدشده یا تکمیل‌شده در دسترس است.";
      default:
        break;
    }
  }
  return "خطایی در پردازش درخواست رخ داد؛ لطفاً دوباره تلاش کنید.";
}

export function getWalletDirectionLabel(direction: string): string {
  return direction === "credit" ? "واریز (بازپرداخت)" : "برداشت";
}

export function getCustomerBookingStatusLabel(status: string): string {
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
