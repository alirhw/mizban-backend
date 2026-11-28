// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";

import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Header } from "@/components/Header";
import { NotificationsBell } from "@/components/NotificationsBell";
import {
  ApiError,
  getUnreadCount,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type NotificationOut,
} from "@/lib/api";

let mockAuthState: {
  user: { id: number; phone: string; role: string } | null;
  loading: boolean;
  logout: () => Promise<void>;
} = {
  user: { id: 1, phone: "09120000001", role: "VENUE_OWNER" },
  loading: false,
  logout: vi.fn(),
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

vi.mock("@/lib/auth", () => ({
  useAuth: () => mockAuthState,
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    getUnreadCount: vi.fn(),
    listNotifications: vi.fn(),
    markNotificationRead: vi.fn(),
    markAllNotificationsRead: vi.fn(),
  };
});

const mockedGetUnreadCount = vi.mocked(getUnreadCount);
const mockedListNotifications = vi.mocked(listNotifications);
const mockedMarkNotificationRead = vi.mocked(markNotificationRead);
const mockedMarkAllNotificationsRead = vi.mocked(markAllNotificationsRead);

function makeNotification(overrides: Partial<NotificationOut>): NotificationOut {
  return {
    id: 1,
    type: "BOOKING_CONFIRMED",
    booking_id: 42,
    venue_id: 5,
    title: "رزرو جدید تایید شد",
    body: "رزرو میز شماره ۳ در کافه تست تایید شد.",
    is_read: false,
    created_at: "2026-11-28T08:00:00Z",
    ...overrides,
  };
}

describe("T-039 frontend: Owner notification bell & dropdown", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuthState = {
      user: { id: 1, phone: "09120000001", role: "VENUE_OWNER" },
      loading: false,
      logout: vi.fn(),
    };
  });

  afterEach(() => {
    cleanup();
  });

  it("Header shows notifications bell only for VENUE_OWNER and hides it for CUSTOMER, ADMIN, and logged-out users", async () => {
    mockedGetUnreadCount.mockResolvedValue({ unread_count: 2 });

    const { rerender } = render(React.createElement(Header));
    expect(await screen.findByRole("button", { name: "اعلان‌ها" })).toBeInTheDocument();

    for (const role of ["CUSTOMER", "ADMIN"]) {
      mockAuthState = { user: { id: 2, phone: "09121111111", role }, loading: false, logout: vi.fn() };
      rerender(React.createElement(Header));
      expect(screen.queryByRole("button", { name: "اعلان‌ها" })).not.toBeInTheDocument();
    }

    mockAuthState = { user: null, loading: false, logout: vi.fn() };
    rerender(React.createElement(Header));
    expect(screen.queryByRole("button", { name: "اعلان‌ها" })).not.toBeInTheDocument();
  });

  it("shows unread badge when count > 0 and hides badge when count is 0", async () => {
    mockedGetUnreadCount.mockResolvedValueOnce({ unread_count: 4 });
    render(React.createElement(NotificationsBell));
    expect(await screen.findByTestId("notifications-unread-badge")).toHaveTextContent("4");

    cleanup();
    vi.clearAllMocks();

    mockedGetUnreadCount.mockResolvedValueOnce({ unread_count: 0 });
    render(React.createElement(NotificationsBell));
    await waitFor(() => expect(mockedGetUnreadCount).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("notifications-unread-badge")).not.toBeInTheDocument();
  });

  it("lists server-rendered Persian notifications with unread/read distinction and marks single row read in place", async () => {
    const user = userEvent.setup();
    mockedGetUnreadCount.mockResolvedValueOnce({ unread_count: 1 });
    mockedListNotifications.mockResolvedValueOnce([
      makeNotification({
        id: 10,
        title: "رزرو جدید تایید شد",
        body: "متن اعلان خوانده‌نشده",
        is_read: false,
      }),
      makeNotification({
        id: 11,
        title: "مجموعه تایید شد",
        body: "متن اعلان خوانده‌شده",
        is_read: true,
      }),
    ]);
    mockedMarkNotificationRead.mockResolvedValueOnce(
      makeNotification({
        id: 10,
        title: "رزرو جدید تایید شد",
        body: "متن اعلان خوانده‌نشده",
        is_read: true,
      })
    );

    render(React.createElement(NotificationsBell));
    await screen.findByTestId("notifications-unread-badge");

    await user.click(screen.getByRole("button", { name: /اعلان‌ها/ }));

    expect(await screen.findByText("متن اعلان خوانده‌نشده")).toBeInTheDocument();
    expect(screen.getByText("متن اعلان خوانده‌شده")).toBeInTheDocument();

    const unreadBtn = screen.getByText("متن اعلان خوانده‌نشده").closest("button")!;
    const readBtn = screen.getByText("متن اعلان خوانده‌شده").closest("button")!;
    expect(unreadBtn).toHaveAttribute("data-unread", "true");
    expect(readBtn).toHaveAttribute("data-unread", "false");

    await user.click(unreadBtn);
    await waitFor(() => expect(mockedMarkNotificationRead).toHaveBeenCalledWith(10));
    expect(unreadBtn).toHaveAttribute("data-unread", "false");
    expect(screen.queryByTestId("notifications-unread-badge")).not.toBeInTheDocument();
    expect(mockedListNotifications).toHaveBeenCalledTimes(1);
  });

  it("marks all notifications read and clears badge", async () => {
    const user = userEvent.setup();
    mockedGetUnreadCount.mockResolvedValueOnce({ unread_count: 2 });
    mockedListNotifications.mockResolvedValueOnce([
      makeNotification({ id: 21, body: "اعلان اول", is_read: false }),
      makeNotification({ id: 22, body: "اعلان دوم", is_read: false }),
    ]);
    mockedMarkAllNotificationsRead.mockResolvedValueOnce({ marked: 2 });

    render(React.createElement(NotificationsBell));
    await screen.findByTestId("notifications-unread-badge");

    await user.click(screen.getByRole("button", { name: /اعلان‌ها/ }));
    await screen.findByText("اعلان اول");

    await user.click(
      screen.getByRole("button", { name: "علامت‌گذاری همه به‌عنوان خوانده‌شده" })
    );

    await waitFor(() => expect(mockedMarkAllNotificationsRead).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId("notifications-unread-badge")).not.toBeInTheDocument();
    expect(screen.getByText("اعلان اول").closest("button")).toHaveAttribute("data-unread", "false");
    expect(screen.getByText("اعلان دوم").closest("button")).toHaveAttribute("data-unread", "false");
  });

  it("renders empty state when there are no notifications and maps 403 to Persian without raw error_code", async () => {
    const user = userEvent.setup();
    mockedGetUnreadCount.mockResolvedValueOnce({ unread_count: 0 });
    mockedListNotifications.mockResolvedValueOnce([]);

    render(React.createElement(NotificationsBell));
    await user.click(screen.getByRole("button", { name: /اعلان‌ها/ }));
    expect(await screen.findByText("اعلانی وجود ندارد.")).toBeInTheDocument();

    cleanup();
    vi.clearAllMocks();

    mockedGetUnreadCount.mockResolvedValueOnce({ unread_count: 0 });
    mockedListNotifications.mockRejectedValueOnce(
      new ApiError(403, "FORBIDDEN", "Forbidden", {})
    );

    render(React.createElement(NotificationsBell));
    await user.click(screen.getByRole("button", { name: /اعلان‌ها/ }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).not.toContain("FORBIDDEN");
    expect(alert.textContent).toContain("دسترسی لازم");
  });
});
