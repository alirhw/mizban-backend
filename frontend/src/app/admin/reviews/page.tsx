"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  hideReview,
  listAdminReviews,
  listPublicVenues,
  showReview,
  type ReviewAdminOut,
  type VenuePublicItemOut,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatJalaliDate } from "@/lib/jalali";

const PAGE_SIZE = 20;

function mapAdminReviewErrorToPersian(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 403 || err.errorCode === "FORBIDDEN") {
      return "فقط مدیران پلتفرم به مدیریت نظرها دسترسی دارند.";
    }
    if (err.status === 404 || err.errorCode === "NOT_FOUND") {
      return "نظر مورد نظر یافت نشد.";
    }
  }
  return "خطایی در دریافت یا به‌روزرسانی نظرها رخ داد.";
}

export default function AdminReviewsPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();

  const [venues, setVenues] = useState<VenuePublicItemOut[]>([]);
  const [venueIdFilter, setVenueIdFilter] = useState<string>("");
  const [visibilityFilter, setVisibilityFilter] = useState<"all" | "visible" | "hidden">("all");
  const [offset, setOffset] = useState(0);

  const [reviews, setReviews] = useState<ReviewAdminOut[]>([]);
  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);
  const [reachedEndOfList, setReachedEndOfList] = useState(false);
  const [loadingReviews, setLoadingReviews] = useState(true);
  const [forbidden, setForbidden] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [mutatingId, setMutatingId] = useState<number | null>(null);

  const venueNameById = useMemo(() => {
    const map: Record<number, string> = {};
    for (const v of venues) {
      map[v.id] = v.name;
    }
    return map;
  }, [venues]);

  useEffect(() => {
    let active = true;
    listPublicVenues()
      .then((list) => {
        if (active) setVenues(list);
      })
      .catch(() => {
        // Venue dropdown falls back to numeric venue_id labels if public list fails.
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      router.replace(`/login?next=${encodeURIComponent("/admin/reviews")}`);
      return;
    }

    let active = true;
    setLoadingReviews(true);
    setErrorMessage(null);
    setReachedEndOfList(false);

    const parsedVenueId = venueIdFilter ? Number(venueIdFilter) : undefined;
    const isVisibleParam =
      visibilityFilter === "all" ? undefined : visibilityFilter === "visible";

    listAdminReviews({
      venue_id: parsedVenueId,
      is_visible: isVisibleParam,
      limit: PAGE_SIZE,
      offset,
    })
      .then((data) => {
        if (!active) return;
        if (offset > 0 && data.length === 0) {
          setReachedEndOfList(true);
        } else {
          setReviews(data);
          setReachedEndOfList(false);
        }
        setHasLoadedOnce(true);
        setForbidden(false);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof ApiError && err.status === 401) {
          router.replace(`/login?next=${encodeURIComponent("/admin/reviews")}`);
          return;
        }
        if (err instanceof ApiError && (err.status === 403 || err.errorCode === "FORBIDDEN")) {
          setForbidden(true);
          setErrorMessage(mapAdminReviewErrorToPersian(err));
          return;
        }
        setErrorMessage(mapAdminReviewErrorToPersian(err));
      })
      .finally(() => {
        if (active) setLoadingReviews(false);
      });

    return () => {
      active = false;
    };
  }, [authLoading, user, venueIdFilter, visibilityFilter, offset, router]);

  async function handleToggleVisibility(review: ReviewAdminOut) {
    setMutatingId(review.id);
    setErrorMessage(null);
    try {
      const updated = review.is_visible
        ? await hideReview(review.id)
        : await showReview(review.id);
      setReviews((prev) => prev.map((r) => (r.id === review.id ? updated : r)));
    } catch (err) {
      if (err instanceof ApiError && (err.status === 403 || err.errorCode === "FORBIDDEN")) {
        setForbidden(true);
      }
      setErrorMessage(mapAdminReviewErrorToPersian(err));
    } finally {
      setMutatingId(null);
    }
  }

  if (authLoading) {
    return (
      <div className="rounded-xl border border-stone-200 bg-white p-6 text-sm text-stone-600">
        در حال بررسی دسترسی...
      </div>
    );
  }

  if (forbidden) {
    return (
      <div
        role="alert"
        className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-900 space-y-3"
      >
        <p className="font-semibold">
          {errorMessage ?? "فقط مدیران پلتفرم به مدیریت نظرها دسترسی دارند."}
        </p>
        <Link href="/" className="inline-block text-xs underline text-stone-800">
          بازگشت به صفحه اصلی
        </Link>
      </div>
    );
  }

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-stone-900">مدیریت نظرها</h1>
          <p className="text-sm text-stone-600">
            بررسی نظرهای ثبت‌شده مشتریان و پنهان یا نمایش دادن آن‌ها در صفحات عمومی
          </p>
        </div>
        <Link href="/" className="text-sm font-medium text-stone-700 underline hover:text-stone-900">
          بازگشت به صفحه اصلی
        </Link>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-end gap-4 rounded-xl border border-stone-200 bg-white p-4">
        <div>
          <label
            htmlFor="admin-reviews-venue-filter"
            className="mb-1 block text-xs font-medium text-stone-700"
          >
            مجموعه
          </label>
          <select
            id="admin-reviews-venue-filter"
            aria-label="فیلتر مجموعه"
            value={venueIdFilter}
            onChange={(e) => {
              setVenueIdFilter(e.target.value);
              setOffset(0);
            }}
            className="rounded-lg border border-stone-300 bg-white px-3 py-1.5 text-sm"
          >
            <option value="">همه مجموعه‌ها</option>
            {venues.map((v) => (
              <option key={v.id} value={String(v.id)}>
                {v.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label
            htmlFor="admin-reviews-visibility-filter"
            className="mb-1 block text-xs font-medium text-stone-700"
          >
            وضعیت نمایش
          </label>
          <select
            id="admin-reviews-visibility-filter"
            aria-label="فیلتر وضعیت نمایش"
            value={visibilityFilter}
            onChange={(e) => {
              setVisibilityFilter(e.target.value as "all" | "visible" | "hidden");
              setOffset(0);
            }}
            className="rounded-lg border border-stone-300 bg-white px-3 py-1.5 text-sm"
          >
            <option value="all">همه</option>
            <option value="visible">قابل نمایش</option>
            <option value="hidden">پنهان</option>
          </select>
        </div>
      </div>

      {errorMessage ? (
        <div
          role="alert"
          className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-900"
        >
          {errorMessage}
        </div>
      ) : null}

      {loadingReviews && !hasLoadedOnce ? (
        <div className="rounded-xl border border-stone-200 bg-white p-6 text-sm text-stone-600">
          در حال دریافت نظرها...
        </div>
      ) : errorMessage && reviews.length === 0 ? null : reviews.length === 0 ? (
        offset > 0 ? (
          <div className="rounded-xl border border-stone-200 bg-white p-6 text-sm text-stone-600 flex flex-wrap items-center justify-between gap-3">
            <span>به انتهای فهرست رسیدید</span>
            <button
              type="button"
              onClick={() => setOffset((prev) => Math.max(0, prev - PAGE_SIZE))}
              className="rounded-lg border border-stone-300 px-3.5 py-1.5 text-xs font-medium text-stone-700 hover:bg-stone-100"
            >
              بازگشت به صفحه قبل
            </button>
          </div>
        ) : (
          <div className="rounded-xl border border-stone-200 bg-white p-6 text-sm text-stone-500">
            نظری با این فیلترها یافت نشد.
          </div>
        )
      ) : (
        <div className="space-y-3">
          {loadingReviews ? (
            <div className="rounded-lg border border-stone-200 bg-stone-50 px-3 py-2 text-xs text-stone-600">
              در حال به‌روزرسانی نظرها...
            </div>
          ) : null}
          {reachedEndOfList ? (
            <div className="rounded-xl border border-stone-200 bg-amber-50 p-4 text-sm text-amber-900 flex flex-wrap items-center justify-between gap-3">
              <span>به انتهای فهرست رسیدید</span>
              <button
                type="button"
                onClick={() => setOffset((prev) => Math.max(0, prev - PAGE_SIZE))}
                className="rounded-lg border border-amber-300 bg-white px-3.5 py-1.5 text-xs font-medium text-amber-900 hover:bg-amber-100"
              >
                بازگشت به صفحه قبل
              </button>
            </div>
          ) : null}
          {reviews.map((review) => (
            <div
              key={review.id}
              className="rounded-xl border border-stone-200 bg-white p-4 space-y-2 text-sm"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-bold text-stone-900">{review.reviewer_name}</span>
                    <span className="text-xs font-bold text-amber-600">★ {review.rating} از ۵</span>
                    <span className="text-xs text-stone-600">
                      {venueNameById[review.venue_id] ?? `مجموعه #${review.venue_id}`} — میز{" "}
                      {review.table_number}
                    </span>
                    <span
                      className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
                        review.is_visible
                          ? "bg-emerald-100 text-emerald-900"
                          : "bg-stone-200 text-stone-700"
                      }`}
                    >
                      {review.is_visible ? "قابل نمایش" : "پنهان"}
                    </span>
                  </div>
                  <p className="text-xs text-stone-500">
                    ثبت‌شده در {formatJalaliDate(review.created_at)} • رزرو #{review.booking_id}
                  </p>
                </div>

                <button
                  type="button"
                  disabled={mutatingId === review.id}
                  onClick={() => void handleToggleVisibility(review)}
                  className={`min-h-[38px] rounded-lg px-3.5 py-1.5 text-xs font-medium disabled:opacity-50 ${
                    review.is_visible
                      ? "border border-amber-300 bg-amber-50 text-amber-900 hover:bg-amber-100"
                      : "bg-stone-900 text-white hover:bg-stone-800"
                  }`}
                >
                  {mutatingId === review.id
                    ? "در حال اعمال..."
                    : review.is_visible
                      ? "پنهان کردن"
                      : "نمایش دادن"}
                </button>
              </div>
              <p className="text-stone-800">{review.text}</p>
            </div>
          ))}

          <div className="flex items-center justify-between pt-2">
            <button
              type="button"
              disabled={offset === 0}
              onClick={() => setOffset((prev) => Math.max(0, prev - PAGE_SIZE))}
              className="rounded-lg border border-stone-300 px-3.5 py-1.5 text-xs font-medium text-stone-700 disabled:opacity-50"
            >
              صفحه قبل
            </button>
            <button
              type="button"
              disabled={reviews.length < PAGE_SIZE}
              onClick={() => setOffset((prev) => prev + PAGE_SIZE)}
              className="rounded-lg border border-stone-300 px-3.5 py-1.5 text-xs font-medium text-stone-700 disabled:opacity-50"
            >
              صفحه بعد
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
