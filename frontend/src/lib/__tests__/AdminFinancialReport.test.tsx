// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";

import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import AdminFinancialReportPage from "@/app/admin/financial-report/page";
import { Header } from "@/components/Header";
import { ApiError, getFinancialReport, type FinancialReportOut } from "@/lib/api";

const mockRouter = {
  push: vi.fn(),
  replace: vi.fn(),
  prefetch: vi.fn(),
};

let mockAuthState: {
  user: { id: number; phone: string; role: string } | null;
  loading: boolean;
  logout: () => Promise<void>;
} = {
  user: { id: 1, phone: "09120000000", role: "ADMIN" },
  loading: false,
  logout: vi.fn(),
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
    getFinancialReport: vi.fn(),
    getUnreadCount: vi.fn().mockResolvedValue({ unread_count: 0 }),
  };
});

const mockedGetFinancialReport = vi.mocked(getFinancialReport);

function makeReport(overrides: Partial<FinancialReportOut> = {}): FinancialReportOut {
  return {
    payments: {
      total_toman: 300_000,
      count: 3,
      counts_by_status: {
        INITIATED: 0,
        PENDING: 0,
        SUCCESS: 2,
        FAILED: 1,
        TIMEOUT: 0,
      },
      rows: [
        {
          id: 1,
          booking_id: 10,
          customer_id: 5,
          provider_name: "sandbox",
          amount_toman: 100_000,
          status: "SUCCESS",
          created_at: "2026-11-28T08:00:00Z",
        },
        {
          id: 2,
          booking_id: 11,
          customer_id: 6,
          provider_name: "wallet",
          amount_toman: 200_000,
          status: "SUCCESS",
          created_at: "2026-11-28T09:00:00Z",
        },
      ],
    },
    wallet: {
      total_credit_toman: 150_000,
      total_debit_toman: 40_000,
      count: 1,
      rows: [
        {
          id: 9,
          user_id: 5,
          type: "CREDIT",
          amount_toman: 150_000,
          balance_after_toman: 150_000,
          reason: "BOOKING_CANCEL_REFUND",
          booking_id: 10,
          created_at: "2026-11-28T08:30:00Z",
        },
      ],
    },
    subscriptions: {
      total_toman: 0,
      count: 0,
      rows: [],
    },
    ...overrides,
  };
}

describe("T-040 frontend: Admin financial report page & Header", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuthState = {
      user: { id: 1, phone: "09120000000", role: "ADMIN" },
      loading: false,
      logout: vi.fn(),
    };
  });

  afterEach(() => {
    cleanup();
  });

  it("Header shows گزارش مالی link only when user.role is ADMIN and hides it for VENUE_OWNER, CUSTOMER, and logged-out users", () => {
    const { rerender } = render(React.createElement(Header));
    const reportLink = screen.getByRole("link", { name: "گزارش مالی" });
    expect(reportLink).toHaveAttribute("href", "/admin/financial-report");

    for (const role of ["VENUE_OWNER", "CUSTOMER"]) {
      mockAuthState = { user: { id: 2, phone: "09121111111", role }, loading: false, logout: vi.fn() };
      rerender(React.createElement(Header));
      expect(screen.queryByRole("link", { name: "گزارش مالی" })).not.toBeInTheDocument();
    }

    mockAuthState = { user: null, loading: false, logout: vi.fn() };
    rerender(React.createElement(Header));
    expect(screen.queryByRole("link", { name: "گزارش مالی" })).not.toBeInTheDocument();
  });

  it("renders server totals (total_toman, count, counts_by_status), payment rows, wallet section, and empty subscriptions state", async () => {
    mockedGetFinancialReport.mockResolvedValueOnce(makeReport());

    render(React.createElement(AdminFinancialReportPage));

    expect(await screen.findByText("گزارش مالی پلتفرم")).toBeInTheDocument();
    expect(screen.getByText("۳۰۰٬۰۰۰ تومان")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("موفق: 2")).toBeInTheDocument();
    expect(screen.getByText("ناموفق: 1")).toBeInTheDocument();
    expect(screen.getByText("sandbox")).toBeInTheDocument();
    expect(screen.getByText("بازپرداخت لغو رزرو")).toBeInTheDocument();
    expect(
      screen.getByText(/هنوز پرداخت آنلاین اشتراکی ثبت نشده است/)
    ).toBeInTheDocument();
  });

  it("re-fetches on payment_status filter change while displaying server totals rather than summing rows", async () => {
    const user = userEvent.setup();
    mockedGetFinancialReport
      .mockResolvedValueOnce(makeReport())
      .mockResolvedValueOnce(
        makeReport({
          payments: {
            total_toman: 300_000,
            count: 3,
            counts_by_status: {
              INITIATED: 0,
              PENDING: 0,
              SUCCESS: 2,
              FAILED: 1,
              TIMEOUT: 0,
            },
            rows: [
              {
                id: 3,
                booking_id: 12,
                customer_id: 7,
                provider_name: "sandbox",
                amount_toman: 50_000,
                status: "FAILED",
                created_at: "2026-11-28T10:00:00Z",
              },
            ],
          },
        })
      );

    render(React.createElement(AdminFinancialReportPage));
    await screen.findByText("گزارش مالی پلتفرم");

    await user.selectOptions(screen.getByLabelText("وضعیت پرداخت"), "FAILED");

    await waitFor(() =>
      expect(mockedGetFinancialReport).toHaveBeenLastCalledWith({
        payment_status: "FAILED",
        limit: 50,
        offset: 0,
      })
    );
    expect(await screen.findByText("#12")).toBeInTheDocument();
    expect(screen.getByText("۳۰۰٬۰۰۰ تومان")).toBeInTheDocument();
    expect(screen.queryByText("۵۰٬۰۰۰ تومان")).toBeInTheDocument();
  });

  it("sends from_date and to_date as picked and omits unset date bounds", async () => {
    mockedGetFinancialReport.mockResolvedValue(makeReport());

    render(React.createElement(AdminFinancialReportPage));
    await screen.findByText("گزارش مالی پلتفرم");

    expect(mockedGetFinancialReport).toHaveBeenCalledWith({
      limit: 50,
      offset: 0,
    });

    fireEvent.change(screen.getByLabelText("از تاریخ"), {
      target: { value: "2026-11-01" },
    });
    await waitFor(() =>
      expect(mockedGetFinancialReport).toHaveBeenLastCalledWith({
        from_date: "2026-11-01",
        limit: 50,
        offset: 0,
      })
    );

    fireEvent.change(screen.getByLabelText("تا تاریخ"), {
      target: { value: "2026-11-28" },
    });
    await waitFor(() =>
      expect(mockedGetFinancialReport).toHaveBeenLastCalledWith({
        from_date: "2026-11-01",
        to_date: "2026-11-28",
        limit: 50,
        offset: 0,
      })
    );
  });

  it("shows Persian admin-only message on 403 without raw error_code", async () => {
    mockAuthState = {
      user: { id: 2, phone: "09121111111", role: "VENUE_OWNER" },
      loading: false,
      logout: vi.fn(),
    };
    mockedGetFinancialReport.mockRejectedValueOnce(
      new ApiError(403, "FORBIDDEN", "Forbidden", {})
    );

    render(React.createElement(AdminFinancialReportPage));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).not.toContain("FORBIDDEN");
    expect(alert.textContent).toContain("فقط مدیران کل پلتفرم");
  });
});
