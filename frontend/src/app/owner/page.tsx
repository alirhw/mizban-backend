"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useEffect, useState } from "react";

import { OwnerForbidden } from "@/components/OwnerForbidden";
import {
  ApiError,
  getOwnerVenueSubscription,
  listOwnerVenues,
  type VenueOwnerOut,
  type VenueSubscriptionOut,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { getSubscriptionBadge, isForbiddenError, OWNER_EMPTY_VENUES_TEXT } from "@/lib/owner";

interface VenueWithSubscription {
  venue: VenueOwnerOut;
  subscription: VenueSubscriptionOut | null;
}

export default function OwnerVenuesPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();

  const [items, setItems] = useState<VenueWithSubscription[]>([]);
  const [loadedUserId, setLoadedUserId] = useState<number | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isOwnerRole = user?.role === "VENUE_OWNER" || user?.role === "ADMIN";
  const loading = Boolean(user && isOwnerRole && loadedUserId !== user.id && !error && !forbidden);

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      router.replace(`/login?next=${encodeURIComponent("/owner")}`);
      return;
    }
    if (!isOwnerRole) {
      return;
    }

    let active = true;
    const targetUserId = user.id;

    listOwnerVenues()
      .then(async (venues) => {
        const subs = await Promise.all(
          venues.map((v) => getOwnerVenueSubscription(v.id).catch(() => null))
        );
        if (!active) return;
        setItems(venues.map((venue, index) => ({ venue, subscription: subs[index] ?? null })));
        setError(null);
        setForbidden(false);
        setLoadedUserId(targetUserId);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof ApiError && err.status === 401) {
          router.replace(`/login?next=${encodeURIComponent("/owner")}`);
          return;
        }
        if (isForbiddenError(err)) {
          setForbidden(true);
          return;
        }
        setError("دریافت فهرست مجموعه‌های شما با خطا مواجه شد.");
      });

    return () => {
      active = false;
    };
  }, [authLoading, user, isOwnerRole, router]);

  if (authLoading || (!user && !authLoading)) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-48 animate-pulse rounded bg-stone-200" />
        <div className="h-32 animate-pulse rounded-xl bg-stone-200" />
      </div>
    );
  }

  if (!isOwnerRole || forbidden) {
    return <OwnerForbidden />;
  }

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-stone-900">پنل مالک مجموعه</h1>
          <p className="text-sm text-stone-600">
            مدیریت فضاها، تعرفه میزها، مسدودسازی اسلات‌ها و مشاهده رزروهای مجموعه‌های شما
          </p>
        </div>
        <Link
          href="/"
          className="text-sm font-medium text-stone-700 underline hover:text-stone-900"
        >
          مشاهده صفحه عمومی
        </Link>
      </div>

      {loading ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="h-40 animate-pulse rounded-xl bg-stone-200" />
          <div className="h-40 animate-pulse rounded-xl bg-stone-200" />
        </div>
      ) : error ? (
        <div
          role="alert"
          className="rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-900"
        >
          {error}
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-xl border border-stone-200 bg-white p-8 text-center text-sm text-stone-600">
          {OWNER_EMPTY_VENUES_TEXT}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {items.map(({ venue, subscription }) => {
            const subBadge = subscription
              ? getSubscriptionBadge(subscription)
              : getSubscriptionBadge({
                  is_active: venue.subscription_status === "ACTIVE",
                  days_remaining: 0,
                  has_ever_subscribed: venue.subscription_status === "ACTIVE",
                });

            const toneClasses =
              subBadge.tone === "emerald"
                ? "bg-emerald-100 text-emerald-900"
                : subBadge.tone === "amber"
                  ? "bg-amber-100 text-amber-900"
                  : "bg-red-100 text-red-900";

            return (
              <div
                key={venue.id}
                className="flex flex-col justify-between gap-4 rounded-xl border border-stone-200 bg-white p-5 shadow-sm"
              >
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h2 className="text-lg font-bold text-stone-900">{venue.name}</h2>
                    <span
                      className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
                        venue.is_approved
                          ? "bg-emerald-50 text-emerald-800"
                          : "bg-stone-100 text-stone-700"
                      }`}
                    >
                      {venue.is_approved ? "تایید شده" : "در انتظار تایید"}
                    </span>
                  </div>
                  <p className="text-xs text-stone-500" dir="ltr">
                    /{venue.slug}
                  </p>

                  <div className="rounded-lg border border-stone-100 bg-stone-50 p-3 text-xs space-y-1">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-stone-600">وضعیت اشتراک:</span>
                      <span className={`rounded-full px-2 py-0.5 font-semibold ${toneClasses}`}>
                        {venue.subscription_status} ({subBadge.label})
                      </span>
                    </div>
                    {subscription?.plan_name ? (
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-stone-600">طرح:</span>
                        <span className="font-medium text-stone-900">{subscription.plan_name}</span>
                      </div>
                    ) : null}
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-stone-600">اعتبار:</span>
                      <span className="text-stone-800">{subBadge.detail}</span>
                    </div>
                    {subscription?.jalali_expires_at ? (
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-stone-600">انقضا:</span>
                        <span className="text-stone-800">{subscription.jalali_expires_at}</span>
                      </div>
                    ) : null}
                  </div>
                </div>

                <Link
                  href={`/owner/venues/${venue.id}`}
                  className="inline-flex min-h-[44px] items-center justify-center rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white hover:bg-stone-800"
                >
                  مدیریت مجموعه
                </Link>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
