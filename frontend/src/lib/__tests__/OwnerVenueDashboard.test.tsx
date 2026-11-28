// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";

import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { OwnerVenueDashboard } from "@/components/OwnerVenueDashboard";
import {
  ApiError,
  createVenueAddon,
  deleteVenueAddon,
  getOwnerVenue,
  getOwnerVenueSubscription,
  listOwnerVenueBookings,
  listOwnerVenueSpaces,
  listVenueAddons,
  submitVenueForReview,
  updateVenueAddon,
  type DesignAddonOut,
  type VenueOwnerOut,
  type VenueSubscriptionOut,
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
    full_name: "مالک تست",
    role: "VENUE_OWNER",
  },
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
    getOwnerVenue: vi.fn(),
    getOwnerVenueSubscription: vi.fn(),
    listOwnerVenueSpaces: vi.fn(),
    listOwnerVenueBookings: vi.fn(),
    listSpaceTablePins: vi.fn().mockResolvedValue([]),
    listVenueSlots: vi.fn().mockResolvedValue([]),
    listPinBlockedSlots: vi.fn().mockResolvedValue([]),
    listVenueAddons: vi.fn(),
    createVenueAddon: vi.fn(),
    updateVenueAddon: vi.fn(),
    deleteVenueAddon: vi.fn(),
    submitVenueForReview: vi.fn(),
  };
});

const mockedGetOwnerVenue = vi.mocked(getOwnerVenue);
const mockedGetOwnerVenueSubscription = vi.mocked(getOwnerVenueSubscription);
const mockedListOwnerVenueSpaces = vi.mocked(listOwnerVenueSpaces);
const mockedListOwnerVenueBookings = vi.mocked(listOwnerVenueBookings);
const mockedListVenueAddons = vi.mocked(listVenueAddons);
const mockedCreateVenueAddon = vi.mocked(createVenueAddon);
const mockedUpdateVenueAddon = vi.mocked(updateVenueAddon);
const mockedDeleteVenueAddon = vi.mocked(deleteVenueAddon);
const mockedSubmitVenueForReview = vi.mocked(submitVenueForReview);

const VENUE_FIXTURE: VenueOwnerOut = {
  id: 9,
  name: "کافه تست",
  slug: "test-cafe",
  city: "تهران",
  venue_type: "CAFE",
  address: "خیابان ولیعصر",
  description: "",
  operating_hours: [],
  design_addons: [],
  is_approved: true,
  review_status: "APPROVED",
  rejection_reason: "",
  submitted_for_review_at: null,
  subscription_status: "ACTIVE",
  is_publicly_visible: true,
  created_at: "2026-11-01T00:00:00Z",
  updated_at: "2026-11-01T00:00:00Z",
};

const SUB_FIXTURE: VenueSubscriptionOut = {
  is_active: true,
  plan_name: "MONTHLY",
  starts_at: "2026-11-01T00:00:00Z",
  expires_at: "2026-12-01T00:00:00Z",
  jalali_expires_at: "۱۴۰۵/۰۹/۱۰",
  days_remaining: 20,
  has_ever_subscribed: true,
};

async function renderDashboardWithAddons(addons: DesignAddonOut[]) {
  mockedGetOwnerVenue.mockResolvedValueOnce(VENUE_FIXTURE);
  mockedGetOwnerVenueSubscription.mockResolvedValueOnce(SUB_FIXTURE);
  mockedListOwnerVenueSpaces.mockResolvedValueOnce([]);
  mockedListOwnerVenueBookings.mockResolvedValueOnce([]);
  mockedListVenueAddons.mockResolvedValueOnce(addons);

  render(React.createElement(OwnerVenueDashboard, { venueId: 9 }));
  await screen.findByText("مدیریت افزودنی‌های طراحی");
}

describe("OwnerVenueDashboard design add-ons section (T-035 frontend)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("renders the design add-ons list with title, formatted fee, and active status", async () => {
    await renderDashboardWithAddons([
      { id: 1, title: "گل‌آرایی میز", fee: 120_000, is_active: true },
      { id: 2, title: "شمع‌آرایی", fee: 50_000, is_active: false },
    ]);

    expect(screen.getByText("گل‌آرایی میز")).toBeInTheDocument();
    expect(screen.getByText("شمع‌آرایی")).toBeInTheDocument();
    expect(screen.getByText("۱۲۰٬۰۰۰ تومان")).toBeInTheDocument();
    expect(screen.getByText("۵۰٬۰۰۰ تومان")).toBeInTheDocument();
    expect(screen.getByText("فعال")).toBeInTheDocument();
    expect(screen.getByText("غیرفعال")).toBeInTheDocument();
  });

  it("shows empty state and create button when there are no add-ons", async () => {
    await renderDashboardWithAddons([]);

    expect(
      screen.getByText("هنوز افزودنی طراحی برای این مجموعه ثبت نشده است.")
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "افزودن افزودنی جدید" })).toBeInTheDocument();
  });

  it("creates a new add-on via POST and refreshes the list", async () => {
    const user = userEvent.setup();
    await renderDashboardWithAddons([]);

    const created: DesignAddonOut = {
      id: 10,
      title: "بادکنک‌آرایی",
      fee: 200_000,
      is_active: true,
    };
    mockedCreateVenueAddon.mockResolvedValueOnce(created);
    mockedListVenueAddons.mockResolvedValueOnce([created]);

    await user.click(screen.getByRole("button", { name: "افزودن افزودنی جدید" }));
    await user.type(screen.getByLabelText("عنوان افزودنی جدید"), "بادکنک‌آرایی");
    await user.type(screen.getByLabelText("هزینه افزودنی جدید"), "200000");
    await user.click(screen.getByRole("button", { name: "ثبت افزودنی" }));

    await waitFor(() => expect(mockedCreateVenueAddon).toHaveBeenCalledTimes(1));
    expect(mockedCreateVenueAddon).toHaveBeenCalledWith(9, {
      title: "بادکنک‌آرایی",
      fee: 200_000,
      is_active: true,
    });
    expect(await screen.findByText("بادکنک‌آرایی")).toBeInTheDocument();
  });

  it("rejects negative and non-integer fee inputs client-side before sending any request", async () => {
    const user = userEvent.setup();
    await renderDashboardWithAddons([]);

    await user.click(screen.getByRole("button", { name: "افزودن افزودنی جدید" }));
    await user.type(screen.getByLabelText("عنوان افزودنی جدید"), "شمع");
    await user.type(screen.getByLabelText("هزینه افزودنی جدید"), "-500");
    await user.click(screen.getByRole("button", { name: "ثبت افزودنی" }));

    expect(screen.getByRole("alert")).toHaveTextContent("عدد صحیح نامنفی");
    expect(mockedCreateVenueAddon).not.toHaveBeenCalled();

    await user.clear(screen.getByLabelText("هزینه افزودنی جدید"));
    await user.type(screen.getByLabelText("هزینه افزودنی جدید"), "12.5");
    await user.click(screen.getByRole("button", { name: "ثبت افزودنی" }));

    expect(screen.getByRole("alert")).toHaveTextContent("عدد صحیح نامنفی");
    expect(mockedCreateVenueAddon).not.toHaveBeenCalled();
  });

  it("edits an add-on inline with BR-15 note and sends PUT full replace", async () => {
    const user = userEvent.setup();
    await renderDashboardWithAddons([
      { id: 5, title: "گل‌آرایی", fee: 100_000, is_active: true },
    ]);

    const updated: DesignAddonOut = {
      id: 5,
      title: "گل‌آرایی ویژه",
      fee: 180_000,
      is_active: false,
    };
    mockedUpdateVenueAddon.mockResolvedValueOnce(updated);

    await user.click(screen.getByRole("button", { name: "ویرایش" }));
    expect(
      screen.getByText(/تغییر هزینه فقط برای رزروهای آینده اعمال می‌شود/)
    ).toBeInTheDocument();

    const titleInput = screen.getByLabelText("عنوان گل‌آرایی");
    const feeInput = screen.getByLabelText("هزینه گل‌آرایی");
    const activeCheckbox = screen.getByLabelText("وضعیت فعال گل‌آرایی");

    await user.clear(titleInput);
    await user.type(titleInput, "گل‌آرایی ویژه");
    await user.clear(feeInput);
    await user.type(feeInput, "180000");
    await user.click(activeCheckbox);
    await user.click(screen.getByRole("button", { name: "ذخیره" }));

    await waitFor(() => expect(mockedUpdateVenueAddon).toHaveBeenCalledTimes(1));
    expect(mockedUpdateVenueAddon).toHaveBeenCalledWith(9, 5, {
      title: "گل‌آرایی ویژه",
      fee: 180_000,
      is_active: false,
    });
    expect(await screen.findByText("گل‌آرایی ویژه")).toBeInTheDocument();
    expect(screen.getByText("غیرفعال")).toBeInTheDocument();
  });

  it("handles 409 ADDON_IN_USE on delete by showing Persian message, keeping the row, and offering deactivation", async () => {
    const user = userEvent.setup();
    await renderDashboardWithAddons([
      { id: 7, title: "میز تولد", fee: 250_000, is_active: true },
    ]);

    mockedDeleteVenueAddon.mockRejectedValueOnce(
      new ApiError(409, "ADDON_IN_USE", "Add-on is in use", {})
    );
    mockedUpdateVenueAddon.mockResolvedValueOnce({
      id: 7,
      title: "میز تولد",
      fee: 250_000,
      is_active: false,
    });

    await user.click(screen.getByRole("button", { name: "حذف" }));
    await user.click(screen.getByRole("button", { name: "تایید حذف" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).not.toContain("ADDON_IN_USE");
    expect(alert.textContent).toContain("غیرفعال کنید");
    expect(screen.getByText("میز تولد")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "غیرفعال کردن افزودنی" }));
    await waitFor(() => expect(mockedUpdateVenueAddon).toHaveBeenCalledTimes(1));
    expect(mockedUpdateVenueAddon).toHaveBeenCalledWith(9, 7, {
      title: "میز تولد",
      fee: 250_000,
      is_active: false,
    });
    expect(await screen.findByText("غیرفعال")).toBeInTheDocument();
  });

  it("removes the add-on row when delete succeeds with 204", async () => {
    const user = userEvent.setup();
    await renderDashboardWithAddons([
      { id: 8, title: "شمع معطر", fee: 60_000, is_active: true },
    ]);

    mockedDeleteVenueAddon.mockResolvedValueOnce(undefined);

    await user.click(screen.getByRole("button", { name: "حذف" }));
    await user.click(screen.getByRole("button", { name: "تایید حذف" }));

    await waitFor(() => expect(mockedDeleteVenueAddon).toHaveBeenCalledWith(9, 8));
    await waitFor(() => expect(screen.queryByText("شمع معطر")).not.toBeInTheDocument());
    expect(
      screen.getByText("هنوز افزودنی طراحی برای این مجموعه ثبت نشده است.")
    ).toBeInTheDocument();
  });
});

async function renderDashboardWithVenue(
  venueOverrides: Partial<VenueOwnerOut> = {},
  subOverrides: Partial<VenueSubscriptionOut> = {}
) {
  mockedGetOwnerVenue.mockResolvedValueOnce({ ...VENUE_FIXTURE, ...venueOverrides });
  mockedGetOwnerVenueSubscription.mockResolvedValueOnce({ ...SUB_FIXTURE, ...subOverrides });
  mockedListOwnerVenueSpaces.mockResolvedValueOnce([]);
  mockedListOwnerVenueBookings.mockResolvedValueOnce([]);
  mockedListVenueAddons.mockResolvedValueOnce([]);

  render(React.createElement(OwnerVenueDashboard, { venueId: 9 }));
  await screen.findByText("وضعیت بررسی مجموعه");
}

describe("OwnerVenueDashboard review-status panel (T-036 frontend)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("shows each of the four review_status header badges with the decided Persian labels", async () => {
    const cases: Array<[VenueOwnerOut["review_status"], string]> = [
      ["DRAFT", "پیش‌نویس"],
      ["PENDING_REVIEW", "در انتظار بررسی"],
      ["APPROVED", "تایید شده"],
      ["REJECTED", "رد شده"],
    ];

    for (const [status, label] of cases) {
      await renderDashboardWithVenue({
        review_status: status,
        is_approved: status === "APPROVED",
      });
      expect(screen.getByText(label)).toBeInTheDocument();
      cleanup();
      vi.clearAllMocks();
    }
  });

  it("shows submit button for DRAFT even when subscription is inactive and no spaces/tables exist", async () => {
    await renderDashboardWithVenue(
      { review_status: "DRAFT", is_approved: false, subscription_status: "INACTIVE" },
      { is_active: false, has_ever_subscribed: false }
    );

    const submitBtn = screen.getByRole("button", { name: "ارسال برای بررسی" });
    expect(submitBtn).toBeEnabled();
  });

  it("shows REJECTED rejection_reason verbatim, submitted_for_review_at, and resubmit button", async () => {
    await renderDashboardWithVenue({
      review_status: "REJECTED",
      is_approved: false,
      rejection_reason: "تصویر ۳۶۰ سالن اصلی بارگذاری نشده است.",
      submitted_for_review_at: "2026-11-28T08:00:00Z",
    });

    expect(screen.getByText("تصویر ۳۶۰ سالن اصلی بارگذاری نشده است.")).toBeInTheDocument();
    expect(screen.getByText(/زمان آخرین ارسال:/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ارسال دوباره برای بررسی" })).toBeEnabled();
  });

  it("shows no submit button for PENDING_REVIEW or APPROVED", async () => {
    await renderDashboardWithVenue({
      review_status: "PENDING_REVIEW",
      is_approved: false,
      submitted_for_review_at: "2026-11-28T08:00:00Z",
    });
    expect(screen.getByText(/در انتظار بررسی مدیر پلتفرم است/)).toBeInTheDocument();
    expect(screen.getByText(/زمان ارسال:/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /ارسال/ })).not.toBeInTheDocument();

    cleanup();
    vi.clearAllMocks();

    await renderDashboardWithVenue({
      review_status: "APPROVED",
      is_approved: true,
    });
    expect(screen.queryByRole("button", { name: /ارسال/ })).not.toBeInTheDocument();
  });

  it("updates panel directly from returned VenueOwnerOut on submit success without extra getOwnerVenue call", async () => {
    const user = userEvent.setup();
    await renderDashboardWithVenue({
      review_status: "DRAFT",
      is_approved: false,
    });

    mockedSubmitVenueForReview.mockResolvedValueOnce({
      ...VENUE_FIXTURE,
      review_status: "PENDING_REVIEW",
      is_approved: false,
      rejection_reason: "",
      submitted_for_review_at: "2026-11-28T08:30:00Z",
    });

    await user.click(screen.getByRole("button", { name: "ارسال برای بررسی" }));

    await waitFor(() => expect(mockedSubmitVenueForReview).toHaveBeenCalledWith(9));
    expect(await screen.findByText("در انتظار بررسی")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /ارسال/ })).not.toBeInTheDocument();
    expect(mockedGetOwnerVenue).toHaveBeenCalledTimes(1);
  });

  it("shows Persian message without raw error_code and refreshes venue on 409 VENUE_NOT_SUBMITTABLE", async () => {
    const user = userEvent.setup();
    await renderDashboardWithVenue({
      review_status: "DRAFT",
      is_approved: false,
    });

    mockedSubmitVenueForReview.mockRejectedValueOnce(
      new ApiError(409, "VENUE_NOT_SUBMITTABLE", "Venue cannot be submitted.", {})
    );
    mockedGetOwnerVenue.mockResolvedValueOnce({
      ...VENUE_FIXTURE,
      review_status: "APPROVED",
      is_approved: true,
    });

    await user.click(screen.getByRole("button", { name: "ارسال برای بررسی" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).not.toContain("VENUE_NOT_SUBMITTABLE");
    expect(alert.textContent).toContain("امکان ارسال برای بررسی را ندارد");
    await waitFor(() => expect(mockedGetOwnerVenue).toHaveBeenCalledTimes(2));
    expect(await screen.findByText("تایید شده")).toBeInTheDocument();
  });
});
