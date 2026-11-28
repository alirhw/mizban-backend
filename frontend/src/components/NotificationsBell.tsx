"use client";

import React, { useEffect, useRef, useState } from "react";

import {
  ApiError,
  getUnreadCount,
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type NotificationOut,
} from "@/lib/api";
import { formatJalaliDate } from "@/lib/jalali";

const PAGE_SIZE = 20;

function mapNotificationErrorToPersian(err: unknown): string {
  if (err instanceof ApiError && (err.status === 403 || err.errorCode === "FORBIDDEN")) {
    return "شما دسترسی لازم برای مشاهده یا تغییر وضعیت اعلان‌ها را ندارید.";
  }
  return "دریافت یا به‌روزرسانی اعلان‌ها با خطا مواجه شد.";
}

export function NotificationsBell() {
  const [open, setOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [notifications, setNotifications] = useState<NotificationOut[]>([]);
  const [loadingList, setLoadingList] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [markingAll, setMarkingAll] = useState(false);
  const listRequestGenRef = useRef(0);

  useEffect(() => {
    let active = true;
    getUnreadCount()
      .then((res) => {
        if (active) setUnreadCount(res.unread_count);
      })
      .catch(() => {
        // Keep badge at 0 if initial count fails.
      });
    return () => {
      active = false;
    };
  }, []);

  async function loadFirstPage() {
    const gen = ++listRequestGenRef.current;
    setLoadingList(true);
    setLoadingMore(false);
    setErrorMessage(null);
    try {
      const items = await listNotifications({ limit: PAGE_SIZE, offset: 0 });
      if (listRequestGenRef.current !== gen) return;
      setNotifications(items);
      setHasMore(items.length === PAGE_SIZE);
    } catch (err) {
      if (listRequestGenRef.current !== gen) return;
      setErrorMessage(mapNotificationErrorToPersian(err));
    } finally {
      if (listRequestGenRef.current === gen) {
        setLoadingList(false);
      }
    }
  }

  async function handleToggleOpen() {
    const nextOpen = !open;
    setOpen(nextOpen);
    if (nextOpen) {
      await loadFirstPage();
    }
  }

  async function handleLoadMore() {
    const gen = listRequestGenRef.current;
    setLoadingMore(true);
    setErrorMessage(null);
    try {
      const items = await listNotifications({
        limit: PAGE_SIZE,
        offset: notifications.length,
      });
      if (listRequestGenRef.current !== gen) return;
      setNotifications((prev) => [...prev, ...items]);
      setHasMore(items.length === PAGE_SIZE);
    } catch (err) {
      if (listRequestGenRef.current !== gen) return;
      setErrorMessage(mapNotificationErrorToPersian(err));
    } finally {
      if (listRequestGenRef.current === gen) {
        setLoadingMore(false);
      }
    }
  }

  async function handleMarkRead(notification: NotificationOut) {
    if (notification.is_read) return;
    setErrorMessage(null);
    try {
      const updated = await markNotificationRead(notification.id);
      setNotifications((prev) =>
        prev.map((item) => (item.id === notification.id ? updated : item))
      );
      setUnreadCount((prev) => Math.max(0, prev - 1));
    } catch (err) {
      setErrorMessage(mapNotificationErrorToPersian(err));
    }
  }

  async function handleMarkAllRead() {
    setMarkingAll(true);
    setErrorMessage(null);
    try {
      await markAllNotificationsRead();
      setNotifications((prev) => prev.map((item) => ({ ...item, is_read: true })));
      setUnreadCount(0);
    } catch (err) {
      setErrorMessage(mapNotificationErrorToPersian(err));
    } finally {
      setMarkingAll(false);
    }
  }

  return (
    <div className="relative">
      <button
        type="button"
        aria-label="اعلان‌ها"
        aria-expanded={open}
        onClick={() => void handleToggleOpen()}
        className="relative inline-flex items-center gap-1.5 rounded-md border border-stone-300 px-3 py-1.5 text-xs font-medium text-stone-800 hover:bg-stone-100"
      >
        <span>اعلان‌ها</span>
        {unreadCount > 0 ? (
          <span
            data-testid="notifications-unread-badge"
            className="inline-flex min-w-[18px] items-center justify-center rounded-full bg-red-600 px-1.5 py-0.5 text-[11px] font-bold text-white"
          >
            {unreadCount}
          </span>
        ) : null}
      </button>

      {open ? (
        <div
          role="region"
          aria-label="فهرست اعلان‌ها"
          className="absolute left-0 z-30 mt-2 w-80 sm:w-96 rounded-xl border border-stone-200 bg-white p-4 shadow-lg space-y-3"
        >
          <div className="flex items-center justify-between gap-2 border-b border-stone-200 pb-2">
            <h2 className="text-sm font-bold text-stone-900">اعلان‌ها</h2>
            {notifications.some((n) => !n.is_read) || unreadCount > 0 ? (
              <button
                type="button"
                disabled={markingAll}
                onClick={() => void handleMarkAllRead()}
                className="text-xs font-medium text-stone-700 underline hover:text-stone-900 disabled:opacity-50"
              >
                {markingAll ? "در حال ثبت..." : "علامت‌گذاری همه به‌عنوان خوانده‌شده"}
              </button>
            ) : null}
          </div>

          {errorMessage ? (
            <div
              role="alert"
              className="rounded-lg border border-red-200 bg-red-50 p-2.5 text-xs text-red-800"
            >
              {errorMessage}
            </div>
          ) : null}

          {loadingList ? (
            <p className="text-xs text-stone-500">در حال دریافت اعلان‌ها...</p>
          ) : notifications.length === 0 ? (
            <p className="text-xs text-stone-500">اعلانی وجود ندارد.</p>
          ) : (
            <div className="max-h-80 space-y-2 overflow-y-auto">
              {notifications.map((n) => (
                <button
                  key={n.id}
                  type="button"
                  onClick={() => void handleMarkRead(n)}
                  data-unread={n.is_read ? "false" : "true"}
                  className={`w-full rounded-lg border p-3 text-right text-xs space-y-1 transition ${
                    n.is_read
                      ? "border-stone-200 bg-white text-stone-600"
                      : "border-amber-200 bg-amber-50 text-stone-900"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className={n.is_read ? "font-medium" : "font-bold"}>{n.title}</span>
                    {!n.is_read ? (
                      <span className="rounded-full bg-amber-200 px-1.5 py-0.5 text-[10px] font-semibold text-amber-950">
                        خوانده‌نشده
                      </span>
                    ) : null}
                  </div>
                  <p>{n.body}</p>
                  <div className="text-[11px] text-stone-500">
                    {formatJalaliDate(n.created_at, { includeTime: true })}
                  </div>
                </button>
              ))}

              {hasMore ? (
                <button
                  type="button"
                  disabled={loadingMore}
                  onClick={() => void handleLoadMore()}
                  className="w-full rounded-lg border border-stone-300 py-1.5 text-xs font-medium text-stone-700 hover:bg-stone-100 disabled:opacity-50"
                >
                  {loadingMore ? "در حال بارگذاری..." : "نمایش اعلان‌های بیشتر"}
                </button>
              ) : null}
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
