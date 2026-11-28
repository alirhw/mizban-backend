// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";

import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import VenueDetailPage from "@/app/venues/[slug]/page";
import PanoramaViewer from "@/components/PanoramaViewer";
import { VenuePanoramaExplorer } from "@/components/VenuePanoramaExplorer";
import {
  getPublicSpacePanorama,
  getPublicVenueBySlug,
  getMyWallet,
  initiateBooking,
  listPublicVenueSpaces,
  listTableReviews,
  listVenueReviews,
  listVenueSlots,
  type BookingInitiateOut,
  type PublicPanoramaOut,
  type PublicTablePinOut,
  type SpaceOut,
} from "@/lib/api";

type VenueDetail = Awaited<ReturnType<typeof getPublicVenueBySlug>>;

let mockSearchParams = new URLSearchParams("");
const mockRouter = {
  push: vi.fn(),
  replace: vi.fn(),
  prefetch: vi.fn(),
};

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

vi.mock("next/navigation", () => ({
  useRouter: () => mockRouter,
  useSearchParams: () => mockSearchParams,
  notFound: vi.fn(),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    user: { id: 1, phone_number: "09123456789", full_name: "علی", role: "CUSTOMER" },
    loading: false,
  }),
}));

vi.mock("pannellum/build/pannellum.css", () => ({}));
vi.mock("pannellum/build/pannellum.js", () => ({}));

vi.mock("next/dynamic", () => ({
  default: () =>
    function MockPanoramaViewer({
      pins,
      selectedPinId,
      onSelectPin,
    }: {
      imageUrl: string;
      pins: PublicTablePinOut[];
      selectedPinId: number | null;
      onSelectPin: (pin: PublicTablePinOut | null) => void;
    }) {
      return React.createElement(
        "div",
        { "data-testid": "mock-panorama", "data-selected-pin": selectedPinId ?? "" },
        pins.map((pin) =>
          React.createElement(
            "button",
            {
              key: pin.id,
              type: "button",
              "data-testid": `mock-pin-${pin.id}`,
              onClick: () => onSelectPin(pin),
            },
            `میز ${pin.table_number}`
          )
        ),
        React.createElement(
          "button",
          {
            type: "button",
            "data-testid": "mock-panorama-bg",
            onClick: () => onSelectPin(null),
          },
          "پس‌زمینه"
        )
      );
    },
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    getPublicSpacePanorama: vi.fn(),
    getPublicVenueBySlug: vi.fn(),
    getMyWallet: vi.fn(),
    initiateBooking: vi.fn(),
    listPublicVenueSpaces: vi.fn(),
    listTableReviews: vi.fn(),
    listVenueReviews: vi.fn(),
    listVenueSlots: vi.fn(),
  };
});

const mockedGetPublicSpacePanorama = vi.mocked(getPublicSpacePanorama);
const mockedGetPublicVenueBySlug = vi.mocked(getPublicVenueBySlug);
const mockedGetMyWallet = vi.mocked(getMyWallet);
const mockedInitiateBooking = vi.mocked(initiateBooking);
const mockedListPublicVenueSpaces = vi.mocked(listPublicVenueSpaces);
const mockedListTableReviews = vi.mocked(listTableReviews);
const mockedListVenueReviews = vi.mocked(listVenueReviews);
const mockedListVenueSlots = vi.mocked(listVenueSlots);

const SPACE_1: SpaceOut = {
  id: 1,
  venue_id: 1,
  name: "سالن اصلی",
  description: "",
  display_order: 1,
  is_active: true,
  active_panorama_id: "p1",
  panorama_status: "READY",
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
};
const SPACE_2: SpaceOut = {
  id: 2,
  venue_id: 1,
  name: "تراس",
  description: "",
  display_order: 2,
  is_active: true,
  active_panorama_id: "p2",
  panorama_status: "READY",
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
};

function makePin(id: number, tableNumber: string, overrides: Partial<PublicTablePinOut> = {}): PublicTablePinOut {
  return {
    id,
    table_number: tableNumber,
    capacity: 4,
    pitch: 10,
    yaw: 20,
    description: "",
    reservation_fee_toman: 150_000,
    is_smoking: false,
    ...overrides,
  };
}

function makePanorama(spaceId: number, pins: PublicTablePinOut[]): PublicPanoramaOut {
  return {
    space_id: spaceId,
    space_name: spaceId === 1 ? "سالن اصلی" : "تراس",
    venue_id: 1,
    venue_name: "کافه تست",
    panorama_image_id: `pano-${spaceId}`,
    image_url: `https://cdn.example.test/space-${spaceId}.jpg`,
    thumbnail_url: null,
    width: 4000,
    height: 2000,
    pins,
  };
}

function makeLockedBooking(): BookingInitiateOut {
  const now = Date.now();
  return {
    booking_id: 99,
    id: 99,
    status: "PENDING_PAYMENT",
    venue_id: 1,
    table_pin_id: 11,
    start_at: "2099-01-01T10:00:00Z",
    end_at: "2099-01-01T11:30:00Z",
    slot_date: "2099-01-01",
    slot_start_time: "10:00",
    locked_at: new Date(now).toISOString(),
    lock_expires_at: new Date(now + 600_000).toISOString(),
    amount_online_toman: 150_000,
    amount_in_person_toman: 0,
    start_jalali: "۱۴۷۷/۱۰/۱۱ ۱۰:۰۰",
    end_jalali: "۱۴۷۷/۱۰/۱۱ ۱۱:۳۰",
    jalali_start_datetime: "۱۴۷۷/۱۰/۱۱ ۱۰:۰۰",
    jalali_end_datetime: "۱۴۷۷/۱۰/۱۱ ۱۱:۳۰",
    jalali_date: "۱۴۷۷/۱۰/۱۱",
  };
}

describe("F-02 reproduction tests (M2, M4, m20, m19)", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockSearchParams = new URLSearchParams("");
    mockedListTableReviews.mockResolvedValue({
      average_rating: null,
      review_count: 0,
      reviews: [],
    });
    mockedListVenueSlots.mockResolvedValue([]);
    mockedGetMyWallet.mockResolvedValue({ balance_toman: 0, entries: [] });
  });

  afterEach(() => {
    cleanup();
  });

  it("M2: resumes a booking URL targeting a pin in space 2+", async () => {
    mockSearchParams = new URLSearchParams(
      "pin=22&date=2099-01-01&slot=2099-01-01T10:00:00Z&addons=5&step=review"
    );
    const pinSpace1 = makePin(11, "A1");
    const pinSpace2 = makePin(22, "B2");
    mockedGetPublicSpacePanorama.mockResolvedValueOnce(makePanorama(2, [pinSpace2]));

    render(
      React.createElement(VenuePanoramaExplorer, {
        venueId: 1,
        venueName: "کافه تست",
        venueSlug: "test-cafe",
        designAddons: [
          {
            id: 5,
            title: "شمع‌آرایی",
            fee: 50_000,
            is_active: true,
          },
        ],
        spaces: [SPACE_1, SPACE_2],
        initialSpaceId: 1,
        initialPanorama: makePanorama(1, [pinSpace1]),
      })
    );

    expect(await screen.findByText(/رزرو میز «B2»/)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "تراس" })).toHaveAttribute("aria-selected", "true");
  });

  it("M4: disables space tabs and blocks switching when a booking lock is held", async () => {
    const user = userEvent.setup();
    mockSearchParams = new URLSearchParams(
      "pin=11&date=2099-01-01&slot=2099-01-01T10:00:00Z&step=review"
    );
    const pin11 = makePin(11, "A1");
    const pin22 = makePin(22, "B2");
    mockedInitiateBooking.mockResolvedValueOnce(makeLockedBooking());
    mockedGetPublicSpacePanorama.mockResolvedValueOnce(makePanorama(2, [pin22]));

    render(
      React.createElement(VenuePanoramaExplorer, {
        venueId: 1,
        venueName: "کافه تست",
        venueSlug: "test-cafe",
        designAddons: [],
        spaces: [SPACE_1, SPACE_2],
        initialSpaceId: 1,
        initialPanorama: makePanorama(1, [pin11]),
      })
    );

    await user.click(screen.getByRole("button", { name: "تایید و قفل موقت میز" }));
    await screen.findByText("میز برای شما به‌صورت موقت قفل شد");

    const terraceTab = screen.getByRole("tab", { name: "تراس" });
    expect(terraceTab).toBeDisabled();
    expect(terraceTab).toHaveAttribute("aria-disabled", "true");
    await user.click(terraceTab);
    expect(mockedGetPublicSpacePanorama).not.toHaveBeenCalled();
    expect(screen.getByText("میز برای شما به‌صورت موقت قفل شد")).toBeInTheDocument();
  });

  it("m20: keeps details panel synced to bookingPin and restarts unlocked flow on pin B", async () => {
    const user = userEvent.setup();
    const pin11 = makePin(11, "A1");
    const pin12 = makePin(12, "A2");

    render(
      React.createElement(VenuePanoramaExplorer, {
        venueId: 1,
        venueName: "کافه تست",
        venueSlug: "test-cafe",
        designAddons: [],
        spaces: [SPACE_1],
        initialSpaceId: 1,
        initialPanorama: makePanorama(1, [pin11, pin12]),
      })
    );

    await user.click(screen.getByTestId("mock-pin-11"));
    await user.click(screen.getByRole("button", { name: "انتخاب این میز" }));
    expect(screen.getByText(/رزرو میز «A1»/)).toBeInTheDocument();

    await user.click(screen.getByTestId("mock-pin-12"));
    expect(screen.getByText(/رزرو میز «A2»/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "بستن" }));
    expect(screen.queryByText(/رزرو میز «A2»/)).not.toBeInTheDocument();
  });

  it("m19: highlights selected pin once Pannellum finishes loading hotspots", async () => {
    Object.defineProperty(window, "WebGLRenderingContext", {
      value: function WebGLRenderingContext() {},
      configurable: true,
    });
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({} as WebGLRenderingContext);

    let onLoadCallback: (() => void) | undefined;
    (window as unknown as { pannellum?: unknown }).pannellum = {
      viewer: (
        container: HTMLElement,
        config: {
          hotSpots?: Array<{ createTooltipFunc?: (div: HTMLElement) => void }>;
        }
      ) => {
        for (const hs of config.hotSpots ?? []) {
          const div = document.createElement("div");
          container.appendChild(div);
          hs.createTooltipFunc?.(div);
        }
        return {
          on: (event: string, cb: () => void) => {
            if (event === "load") {
              onLoadCallback = cb;
            }
          },
          destroy: vi.fn(),
        };
      },
    };

    const pin11 = makePin(11, "A1");
    render(
      React.createElement(PanoramaViewer, {
        imageUrl: "https://cdn.example.test/space-1.jpg",
        pins: [pin11],
        selectedPinId: 11,
        onSelectPin: vi.fn(),
      })
    );

    const hotspotBtn = await screen.findByRole("button", { name: "میز A1" });
    await act(async () => {
      onLoadCallback?.();
    });

    await waitFor(() => expect(hotspotBtn).toHaveAttribute("aria-pressed", "true"));
    expect(hotspotBtn.className).toContain("ring-4");
  });
});

describe("F-02 panorama, venue & resume fixes", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockSearchParams = new URLSearchParams("");
    mockedListTableReviews.mockResolvedValue({
      average_rating: null,
      review_count: 0,
      reviews: [],
    });
    mockedListVenueSlots.mockResolvedValue([]);
    mockedGetMyWallet.mockResolvedValue({ balance_toman: 0, entries: [] });
  });

  afterEach(() => {
    cleanup();
  });

  it("M2: shows Persian alert for unknown resume pin and does not fetch extra panoramas without pin param", async () => {
    mockSearchParams = new URLSearchParams(
      "pin=999&date=2099-01-01&slot=2099-01-01T10:00:00Z"
    );
    mockedGetPublicSpacePanorama.mockRejectedValueOnce(new Error("space 2 failed"));

    render(
      React.createElement(VenuePanoramaExplorer, {
        venueId: 1,
        venueName: "کافه تست",
        venueSlug: "test-cafe",
        designAddons: [],
        spaces: [SPACE_1, SPACE_2],
        initialSpaceId: 1,
        initialPanorama: makePanorama(1, [makePin(11, "A1")]),
      })
    );

    expect(
      await screen.findByText("رزرو موردنظر یافت نشد؛ لطفاً دوباره میز را انتخاب کنید.")
    ).toBeInTheDocument();

    cleanup();
    vi.clearAllMocks();
    mockSearchParams = new URLSearchParams("");
    render(
      React.createElement(VenuePanoramaExplorer, {
        venueId: 1,
        venueName: "کافه تست",
        venueSlug: "test-cafe",
        designAddons: [],
        spaces: [SPACE_1, SPACE_2],
        initialSpaceId: 1,
        initialPanorama: makePanorama(1, [makePin(11, "A1")]),
      })
    );
    expect(mockedGetPublicSpacePanorama).not.toHaveBeenCalled();
  });

  it("M4: allows switching space tabs when BookingFlow is pre-lock", async () => {
    const user = userEvent.setup();
    const pin11 = makePin(11, "A1");
    const pin22 = makePin(22, "B2");
    mockedGetPublicSpacePanorama.mockResolvedValueOnce(makePanorama(2, [pin22]));

    render(
      React.createElement(VenuePanoramaExplorer, {
        venueId: 1,
        venueName: "کافه تست",
        venueSlug: "test-cafe",
        designAddons: [],
        spaces: [SPACE_1, SPACE_2],
        initialSpaceId: 1,
        initialPanorama: makePanorama(1, [pin11]),
      })
    );

    await user.click(screen.getByTestId("mock-pin-11"));
    await user.click(screen.getByRole("button", { name: "انتخاب این میز" }));
    expect(screen.getByText(/رزرو میز «A1»/)).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "تراس" }));
    expect(await screen.findByTestId("mock-pin-22")).toBeInTheDocument();
    expect(screen.queryByText(/رزرو میز «A1»/)).not.toBeInTheDocument();
  });

  it("m6: renders error and retry button when table reviews fetch fails instead of empty message", async () => {
    const user = userEvent.setup();
    const pin11 = makePin(11, "A1");
    mockedListTableReviews
      .mockRejectedValueOnce(new Error("reviews failed"))
      .mockResolvedValueOnce({
        average_rating: 5,
        review_count: 1,
        reviews: [
          {
            id: 1,
            table_number: "A1",
            reviewer_name: "سارا",
            rating: 5,
            text: "عالی بود",
            created_at: "2026-11-20T10:00:00Z",
          },
        ],
      });

    render(
      React.createElement(VenuePanoramaExplorer, {
        venueId: 1,
        venueName: "کافه تست",
        venueSlug: "test-cafe",
        designAddons: [],
        spaces: [SPACE_1],
        initialSpaceId: 1,
        initialPanorama: makePanorama(1, [pin11]),
      })
    );

    await user.click(screen.getByTestId("mock-pin-11"));
    expect(await screen.findByText("دریافت نظرات این میز با خطا مواجه شد.")).toBeInTheDocument();
    expect(screen.queryByText("هنوز نظری برای این میز ثبت نشده است.")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "تلاش مجدد" }));
    expect(await screen.findByText("عالی بود")).toBeInTheDocument();
  });

  it("m7: paginates table reviews with 20 per page, shows count, and hides button at end", async () => {
    const user = userEvent.setup();
    const pin11 = makePin(11, "A1");
    const firstPage = Array.from({ length: 20 }, (_, i) => ({
      id: i + 1,
      table_number: "A1",
      reviewer_name: `کاربر ${i + 1}`,
      rating: 5,
      text: `نظر ${i + 1}`,
      created_at: "2026-11-20T10:00:00Z",
    }));
    const secondPage = [
      {
        id: 21,
        table_number: "A1",
        reviewer_name: "کاربر ۲۱",
        rating: 4,
        text: "نظر ۲۱",
        created_at: "2026-11-20T10:00:00Z",
      },
    ];

    mockedListTableReviews
      .mockResolvedValueOnce({ average_rating: 4.9, review_count: 21, reviews: firstPage })
      .mockResolvedValueOnce({ average_rating: 4.9, review_count: 21, reviews: secondPage });

    render(
      React.createElement(VenuePanoramaExplorer, {
        venueId: 1,
        venueName: "کافه تست",
        venueSlug: "test-cafe",
        designAddons: [],
        spaces: [SPACE_1],
        initialSpaceId: 1,
        initialPanorama: makePanorama(1, [pin11]),
      })
    );

    await user.click(screen.getByTestId("mock-pin-11"));
    expect(await screen.findByText(/نمایش 20 از 21 نظر/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "نمایش بیشتر" }));

    expect(await screen.findByText(/نمایش 21 از 21 نظر/)).toBeInTheDocument();
    expect(screen.getByText("نظر ۲۱")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "نمایش بیشتر" })).not.toBeInTheDocument();
  });

  it("m20: ignores clicking another pin with a Persian note when BookingFlow is locked", async () => {
    const user = userEvent.setup();
    mockSearchParams = new URLSearchParams(
      "pin=11&date=2099-01-01&slot=2099-01-01T10:00:00Z&step=review"
    );
    const pin11 = makePin(11, "A1");
    const pin12 = makePin(12, "A2");
    mockedInitiateBooking.mockResolvedValueOnce(makeLockedBooking());

    render(
      React.createElement(VenuePanoramaExplorer, {
        venueId: 1,
        venueName: "کافه تست",
        venueSlug: "test-cafe",
        designAddons: [],
        spaces: [SPACE_1],
        initialSpaceId: 1,
        initialPanorama: makePanorama(1, [pin11, pin12]),
      })
    );

    await user.click(screen.getByRole("button", { name: "تایید و قفل موقت میز" }));
    await screen.findByText("میز برای شما به‌صورت موقت قفل شد");

    await user.click(screen.getByTestId("mock-pin-12"));
    expect(
      screen.getByText("برای انتخاب میز دیگر، ابتدا فرآیند رزرو یا پرداخت فعلی را تکمیل یا لغو کنید.")
    ).toBeInTheDocument();
    expect(screen.getByText(/رزرو میز «A1»/)).toBeInTheDocument();
  });

  it("m28: VenueDetailPage degrades spaces, panorama, and reviews errors into explicit error states", async () => {
    const venueFixture = {
      id: 1,
      name: "کافه تست",
      slug: "test-cafe",
      venue_type: "CAFE",
      city: "تهران",
      address: "خیابان ولیعصر",
      description: "",
      opening_hours: [],
      design_addons: [],
    } as unknown as VenueDetail;

    // Case 1: only reviews fetch fails -> header + panorama still render, reviews show error
    mockedGetPublicVenueBySlug.mockResolvedValueOnce(venueFixture);
    mockedListPublicVenueSpaces.mockResolvedValueOnce([SPACE_1]);
    mockedGetPublicSpacePanorama.mockResolvedValueOnce(makePanorama(1, [makePin(11, "A1")]));
    mockedListVenueReviews.mockRejectedValueOnce(new Error("reviews 500"));

    const jsx1 = await VenueDetailPage({ params: Promise.resolve({ slug: "test-cafe" }) });
    render(jsx1);
    expect(screen.getByText("کافه تست")).toBeInTheDocument();
    expect(screen.getByTestId("mock-panorama")).toBeInTheDocument();
    expect(screen.getByText("دریافت نظرات مشتریان با خطا مواجه شد.")).toBeInTheDocument();
    expect(screen.queryByText("هنوز نظری ثبت نشده است.")).not.toBeInTheDocument();

    cleanup();
    vi.resetAllMocks();
    mockedListTableReviews.mockResolvedValue({ average_rating: null, review_count: 0, reviews: [] });

    // Case 2: spaces fetch fails -> explicit spaces error + retry
    mockedGetPublicVenueBySlug.mockResolvedValueOnce(venueFixture);
    mockedListPublicVenueSpaces.mockRejectedValueOnce(new Error("spaces 500"));
    mockedListVenueReviews.mockResolvedValueOnce({ average_rating: null, review_count: 0, reviews: [] });

    const jsx2 = await VenueDetailPage({ params: Promise.resolve({ slug: "test-cafe" }) });
    render(jsx2);
    expect(screen.getByText("دریافت فهرست فضاهای مجموعه با خطا مواجه شد.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "تلاش مجدد" })).toBeInTheDocument();

    cleanup();
    vi.resetAllMocks();
    mockedListTableReviews.mockResolvedValue({ average_rating: null, review_count: 0, reviews: [] });

    // Case 3: initial panorama fetch fails -> explicit panorama error
    mockedGetPublicVenueBySlug.mockResolvedValueOnce(venueFixture);
    mockedListPublicVenueSpaces.mockResolvedValueOnce([SPACE_1]);
    mockedGetPublicSpacePanorama.mockRejectedValueOnce(new Error("panorama 500"));
    mockedListVenueReviews.mockResolvedValueOnce({ average_rating: null, review_count: 0, reviews: [] });

    const jsx3 = await VenueDetailPage({ params: Promise.resolve({ slug: "test-cafe" }) });
    render(jsx3);
    expect(screen.getByText("دریافت تصویر ۳۶۰ درجه این فضا با خطا مواجه شد.")).toBeInTheDocument();
  });

  it("m29: displays unmapped table numbers note when pins lack coordinates and hides it when all are mapped", () => {
    const mapped = makePin(11, "A1");
    const unmapped = makePin(12, "B9", { pitch: null, yaw: null });

    render(
      React.createElement(VenuePanoramaExplorer, {
        venueId: 1,
        venueName: "کافه تست",
        venueSlug: "test-cafe",
        designAddons: [],
        spaces: [SPACE_1],
        initialSpaceId: 1,
        initialPanorama: makePanorama(1, [mapped, unmapped]),
      })
    );

    expect(
      screen.getByText(/میزهای B9 روی تصویر ۳۶۰ درجه نمایش داده نمی‌شوند چون مختصات ندارند/)
    ).toBeInTheDocument();

    cleanup();
    render(
      React.createElement(VenuePanoramaExplorer, {
        venueId: 1,
        venueName: "کافه تست",
        venueSlug: "test-cafe",
        designAddons: [],
        spaces: [SPACE_1],
        initialSpaceId: 1,
        initialPanorama: makePanorama(1, [mapped]),
      })
    );

    expect(screen.queryByText(/مختصات ندارند/)).not.toBeInTheDocument();
  });
});
