// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";

import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import AdminReviewsPage from "@/app/admin/reviews/page";
import { Header } from "@/components/Header";
import {
  ApiError,
  hideReview,
  listAdminReviews,
  listPublicVenues,
  showReview,
  type ReviewAdminOut,
} from "@/lib/api";

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
    listPublicVenues: vi.fn(),
    listAdminReviews: vi.fn(),
    hideReview: vi.fn(),
    showReview: vi.fn(),
  };
});

const mockedListPublicVenues = vi.mocked(listPublicVenues);
const mockedListAdminReviews = vi.mocked(listAdminReviews);
const mockedHideReview = vi.mocked(hideReview);
const mockedShowReview = vi.mocked(showReview);

function makeAdminReview(overrides: Partial<ReviewAdminOut>): ReviewAdminOut {
  return {
    id: 1,
    booking_id: 50,
    venue_id: 5,
    table_number: "2",
    rating: 5,
    text: "بسیار عالی",
    reviewer_name: "سارا",
    created_at: "2026-11-28T08:00:00Z",
    is_visible: true,
    ...overrides,
  };
}

describe("T-038 frontend: Admin review moderation UI & Header", () => {
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

  it("Header shows مدیریت نظرها link only when user.role is ADMIN and hides it for customer, owner, and logged-out users", () => {
    const { rerender } = render(React.createElement(Header));
    const adminLink = screen.getByRole("link", { name: "مدیریت نظرها" });
    expect(adminLink).toHaveAttribute("href", "/admin/reviews");

    for (const role of ["CUSTOMER", "VENUE_OWNER"]) {
      mockAuthState = { user: { id: 2, phone: "09121111111", role }, loading: false, logout: vi.fn() };
      rerender(React.createElement(Header));
      expect(screen.queryByRole("link", { name: "مدیریت نظرها" })).not.toBeInTheDocument();
    }

    mockAuthState = { user: null, loading: false, logout: vi.fn() };
    rerender(React.createElement(Header));
    expect(screen.queryByRole("link", { name: "مدیریت نظرها" })).not.toBeInTheDocument();
  });

  it("filters admin reviews by venue and visibility", async () => {
    const user = userEvent.setup();
    mockedListPublicVenues.mockResolvedValueOnce([
      { id: 5, name: "کافه تست", slug: "test-cafe", city: "تهران", venue_type: "CAFE", address: "", description: "" },
    ]);
    mockedListAdminReviews
      .mockResolvedValueOnce([makeAdminReview({ id: 1, venue_id: 5, is_visible: true })])
      .mockResolvedValueOnce([makeAdminReview({ id: 1, venue_id: 5, is_visible: true })])
      .mockResolvedValueOnce([makeAdminReview({ id: 2, venue_id: 5, is_visible: false, text: "نظر پنهان" })]);

    render(React.createElement(AdminReviewsPage));
    expect(await screen.findByText("بسیار عالی")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("فیلتر مجموعه"), "5");
    await waitFor(() =>
      expect(mockedListAdminReviews).toHaveBeenLastCalledWith({
        venue_id: 5,
        is_visible: undefined,
        limit: 20,
        offset: 0,
      })
    );

    await user.selectOptions(screen.getByLabelText("فیلتر وضعیت نمایش"), "hidden");
    await waitFor(() =>
      expect(mockedListAdminReviews).toHaveBeenLastCalledWith({
        venue_id: 5,
        is_visible: false,
        limit: 20,
        offset: 0,
      })
    );
    expect(await screen.findByText("نظر پنهان")).toBeInTheDocument();
  });

  it("hides a visible review in place and shows a hidden review in place with no delete button anywhere", async () => {
    const user = userEvent.setup();
    mockedListPublicVenues.mockResolvedValueOnce([]);
    mockedListAdminReviews.mockResolvedValueOnce([
      makeAdminReview({ id: 10, is_visible: true, text: "متن اول" }),
      makeAdminReview({ id: 11, is_visible: false, text: "متن دوم" }),
    ]);
    mockedHideReview.mockResolvedValueOnce(
      makeAdminReview({ id: 10, is_visible: false, text: "متن اول" })
    );
    mockedShowReview.mockResolvedValueOnce(
      makeAdminReview({ id: 11, is_visible: true, text: "متن دوم" })
    );

    render(React.createElement(AdminReviewsPage));
    expect(await screen.findByText("متن اول")).toBeInTheDocument();

    expect(screen.queryByRole("button", { name: /حذف/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "پنهان کردن" }));
    await waitFor(() => expect(mockedHideReview).toHaveBeenCalledWith(10));
    expect(mockedListAdminReviews).toHaveBeenCalledTimes(1);

    const showButtons = screen.getAllByRole("button", { name: "نمایش دادن" });
    expect(showButtons).toHaveLength(2);

    await user.click(showButtons[1]!);
    await waitFor(() => expect(mockedShowReview).toHaveBeenCalledWith(11));
    expect(mockedListAdminReviews).toHaveBeenCalledTimes(1);
    expect(screen.getAllByRole("button", { name: "پنهان کردن" })).toHaveLength(1);
  });

  it("shows Persian admin-only message on 403 without raw error_code", async () => {
    mockAuthState = {
      user: { id: 2, phone: "09121111111", role: "CUSTOMER" },
      loading: false,
      logout: vi.fn(),
    };
    mockedListPublicVenues.mockResolvedValueOnce([]);
    mockedListAdminReviews.mockRejectedValueOnce(
      new ApiError(403, "FORBIDDEN", "Forbidden", {})
    );

    render(React.createElement(AdminReviewsPage));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).not.toContain("FORBIDDEN");
    expect(alert.textContent).toContain("فقط مدیران پلتفرم");
  });
});
