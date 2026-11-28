// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";

import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { BookingFlow } from "@/components/BookingFlow";
import {
  ApiError,
  getMyWallet,
  initiateBooking,
  initiatePayment,
  payBookingWithWallet,
  type BookingInitiateOut,
  type PaymentInitiateOut,
  type PaymentTransactionOut,
  type PublicTablePinOut,
  type WalletMeOut,
} from "@/lib/api";

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
  }),
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
  useAuth: () => ({
    user: {
      id: 1,
      phone_number: "09123456789",
      full_name: "کاربر تست",
      role: "CUSTOMER",
    },
    loading: false,
  }),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    getMyWallet: vi.fn(),
    initiateBooking: vi.fn(),
    initiatePayment: vi.fn(),
    payBookingWithWallet: vi.fn(),
    listVenueSlots: vi.fn().mockResolvedValue([]),
  };
});

const mockedGetMyWallet = vi.mocked(getMyWallet);
const mockedInitiateBooking = vi.mocked(initiateBooking);
const mockedInitiatePayment = vi.mocked(initiatePayment);
const mockedPayBookingWithWallet = vi.mocked(payBookingWithWallet);

const PIN_FIXTURE: PublicTablePinOut = {
  id: 10,
  table_number: "7",
  capacity: 4,
  pitch: 0,
  yaw: 0,
  description: "میز کنار پنجره",
  reservation_fee_toman: 150_000,
  is_smoking: false,
};

function makeLockedBooking(expiresInMs = 10 * 60 * 1000): BookingInitiateOut {
  const now = Date.now();
  return {
    booking_id: 42,
    id: 42,
    status: "LOCKED",
    venue_id: 1,
    table_pin_id: 10,
    start_at: "2099-01-01T10:00:00Z",
    end_at: "2099-01-01T12:00:00Z",
    slot_date: "2099-01-01",
    slot_start_time: "10:00",
    locked_at: new Date(now).toISOString(),
    lock_expires_at: new Date(now + expiresInMs).toISOString(),
    amount_online_toman: 150_000,
    amount_in_person_toman: 0,
    start_jalali: "۱۴۷۷/۱۰/۱۱ ۱۰:۰۰",
    end_jalali: "۱۴۷۷/۱۰/۱۱ ۱۲:۰۰",
    jalali_start_datetime: "۱۴۷۷/۱۰/۱۱ ۱۰:۰۰",
    jalali_end_datetime: "۱۴۷۷/۱۰/۱۱ ۱۲:۰۰",
    jalali_date: "۱۴۷۷/۱۰/۱۱",
  };
}

function makeWallet(balanceToman: number): WalletMeOut {
  return {
    balance_toman: balanceToman,
    entries: [],
  };
}

function makeWalletTx(): PaymentTransactionOut {
  return {
    id: 901,
    booking_id: 42,
    amount_toman: 150_000,
    currency: "TOMAN",
    status: "SUCCESS",
    provider_name: "wallet",
    provider_reference: "wallet-ref-901",
    tracking_code: "TRK-901",
    card_pan_masked: "",
    created_at: "2026-11-27T12:00:00Z",
    verified_at: "2026-11-27T12:00:00Z",
  };
}

function makeGatewayInit(): PaymentInitiateOut {
  return {
    transaction_id: 777,
    booking_id: 42,
    amount_toman: 150_000,
    currency: "TOMAN",
    status: "INITIATED",
    provider_name: "sandbox",
    provider_reference: "AUTH-777",
    redirect_url: "https://sandbox.example.test/pay/AUTH-777",
  };
}

async function renderLockedPaymentStep(
  user: ReturnType<typeof userEvent.setup>,
  expiresInMs = 10 * 60 * 1000
) {
  mockedInitiateBooking.mockResolvedValueOnce(makeLockedBooking(expiresInMs));
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
        slotLabel: "۱۰:۰۰ تا ۱۲:۰۰",
        addonIds: [],
        step: "review",
      },
    })
  );

  await user.click(screen.getByRole("button", { name: "تایید و قفل موقت میز" }));
  await screen.findByText("میز برای شما به‌صورت موقت قفل شد");
}

describe("BookingFlow payment choice (T-034 frontend)", () => {
  let assignMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.clearAllMocks();
    assignMock = vi.fn();
    Object.defineProperty(window, "location", {
      value: {
        origin: "http://localhost:3000",
        assign: assignMock,
      },
      writable: true,
      configurable: true,
    });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("renders both payment options at the payment step with wallet first and gateway second", async () => {
    const user = userEvent.setup();
    mockedGetMyWallet.mockResolvedValueOnce(makeWallet(200_000));

    await renderLockedPaymentStep(user);

    const radios = screen.getAllByRole("radio") as HTMLInputElement[];
    expect(radios).toHaveLength(2);
    expect(radios[0]!.value).toBe("wallet");
    expect(radios[1]!.value).toBe("gateway");
    await waitFor(() => expect(radios[0]).toBeEnabled());
    expect(radios[0]).toBeChecked();
  });

  it("disables wallet with insufficient-balance note when balance_toman < fee and enables when balance_toman === fee", async () => {
    const user = userEvent.setup();
    mockedGetMyWallet.mockResolvedValueOnce(makeWallet(149_999));

    await renderLockedPaymentStep(user);

    const radios = screen.getAllByRole("radio") as HTMLInputElement[];
    await waitFor(() =>
      expect(screen.getByText("موجودی کیف پول برای پرداخت هزینه رزرو میز کافی نیست.")).toBeInTheDocument()
    );
    expect(radios[0]).toBeDisabled();
    expect(radios[1]).toBeEnabled();
    expect(radios[1]).toBeChecked();

    cleanup();
    vi.clearAllMocks();

    mockedGetMyWallet.mockResolvedValueOnce(makeWallet(150_000));
    await renderLockedPaymentStep(user);

    const eqRadios = screen.getAllByRole("radio") as HTMLInputElement[];
    await waitFor(() => expect(eqRadios[0]).toBeEnabled());
    expect(eqRadios[0]).toBeChecked();
  });

  it("disables wallet with a note when getMyWallet fails while keeping gateway usable", async () => {
    const user = userEvent.setup();
    mockedGetMyWallet.mockRejectedValueOnce(new Error("network error"));
    mockedInitiatePayment.mockResolvedValueOnce(makeGatewayInit());

    await renderLockedPaymentStep(user);

    const radios = screen.getAllByRole("radio") as HTMLInputElement[];
    await waitFor(() =>
      expect(
        screen.getByText("امکان دریافت موجودی کیف پول وجود ندارد؛ می‌توانید از درگاه پرداخت آنلاین استفاده کنید.")
      ).toBeInTheDocument()
    );
    expect(radios[0]).toBeDisabled();
    expect(radios[1]).toBeEnabled();
    expect(radios[1]).toBeChecked();

    await user.click(screen.getByRole("button", { name: "پرداخت آنلاین (درگاه آزمایشی)" }));
    await waitFor(() => expect(mockedInitiatePayment).toHaveBeenCalledTimes(1));
    expect(assignMock).toHaveBeenCalledWith("https://sandbox.example.test/pay/AUTH-777");
  });

  it("pays via wallet when balance is sufficient, calls payBookingWithWallet once, and reaches confirmed with no redirect", async () => {
    const user = userEvent.setup();
    mockedGetMyWallet.mockResolvedValueOnce(makeWallet(300_000));
    mockedPayBookingWithWallet.mockResolvedValueOnce(makeWalletTx());

    await renderLockedPaymentStep(user);

    const radios = screen.getAllByRole("radio") as HTMLInputElement[];
    await waitFor(() => expect(radios[0]).toBeEnabled());

    await user.click(screen.getByRole("button", { name: "پرداخت با کیف پول" }));

    await screen.findByText("رزرو شما با موفقیت تایید شد");
    expect(mockedPayBookingWithWallet).toHaveBeenCalledTimes(1);
    expect(mockedPayBookingWithWallet).toHaveBeenCalledWith({
      booking_id: 42,
      idempotency_key: expect.any(String),
    });
    expect(screen.getByText("TRK-901")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "مشاهده رزروهای من" })).toHaveAttribute("href", "/bookings");
    expect(assignMock).not.toHaveBeenCalled();
  });

  it("shows Persian message and auto-selects gateway on WALLET_INSUFFICIENT_BALANCE", async () => {
    const user = userEvent.setup();
    mockedGetMyWallet.mockResolvedValueOnce(makeWallet(200_000));
    mockedPayBookingWithWallet.mockRejectedValueOnce(
      new ApiError(400, "WALLET_INSUFFICIENT_BALANCE", "Insufficient balance", {})
    );

    await renderLockedPaymentStep(user);

    const radios = screen.getAllByRole("radio") as HTMLInputElement[];
    await waitFor(() => expect(radios[0]).toBeEnabled());

    await user.click(screen.getByRole("button", { name: "پرداخت با کیف پول" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).not.toContain("WALLET_INSUFFICIENT_BALANCE");
    expect(alert.textContent).toContain("موجودی کیف پول");
    expect(radios[0]).toBeDisabled();
    expect(radios[1]).toBeChecked();
  });

  it("keeps gateway path unchanged: calls initiatePayment and redirects to redirect_url", async () => {
    const user = userEvent.setup();
    mockedGetMyWallet.mockResolvedValueOnce(makeWallet(300_000));
    mockedInitiatePayment.mockResolvedValueOnce(makeGatewayInit());

    await renderLockedPaymentStep(user);

    const radios = screen.getAllByRole("radio") as HTMLInputElement[];
    await waitFor(() => expect(radios[0]).toBeEnabled());

    await user.click(radios[1]!);
    await user.click(screen.getByRole("button", { name: "پرداخت آنلاین (درگاه آزمایشی)" }));

    await waitFor(() => expect(mockedInitiatePayment).toHaveBeenCalledTimes(1));
    expect(mockedPayBookingWithWallet).not.toHaveBeenCalled();
    expect(assignMock).toHaveBeenCalledWith("https://sandbox.example.test/pay/AUTH-777");
  });

  it("prevents a second request on double-click while a payment is in flight", async () => {
    const user = userEvent.setup();
    mockedGetMyWallet.mockResolvedValueOnce(makeWallet(300_000));

    let resolveWalletPay!: (value: PaymentTransactionOut) => void;
    mockedPayBookingWithWallet.mockImplementationOnce(
      () =>
        new Promise<PaymentTransactionOut>((resolve) => {
          resolveWalletPay = resolve;
        })
    );

    await renderLockedPaymentStep(user);

    const radios = screen.getAllByRole("radio") as HTMLInputElement[];
    await waitFor(() => expect(radios[0]).toBeEnabled());

    const submitButton = screen.getByRole("button", { name: "پرداخت با کیف پول" });
    await user.dblClick(submitButton);

    expect(mockedPayBookingWithWallet).toHaveBeenCalledTimes(1);
    expect(radios[0]).toBeDisabled();
    expect(radios[1]).toBeDisabled();

    resolveWalletPay(makeWalletTx());
    await screen.findByText("رزرو شما با موفقیت تایید شد");
  });

  it("disables both payment options when the lock countdown reaches 0", async () => {
    const user = userEvent.setup();
    mockedGetMyWallet.mockResolvedValueOnce(makeWallet(300_000));

    await renderLockedPaymentStep(user, 500);

    const radios = screen.getAllByRole("radio") as HTMLInputElement[];
    await waitFor(() => expect(mockedGetMyWallet).toHaveBeenCalledTimes(1));
    expect(radios[0]).toBeDisabled();
    expect(radios[1]).toBeDisabled();
    expect(screen.getByText("00:00")).toBeInTheDocument();
  });
});
