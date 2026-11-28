// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";

import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import BookingCallbackPage from "@/app/bookings/callback/page";
import MyBookingsPage from "@/app/my-bookings/page";
import { BookingFlow } from "@/components/BookingFlow";
import {
  cancelBooking,
  getBookingReceipt,
  getMyWallet,
  initiateBooking,
  initiatePayment,
  listMyBookings,
  listMyReviews,
  listVenueSlots,
  payBookingWithWallet,
  type BookingInitiateOut,
  type CustomerBookingOut,
  type PaymentInitiateOut,
  type PaymentTransactionOut,
  type PublicTablePinOut,
  type ReviewMineOut,
  type SlotOut,
  type SplitReceiptOut,
  type WalletMeOut,
} from "@/lib/api";
import { computeSlotEndIso } from "@/lib/booking";

type CancelResult = Awaited<ReturnType<typeof cancelBooking>>;

const mockRouter = {
  push: vi.fn(),
  replace: vi.fn(),
  prefetch: vi.fn(),
};

let mockSearchParams = new URLSearchParams("");

let mockAuthState = {
  user: {
    id: 1,
    phone_number: "09123456789",
    full_name: "علی",
    role: "CUSTOMER",
  } as { id: number; phone_number: string; full_name: string; role: string } | null,
  loading: false,
};

vi.mock("next/navigation", () => ({
  useRouter: () => mockRouter,
  useSearchParams: () => mockSearchParams,
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
  } & React.AnchorHTMLAttributes<HTMLAnchorElement>) =>
    React.createElement("a", { href, ...rest }, children),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => mockAuthState,
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    cancelBooking: vi.fn(),
    getBookingReceipt: vi.fn(),
    getMyWallet: vi.fn(),
    initiateBooking: vi.fn(),
    initiatePayment: vi.fn(),
    listMyBookings: vi.fn(),
    listMyReviews: vi.fn(),
    listVenueSlots: vi.fn().mockResolvedValue([]),
    payBookingWithWallet: vi.fn(),
  };
});

const mockedCancelBooking = vi.mocked(cancelBooking);
const mockedGetBookingReceipt = vi.mocked(getBookingReceipt);
const mockedGetMyWallet = vi.mocked(getMyWallet);
const mockedInitiateBooking = vi.mocked(initiateBooking);
const mockedInitiatePayment = vi.mocked(initiatePayment);
const mockedListMyBookings = vi.mocked(listMyBookings);
const mockedListMyReviews = vi.mocked(listMyReviews);
const mockedListVenueSlots = vi.mocked(listVenueSlots);
const mockedPayBookingWithWallet = vi.mocked(payBookingWithWallet);

const PIN_FIXTURE: PublicTablePinOut = {
  id: 10,
  table_number: "7",
  capacity: 4,
  pitch: 0,
  yaw: 0,
  description: "",
  reservation_fee_toman: 150_000,
  is_smoking: false,
};

function makeBooking(id: number, overrides: Partial<CustomerBookingOut> = {}): CustomerBookingOut {
  return {
    booking_id: id,
    venue_name: `کافه ${id}`,
    venue_slug: `cafe-${id}`,
    table_number: String(id),
    status: "CONFIRMED",
    slot_date: "2026-11-20",
    jalali_date: "۱۴۰۵/۰۸/۲۹",
    slot_start_time: "10:00",
    start_at: "2026-11-20T10:00:00Z",
    end_at: "2026-11-20T11:30:00Z",
    start_jalali: "۱۴۰۵/۰۸/۲۹ ۱۳:۳۰",
    end_jalali: "۱۴۰۵/۰۸/۲۹ ۱۵:۰۰",
    amount_online_toman: 150_000,
    amount_in_person_toman: 0,
    is_cancellable: false,
    cancel_refund_toman: 0,
    created_at: "2026-11-19T10:00:00Z",
    ...overrides,
  };
}

function makeReceipt(bookingId: number): SplitReceiptOut {
  return {
    booking_id: bookingId,
    status: "CONFIRMED",
    venue_name: `کافه ${bookingId}`,
    venue_slug: `cafe-${bookingId}`,
    table_number: String(bookingId),
    start_at: "2026-11-20T10:00:00Z",
    end_at: "2026-11-20T11:30:00Z",
    slot_date: "2026-11-20",
    slot_start_time: "10:00",
    jalali_date: "۱۴۰۵/۰۸/۲۹",
    jalali_start_datetime: "۱۴۰۵/۰۸/۲۹ ۱۳:۳۰",
    jalali_end_datetime: "۱۴۰۵/۰۸/۲۹ ۱۵:۰۰",
    paid_online: {
      label: "پرداخت آنلاین",
      description: `هزینه رزرو میز ${bookingId}`,
      amount_online_toman: 150_000,
      provider_name: `sandbox-${bookingId}`,
      card_pan_masked: "6037****1234",
    },
    payable_in_person: {
      label: "پرداخت حضوری",
      items: [],
      total_in_person_toman: 0,
    },
    total_online_toman: 150_000,
    total_in_person_toman: 0,
    grand_total_toman: 150_000,
  };
}

function makeLockedBooking(expiresInMs = 10 * 60 * 1000): BookingInitiateOut {
  const now = Date.now();
  return {
    booking_id: 42,
    id: 42,
    status: "PENDING_PAYMENT",
    venue_id: 1,
    table_pin_id: 10,
    start_at: "2099-01-01T10:00:00Z",
    end_at: "2099-01-01T11:30:00Z",
    slot_date: "2099-01-01",
    slot_start_time: "10:00",
    locked_at: new Date(now).toISOString(),
    lock_expires_at: new Date(now + expiresInMs).toISOString(),
    amount_online_toman: 150_000,
    amount_in_person_toman: 0,
    start_jalali: "۱۴۷۷/۱۰/۱۱ ۱۰:۰۰",
    end_jalali: "۱۴۷۷/۱۰/۱۱ ۱۱:۳۰",
    jalali_start_datetime: "۱۴۷۷/۱۰/۱۱ ۱۰:۰۰",
    jalali_end_datetime: "۱۴۷۷/۱۰/۱۱ ۱۱:۳۰",
    jalali_date: "۱۴۷۷/۱۰/۱۱",
  };
}

describe("F-01 reproduction tests (M1, M6, m30)", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockedListVenueSlots.mockResolvedValue([]);
    mockSearchParams = new URLSearchParams("");
    mockAuthState = {
      user: {
        id: 1,
        phone_number: "09123456789",
        full_name: "علی",
        role: "CUSTOMER",
      },
      loading: false,
    };
  });

  afterEach(() => {
    cleanup();
  });

  it("M1: ignores stale receipt response for booking A when booking B was selected afterwards", async () => {
    mockedListMyBookings.mockResolvedValueOnce([makeBooking(101), makeBooking(102)]);
    mockedGetMyWallet.mockResolvedValueOnce({ balance_toman: 0, entries: [] });
    mockedListMyReviews.mockResolvedValueOnce([]);

    let resolveA!: (value: SplitReceiptOut) => void;
    mockedGetBookingReceipt
      .mockImplementationOnce(
        () =>
          new Promise<SplitReceiptOut>((resolve) => {
            resolveA = resolve;
          })
      )
      .mockResolvedValueOnce(makeReceipt(102));

    render(React.createElement(MyBookingsPage));

    const buttons = await screen.findAllByRole("button", { name: "مشاهده رسید" });
    fireEvent.click(buttons[0]!);
    fireEvent.click(buttons[1]!);

    await waitFor(() => expect(mockedGetBookingReceipt).toHaveBeenCalledTimes(2));
    await act(async () => {
      resolveA(makeReceipt(101));
    });

    await waitFor(() => {
      const card102 = screen.getByText("#102 — کافه 102").closest("div.rounded-xl");
      expect(card102).toHaveTextContent("sandbox-102");
    });
    const card101 = screen.getByText("#101 — کافه 101").closest("div.rounded-xl");
    expect(card101).not.toHaveTextContent("sandbox-101");
  });

  it("M6: does not overwrite manual gateway selection when deferred getMyWallet resolves", async () => {
    const user = userEvent.setup();
    mockedInitiateBooking.mockResolvedValueOnce(makeLockedBooking());

    let resolveWallet!: (value: WalletMeOut) => void;
    mockedGetMyWallet.mockImplementationOnce(
      () =>
        new Promise<WalletMeOut>((resolve) => {
          resolveWallet = resolve;
        })
    );

    render(
      React.createElement(BookingFlow, {
        venueId: 1,
        venueName: "کافه تست",
        venueSlug: "test-cafe",
        designAddons: [],
        selectedPin: PIN_FIXTURE,
        initialResume: {
          pinId: 10,
          slotDate: "2099-01-01",
          slotStartIso: "2099-01-01T10:00:00Z",
          slotLabel: "۱۰:۰۰ تا ۱۱:۳۰",
          addonIds: [],
          step: "review",
        },
      })
    );

    await user.click(screen.getByRole("button", { name: "تایید و قفل موقت میز" }));
    await screen.findByText("میز برای شما به‌صورت موقت قفل شد");

    const radios = screen.getAllByRole("radio") as HTMLInputElement[];
    await user.click(radios[1]!);
    expect(radios[1]).toBeChecked();

    resolveWallet({ balance_toman: 500_000, entries: [] });
    await waitFor(() => expect(screen.getByText(/۵۰۰٬۰۰۰ تومان/)).toBeInTheDocument());
    expect(radios[1]).toBeChecked();
  });

  it("m30: prevents double-submit on rapid double invocation of handleConfirmAndLock and handleRetryPayment", async () => {
    const user = userEvent.setup();
    let resolveLock!: (value: BookingInitiateOut) => void;
    mockedInitiateBooking.mockImplementationOnce(
      () =>
        new Promise<BookingInitiateOut>((resolve) => {
          resolveLock = resolve;
        })
    );
    mockedGetMyWallet.mockResolvedValueOnce({ balance_toman: 0, entries: [] });

    render(
      React.createElement(BookingFlow, {
        venueId: 1,
        venueName: "کافه تست",
        venueSlug: "test-cafe",
        designAddons: [],
        selectedPin: PIN_FIXTURE,
        initialResume: {
          pinId: 10,
          slotDate: "2099-01-01",
          slotStartIso: "2099-01-01T10:00:00Z",
          slotLabel: "۱۰:۰۰ تا ۱۱:۳۰",
          addonIds: [],
          step: "review",
        },
      })
    );

    const lockBtn = screen.getByRole("button", { name: "تایید و قفل موقت میز" });
    act(() => {
      lockBtn.click();
      lockBtn.click();
    });
    expect(mockedInitiateBooking).toHaveBeenCalledTimes(1);

    resolveLock(makeLockedBooking());
    await screen.findByText("میز برای شما به‌صورت موقت قفل شد");

    cleanup();
    vi.clearAllMocks();

    mockSearchParams = new URLSearchParams(
      "booking_id=42&booking_status=PENDING_PAYMENT&payment_status=FAILED&venue=test-cafe"
    );
    mockedGetBookingReceipt.mockRejectedValueOnce(new Error("pending"));
    let resolvePay!: (value: PaymentInitiateOut) => void;
    mockedInitiatePayment.mockImplementationOnce(
      () =>
        new Promise<PaymentInitiateOut>((resolve) => {
          resolvePay = resolve;
        })
    );

    render(React.createElement(BookingCallbackPage));
    const retryBtn = await screen.findByRole("button", { name: "تلاش مجدد پرداخت" });
    act(() => {
      retryBtn.click();
      retryBtn.click();
    });
    expect(mockedInitiatePayment).toHaveBeenCalledTimes(1);
    resolvePay({
      transaction_id: 1,
      booking_id: 42,
      amount_toman: 150_000,
      currency: "TOMAN",
      status: "INITIATED",
      provider_name: "sandbox",
      provider_reference: "AUTH-1",
      redirect_url: "https://sandbox.example.test/pay",
    });
  });
});

describe("F-01 booking-journey fixes", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockedListVenueSlots.mockResolvedValue([]);
    mockSearchParams = new URLSearchParams("");
    mockAuthState = {
      user: {
        id: 1,
        phone_number: "09123456789",
        full_name: "علی",
        role: "CUSTOMER",
      },
      loading: false,
    };
  });

  afterEach(() => {
    vi.useRealTimers();
    cleanup();
  });

  it("B1: confirmed booking panel links to /my-bookings", async () => {
    const user = userEvent.setup();
    mockedInitiateBooking.mockResolvedValueOnce(makeLockedBooking());
    mockedGetMyWallet.mockResolvedValueOnce({ balance_toman: 500_000, entries: [] });
    mockedPayBookingWithWallet.mockResolvedValueOnce({
      id: 7,
      booking_id: 42,
      amount_toman: 150_000,
      currency: "TOMAN",
      status: "SUCCESS",
      provider_name: "wallet",
      provider_reference: "REF-7",
      tracking_code: "TRK-7",
      card_pan_masked: "",
      created_at: "2099-01-01T09:50:00Z",
      verified_at: "2099-01-01T09:50:00Z",
    });

    render(
      React.createElement(BookingFlow, {
        venueId: 1,
        venueName: "کافه تست",
        venueSlug: "test-cafe",
        designAddons: [],
        selectedPin: PIN_FIXTURE,
        initialResume: {
          pinId: 10,
          slotDate: "2099-01-01",
          slotStartIso: "2099-01-01T10:00:00Z",
          slotLabel: "۱۰:۰۰ تا ۱۱:۳۰",
          addonIds: [],
          step: "review",
        },
      })
    );

    await user.click(screen.getByRole("button", { name: "تایید و قفل موقت میز" }));
    await screen.findByText("میز برای شما به‌صورت موقت قفل شد");
    await waitFor(() => expect(screen.getByText(/۵۰۰٬۰۰۰ تومان/)).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "پرداخت با کیف پول" }));

    const link = await screen.findByRole("link", { name: "مشاهده رزروهای من" });
    expect(link).toHaveAttribute("href", "/my-bookings");
  });

  it("M3: shows live countdown during paying and expires without client-side confirmation", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2099-01-01T09:50:00Z"));

    mockedInitiateBooking.mockResolvedValueOnce(makeLockedBooking(10_000));
    mockedGetMyWallet.mockResolvedValueOnce({ balance_toman: 500_000, entries: [] });

    let resolvePay!: (value: PaymentTransactionOut) => void;
    mockedPayBookingWithWallet.mockImplementationOnce(
      () =>
        new Promise<PaymentTransactionOut>((resolve) => {
          resolvePay = resolve;
        })
    );

    render(
      React.createElement(BookingFlow, {
        venueId: 1,
        venueName: "کافه تست",
        venueSlug: "test-cafe",
        designAddons: [],
        selectedPin: PIN_FIXTURE,
        initialResume: {
          pinId: 10,
          slotDate: "2099-01-01",
          slotStartIso: "2099-01-01T10:00:00Z",
          slotLabel: "۱۰:۰۰ تا ۱۱:۳۰",
          addonIds: [],
          step: "review",
        },
      })
    );

    await act(async () => {
      screen.getByRole("button", { name: "تایید و قفل موقت میز" }).click();
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByText("00:10")).toBeInTheDocument();

    await act(async () => {
      screen.getByRole("button", { name: "پرداخت با کیف پول" }).click();
    });

    await act(async () => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.getByText("00:07")).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(8000);
    });
    expect(screen.getByText(/زمان قفل رزرو به پایان رسید/)).toBeInTheDocument();

    await act(async () => {
      resolvePay({
        id: 9,
        booking_id: 42,
        amount_toman: 150_000,
        currency: "TOMAN",
        status: "SUCCESS",
        provider_name: "wallet",
        provider_reference: "REF-9",
        tracking_code: "TRK-9",
        card_pan_masked: "",
        created_at: "2099-01-01T09:50:00Z",
        verified_at: "2099-01-01T09:50:00Z",
      });
      await Promise.resolve();
    });
    expect(screen.queryByRole("link", { name: "مشاهده رزروهای من" })).not.toBeInTheDocument();
  });

  it("M5: failed load on my-bookings shows only error banner + retry without empty state or zero wallet", async () => {
    mockedListMyBookings.mockRejectedValueOnce(new Error("network error"));
    mockedGetMyWallet.mockRejectedValueOnce(new Error("network error"));
    mockedListMyReviews.mockResolvedValueOnce([]);

    render(React.createElement(MyBookingsPage));

    expect(await screen.findByRole("button", { name: "تلاش مجدد" })).toBeInTheDocument();
    expect(screen.queryByText("هنوز رزروی ثبت نکرده‌اید.")).not.toBeInTheDocument();
    expect(screen.queryByText("کیف پول درون‌برنامه‌ای")).not.toBeInTheDocument();
    expect(screen.queryByText("۰ تومان")).not.toBeInTheDocument();
  });

  it("M11: paginates bookings (50) and reviews (20) with show-more and hides button on short page", async () => {
    const user = userEvent.setup();
    const firstBookingsPage = Array.from({ length: 50 }, (_, i) => makeBooking(i + 1));
    const secondBookingsPage = [makeBooking(51)];
    const firstReviewsPage: ReviewMineOut[] = Array.from({ length: 20 }, (_, i) => ({
      id: i + 1,
      booking_id: i + 1,
      table_number: String(i + 1),
      reviewer_name: "علی",
      rating: 5,
      text: `نظر ${i + 1}`,
      is_visible: true,
      created_at: "2026-11-20T10:00:00Z",
    }));
    const secondReviewsPage: ReviewMineOut[] = [
      {
        id: 21,
        booking_id: 51,
        table_number: "51",
        reviewer_name: "علی",
        rating: 4,
        text: "نظر ۵۱",
        is_visible: true,
        created_at: "2026-11-20T10:00:00Z",
      },
    ];

    mockedListMyBookings
      .mockResolvedValueOnce(firstBookingsPage)
      .mockResolvedValueOnce(secondBookingsPage);
    mockedGetMyWallet.mockResolvedValueOnce({ balance_toman: 100_000, entries: [] });
    mockedListMyReviews
      .mockResolvedValueOnce(firstReviewsPage)
      .mockResolvedValueOnce(secondReviewsPage);

    render(React.createElement(MyBookingsPage));

    expect(await screen.findByText(/نمایش 50 رزرو/)).toBeInTheDocument();
    expect(screen.getByText(/نمایش 20 نظر/)).toBeInTheDocument();
    expect(mockedListMyBookings).toHaveBeenCalledWith({ limit: 50, offset: 0 });
    expect(mockedListMyReviews).toHaveBeenCalledWith({ limit: 20, offset: 0 });

    await user.click(screen.getByRole("button", { name: "نمایش بیشتر رزروها" }));
    expect(await screen.findByText(/نمایش 51 رزرو/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "نمایش بیشتر رزروها" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "نمایش بیشتر نظرها" }));
    expect(await screen.findByText(/نمایش 21 نظر/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "نمایش بیشتر نظرها" })).not.toBeInTheDocument();
    expect(screen.getByText("نظر ۵۱")).toBeInTheDocument();
  });

  it("m8: computeSlotEndIso derives 90-minute slot end from resumed start", () => {
    const start = "2099-01-01T10:00:00Z";
    const end = computeSlotEndIso(start);
    expect(Date.parse(end) - Date.parse(start)).toBe(90 * 60 * 1000);
  });

  it("m9: wallet sufficiency uses authoritative lock amountOnlineToman rather than pin fee", async () => {
    const user = userEvent.setup();
    mockedInitiateBooking.mockResolvedValueOnce({
      ...makeLockedBooking(),
      amount_online_toman: 250_000,
    });
    mockedGetMyWallet.mockResolvedValueOnce({ balance_toman: 200_000, entries: [] });

    render(
      React.createElement(BookingFlow, {
        venueId: 1,
        venueName: "کافه تست",
        venueSlug: "test-cafe",
        designAddons: [],
        selectedPin: PIN_FIXTURE,
        initialResume: {
          pinId: 10,
          slotDate: "2099-01-01",
          slotStartIso: "2099-01-01T10:00:00Z",
          slotLabel: "۱۰:۰۰ تا ۱۱:۳۰",
          addonIds: [],
          step: "review",
        },
      })
    );

    await user.click(screen.getByRole("button", { name: "تایید و قفل موقت میز" }));
    await screen.findByText("میز برای شما به‌صورت موقت قفل شد");
    await waitFor(() => expect(screen.getByText(/۲۰۰٬۰۰۰ تومان/)).toBeInTheDocument());

    const radios = screen.getAllByRole("radio") as HTMLInputElement[];
    expect(radios[0]).toBeDisabled();
    expect(radios[1]).toBeChecked();
  });

  it("m16: keeps cancellation success banner when post-cancel refetch fails", async () => {
    const user = userEvent.setup();
    mockedListMyBookings
      .mockResolvedValueOnce([makeBooking(201, { is_cancellable: true, cancel_refund_toman: 150_000 })])
      .mockRejectedValueOnce(new Error("refresh failed"));
    mockedGetMyWallet.mockResolvedValueOnce({ balance_toman: 0, entries: [] });
    mockedListMyReviews.mockResolvedValueOnce([]);
    mockedCancelBooking.mockResolvedValueOnce({
      booking_id: 201,
      status: "CANCELLED",
      refunded_to_wallet_toman: 150_000,
      wallet_balance_toman: 150_000,
    } as CancelResult);

    render(React.createElement(MyBookingsPage));

    await user.click(await screen.findByRole("button", { name: "لغو رزرو" }));
    await user.click(screen.getByRole("button", { name: "تایید نهایی لغو رزرو" }));

    expect(await screen.findByText("رزرو #201 لغو شد")).toBeInTheDocument();
    expect(screen.getByText(/به‌روزرسانی فهرست رزروها ناموفق بود/)).toBeInTheDocument();
  });

  it("m17: clears previous user bookings and wallet when switching users with a failing fetch", async () => {
    mockedListMyBookings.mockResolvedValueOnce([makeBooking(301)]);
    mockedGetMyWallet.mockResolvedValueOnce({ balance_toman: 90_000, entries: [] });
    mockedListMyReviews.mockResolvedValueOnce([]);

    const { rerender } = render(React.createElement(MyBookingsPage));
    expect(await screen.findByText(/301 — کافه 301/)).toBeInTheDocument();

    mockAuthState = {
      user: { id: 2, phone_number: "09120000002", full_name: "رضا", role: "CUSTOMER" },
      loading: false,
    };
    mockedListMyBookings.mockRejectedValueOnce(new Error("fail for user 2"));
    mockedGetMyWallet.mockRejectedValueOnce(new Error("fail for user 2"));
    mockedListMyReviews.mockResolvedValueOnce([]);

    rerender(React.createElement(MyBookingsPage));
    expect(await screen.findByRole("button", { name: "تلاش مجدد" })).toBeInTheDocument();
    expect(screen.queryByText(/301 — کافه 301/)).not.toBeInTheDocument();
  });

  it("m18: returning to slot selection shows loading state until fresh slots arrive", async () => {
    const user = userEvent.setup();
    const slotFixture: SlotOut = {
      start: "2099-01-01T10:00:00Z",
      end: "2099-01-01T11:30:00Z",
      start_jalali: "۱۰:۰۰",
      end_jalali: "۱۱:۳۰",
      is_bookable: true,
      disabled_reason: null,
    };
    let resolveSecondSlots!: (value: SlotOut[]) => void;
    mockedListVenueSlots
      .mockResolvedValueOnce([slotFixture])
      .mockImplementationOnce(
        () =>
          new Promise<SlotOut[]>((resolve) => {
            resolveSecondSlots = resolve;
          })
      );

    render(
      React.createElement(BookingFlow, {
        venueId: 1,
        venueName: "کافه تست",
        venueSlug: "test-cafe",
        designAddons: [],
        selectedPin: PIN_FIXTURE,
      })
    );

    const slotBtn = await screen.findByRole("button", { name: /۱۰:۰۰ تا ۱۱:۳۰/ });
    await user.click(slotBtn);
    await screen.findByText(/افزودنی‌های طراحی میز/);

    await user.click(screen.getByRole("button", { name: "بازگشت به انتخاب زمان" }));
    expect(screen.getByText("در حال دریافت زمان‌های قابل رزرو...")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /۱۰:۰۰ تا ۱۱:۳۰/ })).not.toBeInTheDocument();

    resolveSecondSlots([slotFixture]);
    expect(await screen.findByRole("button", { name: /۱۰:۰۰ تا ۱۱:۳۰/ })).toBeInTheDocument();
  });

  it("m21: marks currently selected slot button with aria-pressed=true and selected styling", async () => {
    const user = userEvent.setup();
    const slotsFixture: SlotOut[] = [
      {
        start: "2099-01-01T10:00:00Z",
        end: "2099-01-01T11:30:00Z",
        start_jalali: "۱۰:۰۰",
        end_jalali: "۱۱:۳۰",
        is_bookable: true,
        disabled_reason: null,
      },
      {
        start: "2099-01-01T12:00:00Z",
        end: "2099-01-01T13:30:00Z",
        start_jalali: "۱۲:۰۰",
        end_jalali: "۱۳:۳۰",
        is_bookable: true,
        disabled_reason: null,
      },
    ];
    mockedListVenueSlots.mockResolvedValue(slotsFixture);

    render(
      React.createElement(BookingFlow, {
        venueId: 1,
        venueName: "کافه تست",
        venueSlug: "test-cafe",
        designAddons: [],
        selectedPin: PIN_FIXTURE,
      })
    );

    const firstSlot = await screen.findByRole("button", { name: /۱۰:۰۰ تا ۱۱:۳۰/ });
    await user.click(firstSlot);
    await screen.findByText(/افزودنی‌های طراحی میز/);
    await user.click(screen.getByRole("button", { name: "بازگشت به انتخاب زمان" }));

    const selectedBtn = await screen.findByRole("button", { name: /۱۰:۰۰ تا ۱۱:۳۰/ });
    const unselectedBtn = screen.getByRole("button", { name: /۱۲:۰۰ تا ۱۳:۳۰/ });
    expect(selectedBtn).toHaveAttribute("aria-pressed", "true");
    expect(selectedBtn.className).toContain("bg-stone-900");
    expect(unselectedBtn).toHaveAttribute("aria-pressed", "false");
  });

  it("m22: bare booking_id shows neutral checking state and non-confirmed receipt shows warning", async () => {
    mockSearchParams = new URLSearchParams("booking_id=42&venue=test-cafe");
    let resolveReceipt!: (value: SplitReceiptOut) => void;
    mockedGetBookingReceipt.mockImplementationOnce(
      () =>
        new Promise<SplitReceiptOut>((resolve) => {
          resolveReceipt = resolve;
        })
    );

    render(React.createElement(BookingCallbackPage));
    expect(screen.getByText(/در حال بررسی وضعیت پرداخت/)).toBeInTheDocument();
    expect(screen.queryByText("پرداخت آنلاین ناموفق بود")).not.toBeInTheDocument();

    resolveReceipt({ ...makeReceipt(42), status: "PENDING_PAYMENT" });
    expect(await screen.findByRole("alert")).toHaveTextContent("هنوز تکمیل نشده است");
    expect(screen.queryByText("رزرو تایید شد")).not.toBeInTheDocument();
  });

  it("m23: callback receipt-error screen renders retry button and /my-bookings link", async () => {
    mockSearchParams = new URLSearchParams("booking_id=42&booking_status=CONFIRMED&venue=test-cafe");
    mockedGetBookingReceipt.mockRejectedValueOnce(new Error("receipt failed"));

    render(React.createElement(BookingCallbackPage));

    expect(await screen.findByRole("button", { name: "تلاش مجدد دریافت رسید" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "مشاهده رزروهای من" })).toHaveAttribute(
      "href",
      "/my-bookings"
    );
    expect(screen.getByRole("link", { name: "بازگشت به صفحه مجموعه" })).toHaveAttribute(
      "href",
      "/venues/test-cafe"
    );
  });

  it("m24: disables cancel RESET button while cancellation request is in flight", async () => {
    const user = userEvent.setup();
    mockedListMyBookings.mockResolvedValueOnce([
      makeBooking(401, { is_cancellable: true, cancel_refund_toman: 150_000 }),
    ]);
    mockedGetMyWallet.mockResolvedValueOnce({ balance_toman: 0, entries: [] });
    mockedListMyReviews.mockResolvedValueOnce([]);

    let resolveCancel!: (value: CancelResult) => void;
    mockedCancelBooking.mockImplementationOnce(
      () =>
        new Promise<CancelResult>((resolve) => {
          resolveCancel = resolve;
        })
    );

    render(React.createElement(MyBookingsPage));

    await user.click(await screen.findByRole("button", { name: "لغو رزرو" }));
    await user.click(screen.getByRole("button", { name: "تایید نهایی لغو رزرو" }));

    expect(screen.getByRole("button", { name: "انصراف" })).toBeDisabled();
    resolveCancel({
      booking_id: 401,
      status: "CANCELLED",
      refunded_to_wallet_toman: 150_000,
      wallet_balance_toman: 150_000,
    } as CancelResult);
  });
});
