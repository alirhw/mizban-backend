import { describe, expect, it } from "vitest";

import { ApiError } from "../api";
import {
  cancelReducer,
  getCancelConfirmationSummary,
  getCustomerBookingStatusLabel,
  getWalletDirectionLabel,
  INITIAL_CANCEL_STATE,
  mapMyBookingsErrorToPersian,
  WALLET_NON_WITHDRAWABLE_NOTE,
} from "../my-bookings";
import { formatToman } from "../panorama";

const CONFIRMED_BOOKING = {
  booking_id: 10,
  venue_name: "کافه نمونه",
  venue_slug: "sample-cafe-dev",
  table_number: "میز ۱",
  status: "CONFIRMED",
  slot_date: "2026-11-30",
  jalali_date: "۱۴۰۵/۰۹/۰۹",
  slot_start_time: "15:00:00",
  start_at: "2026-11-30T11:30:00Z",
  end_at: "2026-11-30T13:00:00Z",
  start_jalali: "۱۴۰۵/۰۹/۰۹ ۱۵:۰۰",
  end_jalali: "۱۴۰۵/۰۹/۰۹ ۱۶:۳۰",
  amount_online_toman: 120_000,
  amount_in_person_toman: 80_000,
  is_cancellable: true,
  cancel_refund_toman: 120_000,
  created_at: "2026-11-25T10:00:00Z",
};

describe("cancel state machine (PH-06-03)", () => {
  it("transitions idle -> confirming -> cancelling -> done and resets", () => {
    let s = cancelReducer(INITIAL_CANCEL_STATE, {
      type: "OPEN_CONFIRM",
      booking: CONFIRMED_BOOKING,
    });
    expect(s.step).toBe("confirming");

    s = cancelReducer(s, { type: "START_CANCEL" });
    expect(s.step).toBe("cancelling");

    s = cancelReducer(s, {
      type: "CANCEL_SUCCEEDED",
      result: {
        booking_id: 10,
        status: "CANCELLED",
        refunded_to_wallet_toman: 120_000,
        wallet_balance_toman: 120_000,
      },
    });
    expect(s.step).toBe("done");
    expect(s.result?.refunded_to_wallet_toman).toBe(120_000);

    s = cancelReducer(s, { type: "RESET" });
    expect(s).toEqual(INITIAL_CANCEL_STATE);
  });

  it("transitions cancelling -> failed with safe Persian error", () => {
    let s = cancelReducer(INITIAL_CANCEL_STATE, {
      type: "OPEN_CONFIRM",
      booking: CONFIRMED_BOOKING,
    });
    s = cancelReducer(s, { type: "START_CANCEL" });
    s = cancelReducer(s, {
      type: "CANCEL_FAILED",
      error: new ApiError(400, "CANCELLATION_WINDOW_CLOSED", "Window closed"),
    });
    expect(s.step).toBe("failed");
    expect(s.errorMessage).toContain("۳۶ ساعت");
    expect(s.errorMessage).not.toContain("CANCELLATION_WINDOW_CLOSED");
  });
});

describe("cancel confirmation copy (BR-004)", () => {
  it("shows wallet refund amount for CONFIRMED >= 36h and notes non-refundable add-ons", () => {
    const summary = getCancelConfirmationSummary(CONFIRMED_BOOKING);
    expect(summary.hasRefund).toBe(true);
    expect(summary.refundText).toContain("کیف پول");
    expect(summary.refundText).toContain(formatToman(120_000));
    expect(summary.addonsNote).toContain("افزودنی");
  });

  it("shows بدون بازپرداخت for PENDING_PAYMENT bookings", () => {
    const summary = getCancelConfirmationSummary({
      status: "PENDING_PAYMENT",
      is_cancellable: true,
      cancel_refund_toman: 0,
    });
    expect(summary.hasRefund).toBe(false);
    expect(summary.refundText).toContain("بدون بازپرداخت");
    expect(summary.addonsNote).toContain("افزودنی");
  });
});

describe("error mapping & wallet helpers (PH-06-03)", () => {
  it("maps CANCELLATION_WINDOW_CLOSED, 409 BOOKING_NOT_CANCELLABLE, and RECEIPT_NOT_AVAILABLE without leaking codes", () => {
    const m36 = mapMyBookingsErrorToPersian(
      new ApiError(400, "CANCELLATION_WINDOW_CLOSED", "Under 36h")
    );
    expect(m36).toContain("۳۶ ساعت");
    expect(m36).not.toContain("CANCELLATION_WINDOW_CLOSED");

    const m409 = mapMyBookingsErrorToPersian(
      new ApiError(409, "BOOKING_NOT_CANCELLABLE", "Expired")
    );
    expect(m409).toContain("قابل لغو نیست");
    expect(m409).not.toContain("BOOKING_NOT_CANCELLABLE");

    const mRec = mapMyBookingsErrorToPersian(
      new ApiError(409, "RECEIPT_NOT_AVAILABLE", "Not settled")
    );
    expect(mRec).toContain("تاییدشده");
    expect(mRec).not.toContain("RECEIPT_NOT_AVAILABLE");
  });

  it("renders non-withdrawable wallet copy, direction labels, and Persian booking statuses", () => {
    expect(WALLET_NON_WITHDRAWABLE_NOTE).toContain("غیرقابل برداشت");
    expect(getWalletDirectionLabel("credit")).toContain("واریز");
    expect(getWalletDirectionLabel("debit")).toContain("برداشت");
    expect(getCustomerBookingStatusLabel("CONFIRMED")).toBe("تایید شده");
    expect(getCustomerBookingStatusLabel("PENDING_PAYMENT")).toBe("در انتظار پرداخت");
    expect(getCustomerBookingStatusLabel("CANCELLED")).toBe("لغو شده");
    expect(getCustomerBookingStatusLabel("EXPIRED")).toBe("منقضی شده");
  });
});
