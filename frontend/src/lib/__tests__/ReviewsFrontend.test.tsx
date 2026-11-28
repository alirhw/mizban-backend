// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";

import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import MyBookingsPage from "@/app/my-bookings/page";
import VenueDetailPage from "@/app/venues/[slug]/page";
import { VenuePanoramaExplorer } from "@/components/VenuePanoramaExplorer";
import {
  ApiError,
  createReview,
  getMyWallet,
  getPublicSpacePanorama,
  getPublicVenueBySlug,
  listMyBookings,
  listMyReviews,
  listPublicVenueSpaces,
  listTableReviews,
  listVenueReviews,
  type CustomerBookingOut,
  type ReviewMineOut,
} from "@/lib/api";

const mockRouter = {
  push: vi.fn(),
  replace: vi.fn(),
  prefetch: vi.fn(),
};

const mockAuthState = {
  user: {
    id: 1,
    phone_number: "09123456789",
    full_name: "علی",
    role: "CUSTOMER",
  },
  loading: false,
};

vi.mock("next/navigation", () => ({
  useRouter: () => mockRouter,
  useSearchParams: () => new URLSearchParams("pin=10&date=2099-01-01&slot=2099-01-01T10:00:00Z&step=slot"),
  notFound: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    scroll: _scroll,
    ...rest
  }: {
    href: string;
    children: React.ReactNode;
    scroll?: boolean;
  } & React.AnchorHTMLAttributes<HTMLAnchorElement>) =>
    React.createElement("a", { href, ...rest }, children),
}));

vi.mock("next/dynamic", () => ({
  default: () =>
    function MockPanoramaViewer() {
      return React.createElement("div", { "data-testid": "mock-panorama" });
    },
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => mockAuthState,
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    createReview: vi.fn(),
    listMyReviews: vi.fn(),
    listVenueReviews: vi.fn(),
    listTableReviews: vi.fn(),
    listMyBookings: vi.fn(),
    getMyWallet: vi.fn(),
    getPublicVenueBySlug: vi.fn(),
    listPublicVenueSpaces: vi.fn(),
    getPublicSpacePanorama: vi.fn(),
  };
});

const mockedCreateReview = vi.mocked(createReview);
const mockedListMyReviews = vi.mocked(listMyReviews);
const mockedListVenueReviews = vi.mocked(listVenueReviews);
const mockedListTableReviews = vi.mocked(listTableReviews);
const mockedListMyBookings = vi.mocked(listMyBookings);
const mockedGetMyWallet = vi.mocked(getMyWallet);
const mockedGetPublicVenueBySlug = vi.mocked(getPublicVenueBySlug);
const mockedListPublicVenueSpaces = vi.mocked(listPublicVenueSpaces);
const mockedGetPublicSpacePanorama = vi.mocked(getPublicSpacePanorama);

function makeBooking(overrides: Partial<CustomerBookingOut>): CustomerBookingOut {
  return {
    booking_id: 101,
    venue_name: "کافه تست",
    venue_slug: "test-cafe",
    table_number: "4",
    status: "COMPLETED",
    slot_date: "2026-11-20",
    jalali_date: "۱۴۰۵/۰۸/۲۹",
    slot_start_time: "10:00",
    start_at: "2026-11-20T10:00:00Z",
    end_at: "2026-11-20T12:00:00Z",
    start_jalali: "۱۴۰۵/۰۸/۲۹ ۱۳:۳۰",
    end_jalali: "۱۴۰۵/۰۸/۲۹ ۱۵:۳۰",
    amount_online_toman: 150_000,
    amount_in_person_toman: 0,
    is_cancellable: false,
    cancel_refund_toman: 0,
    created_at: "2026-11-19T10:00:00Z",
    ...overrides,
  };
}

describe("T-037 frontend: Reviews UI", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("renders venue reviews section with 1-decimal average, review count, list, and empty state", async () => {
    mockedGetPublicVenueBySlug.mockResolvedValue({
      id: 5,
      name: "کافه تست",
      slug: "test-cafe",
      city: "تهران",
      venue_type: "CAFE",
      address: "ولیعصر",
      description: "",
      operating_hours: [],
      design_addons: [],
    });
    mockedListPublicVenueSpaces.mockResolvedValue([]);
    mockedListVenueReviews.mockResolvedValueOnce({
      average_rating: 4.5,
      review_count: 25,
      reviews: [
        {
          id: 1,
          rating: 5,
          text: "بسیار دنج و تمیز",
          reviewer_name: "سارا",
          table_number: "4",
          created_at: "2026-11-25T10:00:00Z",
        },
      ],
    });

    const node = await VenueDetailPage({
      params: Promise.resolve({ slug: "test-cafe" }),
    });
    render(node);

    expect(screen.getByText("نظرات مشتریان")).toBeInTheDocument();
    expect(screen.getByText("★ 4.5")).toBeInTheDocument();
    expect(screen.getByText("(25 نظر)")).toBeInTheDocument();
    expect(screen.getByText("سارا")).toBeInTheDocument();
    expect(screen.getByText("بسیار دنج و تمیز")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "نمایش نظرات بیشتر" })).toBeInTheDocument();

    cleanup();
    mockedListVenueReviews.mockResolvedValueOnce({
      average_rating: null,
      review_count: 0,
      reviews: [],
    });

    const emptyNode = await VenueDetailPage({
      params: Promise.resolve({ slug: "test-cafe" }),
    });
    render(emptyNode);

    expect(screen.getByText("هنوز نظری ثبت نشده است.")).toBeInTheDocument();
  });

  it("renders table pin reviews inside VenuePanoramaExplorer when a pin is selected", async () => {
    mockedListTableReviews.mockResolvedValueOnce({
      average_rating: 4.0,
      review_count: 1,
      reviews: [
        {
          id: 9,
          rating: 4,
          text: "نورپردازی عالی کنار پنجره",
          reviewer_name: "Customer",
          table_number: "10",
          created_at: "2026-11-25T10:00:00Z",
        },
      ],
    });

    render(
      React.createElement(VenuePanoramaExplorer, {
        venueId: 5,
        venueName: "کافه تست",
        venueSlug: "test-cafe",
        designAddons: [],
        spaces: [
          {
            id: 1,
            venue_id: 5,
            name: "سالن اصلی",
            description: "",
            display_order: 1,
            is_active: true,
            active_panorama_id: "p1",
            panorama_status: "READY",
            created_at: "2026-11-01T00:00:00Z",
            updated_at: "2026-11-01T00:00:00Z",
          },
        ],
        initialSpaceId: 1,
        initialPanorama: {
          space_id: 1,
          space_name: "سالن اصلی",
          venue_id: 5,
          venue_name: "کافه تست",
          panorama_image_id: "p1",
          image_url: "https://example.test/pano.jpg",
          thumbnail_url: null,
          width: 4000,
          height: 2000,
          pins: [
            {
              id: 10,
              table_number: "10",
              capacity: 4,
              pitch: 0,
              yaw: 0,
              description: "",
              reservation_fee_toman: 150_000,
              is_smoking: false,
            },
          ],
        },
      })
    );

    await waitFor(() => expect(mockedListTableReviews).toHaveBeenCalledWith(10, { limit: 20, offset: 0 }));
    expect(await screen.findByText("نورپردازی عالی کنار پنجره")).toBeInTheDocument();
    expect(screen.getByText(/★ 4\.0/)).toBeInTheDocument();
  });

  it("shows review action only on COMPLETED bookings and validates rating/text before submit", async () => {
    const user = userEvent.setup();
    mockedListMyBookings.mockResolvedValueOnce([
      makeBooking({ booking_id: 101, status: "COMPLETED" }),
      makeBooking({ booking_id: 102, status: "CONFIRMED" }),
    ]);
    mockedGetMyWallet.mockResolvedValueOnce({ balance_toman: 0, entries: [] });
    mockedListMyReviews.mockResolvedValueOnce([]);

    render(React.createElement(MyBookingsPage));

    const reviewButtons = await screen.findAllByRole("button", { name: "ثبت نظر" });
    expect(reviewButtons).toHaveLength(1);

    await user.click(reviewButtons[0]!);
    await user.click(screen.getByRole("button", { name: "ارسال نظر" }));
    expect(screen.getByRole("alert")).toHaveTextContent("امتیاز");
    expect(mockedCreateReview).not.toHaveBeenCalled();

    await user.click(screen.getByRole("radio", { name: "5 ستاره" }));
    await user.click(screen.getByRole("button", { name: "ارسال نظر" }));
    expect(screen.getByRole("alert")).toHaveTextContent("متن نظر");
    expect(mockedCreateReview).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("متن نظر"), {
      target: { value: "آ".repeat(1001) },
    });
    await user.click(screen.getByRole("button", { name: "ارسال نظر" }));
    expect(screen.getByRole("alert")).toHaveTextContent("۱۰۰۰ کاراکتر");
    expect(mockedCreateReview).not.toHaveBeenCalled();
  });

  it("submits review on COMPLETED booking and displays the submitted review instead of button", async () => {
    const user = userEvent.setup();
    mockedListMyBookings.mockResolvedValueOnce([
      makeBooking({ booking_id: 101, status: "COMPLETED" }),
    ]);
    mockedGetMyWallet.mockResolvedValueOnce({ balance_toman: 0, entries: [] });
    mockedListMyReviews.mockResolvedValueOnce([]);

    const createdReview: ReviewMineOut = {
      id: 55,
      booking_id: 101,
      rating: 5,
      text: "تجربه فوق‌العاده",
      reviewer_name: "علی",
      table_number: "4",
      created_at: "2026-11-28T08:00:00Z",
      is_visible: true,
    };
    mockedCreateReview.mockResolvedValueOnce(createdReview);

    render(React.createElement(MyBookingsPage));

    await user.click(await screen.findByRole("button", { name: "ثبت نظر" }));
    await user.click(screen.getByRole("radio", { name: "5 ستاره" }));
    await user.type(screen.getByLabelText("متن نظر"), "تجربه فوق‌العاده");
    await user.click(screen.getByRole("button", { name: "ارسال نظر" }));

    await waitFor(() =>
      expect(mockedCreateReview).toHaveBeenCalledWith({
        booking_id: 101,
        rating: 5,
        text: "تجربه فوق‌العاده",
      })
    );
    expect(await screen.findByText("تجربه فوق‌العاده")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "ثبت نظر" })).not.toBeInTheDocument();
  });

  it("handles 409 REVIEW_ALREADY_EXISTS by fetching listMyReviews and showing existing review, and maps 409 REVIEW_NOT_ELIGIBLE", async () => {
    const user = userEvent.setup();
    mockedListMyBookings.mockResolvedValueOnce([
      makeBooking({ booking_id: 101, status: "COMPLETED" }),
      makeBooking({ booking_id: 103, status: "COMPLETED" }),
    ]);
    mockedGetMyWallet.mockResolvedValueOnce({ balance_toman: 0, entries: [] });
    mockedListMyReviews.mockResolvedValueOnce([]);

    mockedCreateReview
      .mockRejectedValueOnce(
        new ApiError(409, "REVIEW_ALREADY_EXISTS", "Already exists", {})
      )
      .mockRejectedValueOnce(
        new ApiError(409, "REVIEW_NOT_ELIGIBLE", "Not eligible yet", {})
      );
    mockedListMyReviews.mockResolvedValueOnce([
      {
        id: 77,
        booking_id: 101,
        rating: 4,
        text: "نظر قبلی من",
        reviewer_name: "علی",
        table_number: "4",
        created_at: "2026-11-27T08:00:00Z",
        is_visible: true,
      },
    ]);

    render(React.createElement(MyBookingsPage));

    const buttons = await screen.findAllByRole("button", { name: "ثبت نظر" });
    await user.click(buttons[0]!);
    await user.click(screen.getByRole("radio", { name: "4 ستاره" }));
    await user.type(screen.getByLabelText("متن نظر"), "نظر جدید");
    await user.click(screen.getByRole("button", { name: "ارسال نظر" }));

    expect(await screen.findByText("نظر قبلی من")).toBeInTheDocument();
    expect(mockedListMyReviews).toHaveBeenCalledTimes(2);

    const remainingBtn = screen.getByRole("button", { name: "ثبت نظر" });
    await user.click(remainingBtn);
    await user.click(screen.getByRole("radio", { name: "3 ستاره" }));
    await user.type(screen.getByLabelText("متن نظر"), "تست زودهنگام");
    await user.click(screen.getByRole("button", { name: "ارسال نظر" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).not.toContain("REVIEW_NOT_ELIGIBLE");
    expect(alert.textContent).toContain("تکمیل و پایان زمان رزرو");
  });
});
