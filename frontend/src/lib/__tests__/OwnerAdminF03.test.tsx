// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";

import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import AdminFinancialReportPage from "@/app/admin/financial-report/page";
import AdminReviewsPage from "@/app/admin/reviews/page";
import OwnerVenuesPage from "@/app/owner/page";
import { NotificationsBell } from "@/components/NotificationsBell";
import { getReviewStatusBadge, OwnerVenueDashboard } from "@/components/OwnerVenueDashboard";
import {
  ApiError,
  createPinBlockedSlot,
  createVenueAddon,
  deleteVenueAddon,
  getFinancialReport,
  getOwnerVenue,
  getOwnerVenueSubscription,
  getUnreadCount,
  listAdminReviews,
  listNotifications,
  listOwnerVenueBookings,
  listOwnerVenues,
  listOwnerVenueSpaces,
  listPinBlockedSlots,
  listPublicVenues,
  listSpaceTablePins,
  listVenueAddons,
  listVenueSlots,
  updateTablePin,
  type DesignAddonOut,
  type FinancialReportOut,
  type FinancialReportPaymentRowOut,
  type NotificationOut,
  type OwnerBookingOut,
  type ReviewAdminOut,
  type SpaceOut,
  type TablePinOut,
  type VenueOwnerOut,
} from "@/lib/api";

const mockRouter = {
  push: vi.fn(),
  replace: vi.fn(),
  prefetch: vi.fn(),
};

let mockAuthState = {
  user: {
    id: 1,
    phone_number: "09123456789",
    full_name: "مدیر",
    role: "ADMIN",
  } as { id: number; phone_number: string; full_name: string; role: string } | null,
  loading: false,
};

vi.mock("next/navigation", () => ({
  useRouter: () => mockRouter,
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
    createPinBlockedSlot: vi.fn(),
    createVenueAddon: vi.fn(),
    deleteVenueAddon: vi.fn(),
    getFinancialReport: vi.fn(),
    getOwnerVenue: vi.fn(),
    getOwnerVenueSubscription: vi.fn(),
    getUnreadCount: vi.fn(),
    listAdminReviews: vi.fn(),
    listNotifications: vi.fn(),
    listOwnerVenueBookings: vi.fn(),
    listOwnerVenues: vi.fn(),
    listOwnerVenueSpaces: vi.fn(),
    listPinBlockedSlots: vi.fn(),
    listPublicVenues: vi.fn(),
    listSpaceTablePins: vi.fn(),
    listVenueAddons: vi.fn(),
    listVenueSlots: vi.fn(),
    updateTablePin: vi.fn(),
    updateVenueAddon: vi.fn(),
  };
});

const mockedCreatePinBlockedSlot = vi.mocked(createPinBlockedSlot);
const mockedCreateVenueAddon = vi.mocked(createVenueAddon);
const mockedDeleteVenueAddon = vi.mocked(deleteVenueAddon);
const mockedGetFinancialReport = vi.mocked(getFinancialReport);
const mockedGetOwnerVenue = vi.mocked(getOwnerVenue);
const mockedGetOwnerVenueSubscription = vi.mocked(getOwnerVenueSubscription);
const mockedGetUnreadCount = vi.mocked(getUnreadCount);
const mockedListAdminReviews = vi.mocked(listAdminReviews);
const mockedListNotifications = vi.mocked(listNotifications);
const mockedListOwnerVenueBookings = vi.mocked(listOwnerVenueBookings);
const mockedListOwnerVenues = vi.mocked(listOwnerVenues);
const mockedListOwnerVenueSpaces = vi.mocked(listOwnerVenueSpaces);
const mockedListPinBlockedSlots = vi.mocked(listPinBlockedSlots);
const mockedListPublicVenues = vi.mocked(listPublicVenues);
const mockedListSpaceTablePins = vi.mocked(listSpaceTablePins);
const mockedListVenueAddons = vi.mocked(listVenueAddons);
const mockedListVenueSlots = vi.mocked(listVenueSlots);
const mockedUpdateTablePin = vi.mocked(updateTablePin);

function makePaymentRow(id: number, status: string): FinancialReportPaymentRowOut {
  return {
    id,
    booking_id: 1000 + id,
    customer_id: 50 + id,
    provider_name: "sandbox",
    amount_toman: 150_000,
    status,
    created_at: "2026-11-20T10:00:00Z",
  };
}

function makeReport(rows: FinancialReportPaymentRowOut[]): FinancialReportOut {
  return {
    payments: {
      total_toman: 150_000 * rows.length,
      count: rows.length,
      counts_by_status: { SUCCESS: rows.length },
      rows,
    },
    wallet: {
      total_credit_toman: 0,
      total_debit_toman: 0,
      count: 0,
      rows: [],
    },
    subscriptions: {
      total_toman: 0,
      count: 0,
      rows: [],
    },
  };
}

function makeNotification(id: number, title: string): NotificationOut {
  return {
    id,
    title,
    body: `متن ${title}`,
    type: "BOOKING_CONFIRMED",
    is_read: false,
    created_at: "2026-11-20T10:00:00Z",
  } as unknown as NotificationOut;
}

function makeVenue(): VenueOwnerOut {
  return {
    id: 1,
    name: "کافه تست",
    slug: "test-cafe",
    venue_type: "CAFE",
    city: "تهران",
    address: "خیابان ولیعصر",
    description: "",
    is_approved: true,
    review_status: "APPROVED",
    subscription_status: "ACTIVE",
    operating_hours: [],
    design_addons: [],
  } as unknown as VenueOwnerOut;
}

describe("F-03 reproduction tests (m5, m36, M9)", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockAuthState = {
      user: { id: 1, phone_number: "09123456789", full_name: "مدیر", role: "ADMIN" },
      loading: false,
    };
    mockedGetUnreadCount.mockResolvedValue({ unread_count: 0 });
    mockedListVenueSlots.mockResolvedValue([]);
    mockedListPinBlockedSlots.mockResolvedValue([]);
    mockedListSpaceTablePins.mockResolvedValue([]);
  });

  afterEach(() => {
    cleanup();
  });

  it("m5: discards stale show-more financial report response when filters changed mid-flight", async () => {
    const user = userEvent.setup();
    const initialRows = Array.from({ length: 50 }, (_, i) => makePaymentRow(i + 1, "INITIATED"));
    let resolveShowMore!: (value: FinancialReportOut) => void;

    mockedGetFinancialReport
      .mockResolvedValueOnce(makeReport(initialRows))
      .mockImplementationOnce(
        () =>
          new Promise<FinancialReportOut>((resolve) => {
            resolveShowMore = resolve;
          })
      )
      .mockResolvedValueOnce(makeReport([makePaymentRow(999, "SUCCESS")]));

    render(React.createElement(AdminFinancialReportPage));

    const showMoreBtn = await screen.findByRole("button", { name: "نمایش ردیف‌های بیشتر" });
    await user.click(showMoreBtn);

    const statusSelect = screen.getByLabelText("وضعیت پرداخت");
    await user.selectOptions(statusSelect, "SUCCESS");
    expect(await screen.findByText("#1999")).toBeInTheDocument();

    await act(async () => {
      resolveShowMore(makeReport([makePaymentRow(888, "INITIATED")]));
      await Promise.resolve();
    });

    expect(screen.queryByText("#1888")).not.toBeInTheDocument();
  });

  it("m36: discards stale NotificationsBell load-more response after reopen reset", async () => {
    const user = userEvent.setup();
    const firstPage = Array.from({ length: 20 }, (_, i) => makeNotification(i + 1, `اعلان ${i + 1}`));
    const freshPage = [makeNotification(501, "اعلان تازه")];
    let resolveStaleLoadMore!: (value: NotificationOut[]) => void;

    mockedListNotifications
      .mockResolvedValueOnce(firstPage)
      .mockImplementationOnce(
        () =>
          new Promise<NotificationOut[]>((resolve) => {
            resolveStaleLoadMore = resolve;
          })
      )
      .mockResolvedValueOnce(freshPage);

    render(React.createElement(NotificationsBell));

    await user.click(screen.getByRole("button", { name: "اعلان‌ها" }));
    await screen.findByText("اعلان 1");

    await user.click(screen.getByRole("button", { name: "نمایش اعلان‌های بیشتر" }));

    // Close and reopen bell -> resets to page 1
    await user.click(screen.getByRole("button", { name: "اعلان‌ها" }));
    await user.click(screen.getByRole("button", { name: "اعلان‌ها" }));
    expect(await screen.findByText("اعلان تازه")).toBeInTheDocument();

    await act(async () => {
      resolveStaleLoadMore([makeNotification(41, "اعلان کهنه")]);
      await Promise.resolve();
    });

    expect(screen.queryByText("اعلان کهنه")).not.toBeInTheDocument();
  });

  it("M9: keeps loaded dashboard sections visible when subscription fetch fails", async () => {
    mockedGetOwnerVenue.mockResolvedValueOnce(makeVenue());
    mockedGetOwnerVenueSubscription.mockRejectedValueOnce(new Error("sub failed"));
    mockedListOwnerVenueSpaces.mockResolvedValueOnce([]);
    mockedListOwnerVenueBookings.mockResolvedValueOnce([]);
    mockedListVenueAddons.mockResolvedValueOnce([]);

    render(React.createElement(OwnerVenueDashboard, { venueId: 1 }));

    expect(await screen.findByText("کافه تست")).toBeInTheDocument();
    expect(screen.getByText("اطلاعات اشتراک در دسترس نیست.")).toBeInTheDocument();
  });
});

function makeOwnerBooking(id: number): OwnerBookingOut {
  return {
    booking_id: id,
    status: "CONFIRMED",
    table_number: String(id),
    slot_date: "2026-11-20",
    jalali_date: "۱۴۰۵/۰۸/۲۹",
    slot_start_time: "10:00",
    start_at: "2026-11-20T10:00:00Z",
    end_at: "2026-11-20T11:30:00Z",
    start_jalali: "۱۴۰۵/۰۸/۲۹ ۱۳:۳۰",
    end_jalali: "۱۴۰۵/۰۸/۲۹ ۱۵:۰۰",
    amount_online_toman: 150_000,
    amount_in_person_toman: 0,
    customer_phone_masked: "0912***789",
    created_at: "2026-11-19T10:00:00Z",
  };
}

describe("F-03 owner & admin fixes", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockAuthState = {
      user: { id: 1, phone_number: "09123456789", full_name: "مدیر", role: "ADMIN" },
      loading: false,
    };
    mockedGetUnreadCount.mockResolvedValue({ unread_count: 0 });
    mockedListPublicVenues.mockResolvedValue([]);
    mockedListVenueSlots.mockResolvedValue([]);
    mockedListPinBlockedSlots.mockResolvedValue([]);
    mockedListSpaceTablePins.mockResolvedValue([]);
  });

  afterEach(() => {
    cleanup();
  });

  it("M7: paginates owner venue bookings with 50 per page, shows count, and hides button on short page", async () => {
    const user = userEvent.setup();
    const page1 = Array.from({ length: 50 }, (_, i) => makeOwnerBooking(i + 1));
    const page2 = [makeOwnerBooking(51)];

    mockedGetOwnerVenue.mockResolvedValueOnce(makeVenue());
    mockedGetOwnerVenueSubscription.mockResolvedValueOnce({
      is_active: true,
      days_remaining: 20,
      has_ever_subscribed: true,
      plan_name: "طلایی",
      jalali_expires_at: "۱۴۰۵/۱۰/۰۱",
    } as unknown as Awaited<ReturnType<typeof getOwnerVenueSubscription>>);
    mockedListOwnerVenueSpaces.mockResolvedValueOnce([]);
    mockedListOwnerVenueBookings.mockResolvedValueOnce(page1).mockResolvedValueOnce(page2);
    mockedListVenueAddons.mockResolvedValueOnce([]);

    render(React.createElement(OwnerVenueDashboard, { venueId: 1 }));

    expect(await screen.findByText(/نمایش 50 رزرو/)).toBeInTheDocument();
    expect(mockedListOwnerVenueBookings).toHaveBeenCalledWith(1, { limit: 50, offset: 0 });

    await user.click(screen.getByRole("button", { name: "نمایش بیشتر" }));
    expect(await screen.findByText(/نمایش 51 رزرو/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "نمایش بیشتر" })).not.toBeInTheDocument();
  });

  it("M8 & m34: owner venues page shows نامشخص without 0 روز باقی‌مانده or raw ACTIVE code when subscription fails", async () => {
    mockedListOwnerVenues.mockResolvedValueOnce([makeVenue()]);
    mockedGetOwnerVenueSubscription.mockRejectedValueOnce(new Error("sub failed"));

    render(React.createElement(OwnerVenuesPage));

    expect(await screen.findByText("نامشخص")).toBeInTheDocument();
    expect(screen.getByText("اطلاعات اشتراک در دسترس نیست")).toBeInTheDocument();
    expect(screen.queryByText(/0 روز باقی‌مانده/)).not.toBeInTheDocument();
    expect(screen.queryByText(/ACTIVE/)).not.toBeInTheDocument();
  });

  it("M10: financial report failed first load shows error and retry button without loading text", async () => {
    mockedGetFinancialReport.mockRejectedValueOnce(new Error("report failed"));

    render(React.createElement(AdminFinancialReportPage));

    expect(await screen.findByRole("button", { name: "تلاش مجدد" })).toBeInTheDocument();
    expect(screen.queryByText("در حال دریافت گزارش مالی...")).not.toBeInTheDocument();
  });

  it("m1: admin reviews shows error on failure and end-of-list with back button on empty page at offset > 0", async () => {
    const user = userEvent.setup();
    mockedListAdminReviews.mockRejectedValueOnce(new Error("load failed"));

    render(React.createElement(AdminReviewsPage));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("نظری با این فیلترها یافت نشد.")).not.toBeInTheDocument();

    cleanup();
    vi.resetAllMocks();
    mockedListPublicVenues.mockResolvedValue([]);
    const page1: ReviewAdminOut[] = Array.from({ length: 20 }, (_, i) => ({
      id: i + 1,
      booking_id: 100 + i,
      venue_id: 1,
      table_number: "1",
      reviewer_name: `کاربر ${i + 1}`,
      rating: 5,
      text: `متن ${i + 1}`,
      is_visible: true,
      created_at: "2026-11-20T10:00:00Z",
    }));
    mockedListAdminReviews.mockResolvedValueOnce(page1).mockResolvedValueOnce([]);

    render(React.createElement(AdminReviewsPage));
    await screen.findByText("متن 1");
    await user.click(screen.getByRole("button", { name: "صفحه بعد" }));

    expect(await screen.findByText("به انتهای فهرست رسیدید")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "بازگشت به صفحه قبل" })).toBeInTheDocument();
    expect(screen.getByText("متن 1")).toBeInTheDocument();
  });

  it("m2 & m3: 409 on addon create avoids delete guidance and delete 409 on inactive addon shows already-inactive note", async () => {
    const user = userEvent.setup();
    const inactiveAddon: DesignAddonOut = {
      id: 7,
      title: "گل‌آرایی",
      fee: 40_000,
      is_active: false,
    };
    mockedGetOwnerVenue.mockResolvedValueOnce(makeVenue());
    mockedGetOwnerVenueSubscription.mockRejectedValueOnce(new Error("no sub"));
    mockedListOwnerVenueSpaces.mockResolvedValueOnce([]);
    mockedListOwnerVenueBookings.mockResolvedValueOnce([]);
    mockedListVenueAddons.mockResolvedValueOnce([inactiveAddon]);
    mockedCreateVenueAddon.mockRejectedValueOnce(new ApiError(409, "ADDON_IN_USE", "conflict", {}));
    mockedDeleteVenueAddon.mockRejectedValueOnce(new ApiError(409, "ADDON_IN_USE", "in use", {}));

    render(React.createElement(OwnerVenueDashboard, { venueId: 1 }));
    await screen.findByText("گل‌آرایی");

    // m2: create 409 does not show delete-specific guidance
    await user.click(screen.getByRole("button", { name: "افزودن افزودنی جدید" }));
    await user.type(screen.getByLabelText("عنوان افزودنی جدید"), "شمع");
    await user.type(screen.getByLabelText("هزینه افزودنی جدید"), "10000");
    await user.click(screen.getByRole("button", { name: "ثبت افزودنی" }));
    await waitFor(() => expect(mockedCreateVenueAddon).toHaveBeenCalledTimes(1));
    expect(screen.queryByText(/قابل حذف نیست/)).not.toBeInTheDocument();

    // m3: delete 409 on inactive addon shows already-inactive note and no deactivate button
    await user.click(screen.getByRole("button", { name: "حذف" }));
    await user.click(screen.getByRole("button", { name: "تایید حذف" }));
    expect(
      await screen.findByText(/این افزودنی هم‌اکنون غیرفعال است/)
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "غیرفعال کردن افزودنی" })).not.toBeInTheDocument();
  });

  it("m4: clearing pin fee shows Persian error and does not call updateTablePin", async () => {
    const user = userEvent.setup();
    const space1 = { id: 10, venue_id: 1, name: "سالن", panorama_status: "READY", is_active: true } as SpaceOut;
    const pin1 = { id: 100, space_id: 10, table_number: "A1", capacity: 4, reservation_fee_toman: 150_000, is_smoking: false } as unknown as TablePinOut;

    mockedGetOwnerVenue.mockResolvedValueOnce(makeVenue());
    mockedGetOwnerVenueSubscription.mockRejectedValueOnce(new Error("no sub"));
    mockedListOwnerVenueSpaces.mockResolvedValueOnce([space1]);
    mockedListSpaceTablePins.mockResolvedValueOnce([pin1]);
    mockedListOwnerVenueBookings.mockResolvedValueOnce([]);
    mockedListVenueAddons.mockResolvedValueOnce([]);

    render(React.createElement(OwnerVenueDashboard, { venueId: 1 }));
    await user.click(await screen.findByRole("button", { name: "ویرایش" }));

    const feeInput = screen.getByLabelText("هزینه رزرو A1");
    await user.clear(feeInput);
    await user.click(screen.getByRole("button", { name: "ذخیره" }));

    expect(await screen.findByText("هزینه رزرو را وارد کنید.")).toBeInTheDocument();
    expect(mockedUpdateTablePin).not.toHaveBeenCalled();
  });

  it("m31: block-slot error displays mapped server reason instead of guessed text", async () => {
    const user = userEvent.setup();
    const space1 = { id: 10, venue_id: 1, name: "سالن", panorama_status: "READY", is_active: true } as SpaceOut;
    const pin1 = { id: 100, space_id: 10, table_number: "A1", capacity: 4, reservation_fee_toman: 150_000, is_smoking: false } as unknown as TablePinOut;

    mockedGetOwnerVenue.mockResolvedValueOnce(makeVenue());
    mockedGetOwnerVenueSubscription.mockRejectedValueOnce(new Error("no sub"));
    mockedListOwnerVenueSpaces.mockResolvedValueOnce([space1]);
    mockedListSpaceTablePins.mockResolvedValueOnce([pin1]);
    mockedListOwnerVenueBookings.mockResolvedValueOnce([]);
    mockedListVenueAddons.mockResolvedValueOnce([]);
    mockedListVenueSlots.mockResolvedValue([
      {
        start: "2099-01-01T06:30:00Z",
        end: "2099-01-01T08:00:00Z",
        start_jalali: "۱۰:۰۰",
        end_jalali: "۱۱:۳۰",
        is_bookable: true,
        disabled_reason: null,
      },
    ]);
    mockedCreatePinBlockedSlot.mockRejectedValueOnce(
      new ApiError(409, "SLOT_ALREADY_RESERVED", "Reserved", {})
    );

    render(React.createElement(OwnerVenueDashboard, { venueId: 1 }));
    await user.click(await screen.findByRole("button", { name: "مسدود کن" }));

    expect(await screen.findByText("این اسلات قبلاً رزرو یا مسدود شده است.")).toBeInTheDocument();
    expect(screen.queryByText(/ممکن است رزرو یا قبلاً مسدود شده باشد/)).not.toBeInTheDocument();
  });

  it("m33: renders per-space pin error with retry while keeping other spaces' tables visible", async () => {
    const space1 = { id: 10, venue_id: 1, name: "سالن", panorama_status: "READY", is_active: true } as SpaceOut;
    const space2 = { id: 20, venue_id: 1, name: "تراس", panorama_status: "READY", is_active: true } as SpaceOut;
    const pin1 = { id: 100, space_id: 10, table_number: "A1", capacity: 4, reservation_fee_toman: 150_000, is_smoking: false } as unknown as TablePinOut;

    mockedGetOwnerVenue.mockResolvedValueOnce(makeVenue());
    mockedGetOwnerVenueSubscription.mockRejectedValueOnce(new Error("no sub"));
    mockedListOwnerVenueSpaces.mockResolvedValueOnce([space1, space2]);
    mockedListSpaceTablePins
      .mockResolvedValueOnce([pin1])
      .mockRejectedValueOnce(new Error("space 2 pins failed"));
    mockedListOwnerVenueBookings.mockResolvedValueOnce([]);
    mockedListVenueAddons.mockResolvedValueOnce([]);

    render(React.createElement(OwnerVenueDashboard, { venueId: 1 }));

    expect((await screen.findAllByText("A1")).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("دریافت میزهای فضای «تراس» با خطا مواجه شد.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "تلاش مجدد میزهای تراس" })).toBeInTheDocument();
  });

  it("m34: financial report renders Persian enum labels without raw status or wallet type/reason codes", async () => {
    mockedGetFinancialReport.mockResolvedValueOnce({
      payments: {
        total_toman: 150_000,
        count: 1,
        counts_by_status: { SUCCESS: 1 },
        rows: [makePaymentRow(1, "SUCCESS")],
      },
      wallet: {
        total_credit_toman: 150_000,
        total_debit_toman: 0,
        count: 1,
        rows: [
          {
            id: 1,
            user_id: 5,
            type: "CREDIT",
            amount_toman: 150_000,
            balance_after_toman: 150_000,
            reason: "UNKNOWN_RAW_REASON_CODE",
            booking_id: 10,
            created_at: "2026-11-20T10:00:00Z",
          },
        ],
      },
      subscriptions: { total_toman: 0, count: 0, rows: [] },
    });

    render(React.createElement(AdminFinancialReportPage));

    expect(await screen.findByText("موفق: 1")).toBeInTheDocument();
    expect(screen.getByText("واریز")).toBeInTheDocument();
    expect(screen.queryByText("UNKNOWN_RAW_REASON_CODE")).not.toBeInTheDocument();
    expect(screen.queryByText(/CREDIT/)).not.toBeInTheDocument();
    expect(screen.queryByText(/DEBIT/)).not.toBeInTheDocument();
  });

  it("m41: getReviewStatusBadge maps DRAFT to پیش‌نویس and unknown status to نامشخص", () => {
    expect(getReviewStatusBadge("DRAFT").label).toBe("پیش‌نویس");
    expect(getReviewStatusBadge("SOME_FUTURE_STATUS").label).toBe("نامشخص");
  });

  it("m43: admin reviews and financial report keep previous rows visible while refetching on filter change", async () => {
    const user = userEvent.setup();
    let resolveReviewsFilter!: (value: ReviewAdminOut[]) => void;
    mockedListAdminReviews
      .mockResolvedValueOnce([
        {
          id: 1,
          booking_id: 10,
          venue_id: 1,
          table_number: "A1",
          reviewer_name: "علی",
          rating: 5,
          text: "نظر قبلی",
          is_visible: true,
          created_at: "2026-11-20T10:00:00Z",
        },
      ])
      .mockImplementationOnce(
        () =>
          new Promise<ReviewAdminOut[]>((resolve) => {
            resolveReviewsFilter = resolve;
          })
      );

    render(React.createElement(AdminReviewsPage));
    expect(await screen.findByText("نظر قبلی")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("فیلتر وضعیت نمایش"), "hidden");
    expect(screen.getByText("نظر قبلی")).toBeInTheDocument();
    expect(screen.getByText("در حال به‌روزرسانی نظرها...")).toBeInTheDocument();

    await act(async () => {
      resolveReviewsFilter([]);
      await Promise.resolve();
    });

    cleanup();
    vi.resetAllMocks();

    let resolveReportFilter!: (value: FinancialReportOut) => void;
    mockedGetFinancialReport
      .mockResolvedValueOnce(makeReport([makePaymentRow(1, "SUCCESS")]))
      .mockImplementationOnce(
        () =>
          new Promise<FinancialReportOut>((resolve) => {
            resolveReportFilter = resolve;
          })
      );

    render(React.createElement(AdminFinancialReportPage));
    expect(await screen.findByText("#1001")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("وضعیت پرداخت"), "FAILED");
    expect(screen.getByText("#1001")).toBeInTheDocument();
    expect(screen.getByText("در حال به‌روزرسانی گزارش مالی...")).toBeInTheDocument();

    await act(async () => {
      resolveReportFilter(makeReport([]));
      await Promise.resolve();
    });
  });
});
