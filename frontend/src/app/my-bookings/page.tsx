"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useEffect, useReducer, useState } from "react";

import {
  ApiError,
  cancelBooking,
  createReview,
  getBookingReceipt,
  getMyWallet,
  listMyBookings,
  listMyReviews,
  type CustomerBookingOut,
  type ReviewMineOut,
  type SplitReceiptOut,
  type WalletMeOut,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatJalaliDate } from "@/lib/jalali";
import {
  cancelReducer,
  getCancelConfirmationSummary,
  getCustomerBookingStatusLabel,
  getWalletDirectionLabel,
  INITIAL_CANCEL_STATE,
  mapMyBookingsErrorToPersian,
  WALLET_NON_WITHDRAWABLE_NOTE,
} from "@/lib/my-bookings";
import { formatToman } from "@/lib/panorama";

export default function MyBookingsPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();

  const [bookings, setBookings] = useState<CustomerBookingOut[]>([]);
  const [wallet, setWallet] = useState<WalletMeOut | null>(null);
  const [loadedUserId, setLoadedUserId] = useState<number | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [selectedBookingId, setSelectedBookingId] = useState<number | null>(null);
  const [receipt, setReceipt] = useState<SplitReceiptOut | null>(null);
  const [loadingReceipt, setLoadingReceipt] = useState(false);
  const [receiptError, setReceiptError] = useState<string | null>(null);

  const [cancelState, dispatchCancel] = useReducer(cancelReducer, INITIAL_CANCEL_STATE);

  const [reviewsByBookingId, setReviewsByBookingId] = useState<Record<number, ReviewMineOut>>({});
  const [reviewFormBookingId, setReviewFormBookingId] = useState<number | null>(null);
  const [reviewRating, setReviewRating] = useState<number>(0);
  const [reviewText, setReviewText] = useState<string>("");
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [submittingReview, setSubmittingReview] = useState(false);

  const isCustomer = user?.role === "CUSTOMER";
  const loading = Boolean(user && isCustomer && loadedUserId !== user.id && !loadError);

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      router.replace(`/login?next=${encodeURIComponent("/my-bookings")}`);
      return;
    }
    if (!isCustomer) return;

    let active = true;
    const targetUserId = user.id;

    Promise.all([
      listMyBookings(),
      getMyWallet(),
      listMyReviews().catch(() => [] as ReviewMineOut[]),
    ])
      .then(([bookingList, walletData, myReviews]) => {
        if (!active) return;
        const reviewMap: Record<number, ReviewMineOut> = {};
        for (const r of myReviews) {
          reviewMap[r.booking_id] = r;
        }
        setBookings(bookingList);
        setWallet(walletData);
        setReviewsByBookingId(reviewMap);
        setLoadError(null);
        setLoadedUserId(targetUserId);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof ApiError && err.status === 401) {
          router.replace(`/login?next=${encodeURIComponent("/my-bookings")}`);
          return;
        }
        setLoadError(mapMyBookingsErrorToPersian(err));
      });

    return () => {
      active = false;
    };
  }, [authLoading, user, isCustomer, router]);

  async function handleOpenReceipt(bookingId: number) {
    setSelectedBookingId(bookingId);
    setReceipt(null);
    setReceiptError(null);
    setLoadingReceipt(true);
    try {
      const data = await getBookingReceipt(bookingId);
      setReceipt(data);
    } catch (err) {
      setReceiptError(mapMyBookingsErrorToPersian(err));
    } finally {
      setLoadingReceipt(false);
    }
  }

  function openReviewForm(bookingId: number) {
    setReviewFormBookingId(bookingId);
    setReviewRating(0);
    setReviewText("");
    setReviewError(null);
  }

  function mapReviewSubmitError(err: unknown): string {
    if (err instanceof ApiError) {
      if (err.errorCode === "REVIEW_NOT_ALLOWED") {
        return "شما مجاز به ثبت نظر برای این رزرو نیستید.";
      }
      if (err.errorCode === "REVIEW_NOT_ELIGIBLE") {
        return "امکان ثبت نظر فقط پس از تکمیل و پایان زمان رزرو وجود دارد.";
      }
    }
    return mapMyBookingsErrorToPersian(err);
  }

  async function handleSubmitReview(e: React.FormEvent, bookingId: number) {
    e.preventDefault();
    setReviewError(null);

    if (reviewRating < 1 || reviewRating > 5) {
      setReviewError("لطفاً امتیاز از ۱ تا ۵ ستاره را انتخاب کنید.");
      return;
    }
    const trimmed = reviewText.trim();
    if (!trimmed) {
      setReviewError("لطفاً متن نظر خود را بنویسید.");
      return;
    }
    if (trimmed.length > 1000) {
      setReviewError("متن نظر نباید بیش از ۱۰۰۰ کاراکتر باشد.");
      return;
    }

    setSubmittingReview(true);
    try {
      const created = await createReview({
        booking_id: bookingId,
        rating: reviewRating,
        text: trimmed,
      });
      setReviewsByBookingId((prev) => ({ ...prev, [bookingId]: created }));
      setReviewFormBookingId(null);
      setReviewRating(0);
      setReviewText("");
    } catch (err) {
      if (err instanceof ApiError && err.errorCode === "REVIEW_ALREADY_EXISTS") {
        try {
          const myReviews = await listMyReviews();
          const reviewMap: Record<number, ReviewMineOut> = {};
          for (const r of myReviews) {
            reviewMap[r.booking_id] = r;
          }
          setReviewsByBookingId((prev) => ({ ...prev, ...reviewMap }));
          setReviewFormBookingId(null);
          return;
        } catch (fetchErr) {
          setReviewError(mapMyBookingsErrorToPersian(fetchErr));
          return;
        }
      }
      setReviewError(mapReviewSubmitError(err));
    } finally {
      setSubmittingReview(false);
    }
  }

  async function handleConfirmCancel() {
    if (!cancelState.targetBooking) return;
    dispatchCancel({ type: "START_CANCEL" });
    try {
      const res = await cancelBooking(cancelState.targetBooking.booking_id);
      dispatchCancel({ type: "CANCEL_SUCCEEDED", result: res });

      const [nextBookings, nextWallet] = await Promise.all([listMyBookings(), getMyWallet()]);
      setBookings(nextBookings);
      setWallet(nextWallet);
    } catch (err) {
      dispatchCancel({ type: "CANCEL_FAILED", error: err });
    }
  }

  if (authLoading || (!user && !authLoading)) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-40 animate-pulse rounded bg-stone-200" />
        <div className="h-32 animate-pulse rounded-xl bg-stone-200" />
      </div>
    );
  }

  if (!isCustomer) {
    return (
      <div
        role="alert"
        className="mx-auto max-w-lg space-y-3 rounded-xl border border-amber-200 bg-white p-6"
      >
        <h1 className="text-lg font-bold text-stone-900">دسترسی مشتری</h1>
        <p className="text-sm text-stone-700">این صفحه مخصوص حساب‌های مشتری است.</p>
        <Link href="/" className="text-sm font-medium text-stone-900 underline">
          بازگشت به صفحه اصلی
        </Link>
      </div>
    );
  }

  return (
    <section className="space-y-8">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-stone-900">رزروهای من</h1>
          <p className="text-sm text-stone-600">
            مشاهده رزروها، رسید تفکیک‌شده، لغو رزرو و موجودی کیف پول درون‌برنامه‌ای
          </p>
        </div>
        <Link
          href="/"
          className="text-sm font-medium text-stone-700 underline hover:text-stone-900"
        >
          مشاهده کافه‌ها
        </Link>
      </div>

      {loadError ? (
        <div
          role="alert"
          className="rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-900"
        >
          {loadError}
        </div>
      ) : null}

      {/* Wallet Section (display-only, non-withdrawable) */}
      <div className="rounded-xl border border-stone-200 bg-white p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold text-stone-900">کیف پول درون‌برنامه‌ای</h2>
            <p className="text-xs text-stone-600">{WALLET_NON_WITHDRAWABLE_NOTE}</p>
          </div>
          <div className="rounded-lg bg-stone-100 px-4 py-2 text-left">
            <div className="text-xs text-stone-500">موجودی فعلی</div>
            <div className="text-lg font-bold text-stone-900">
              {loading ? "..." : formatToman(wallet?.balance_toman ?? 0)}
            </div>
          </div>
        </div>

        {wallet && wallet.entries.length > 0 ? (
          <div className="space-y-2 border-t border-stone-100 pt-3">
            <h3 className="text-xs font-semibold text-stone-600">تراکنش‌های اخیر</h3>
            <ul className="divide-y divide-stone-100 text-xs">
              {wallet.entries.map((entry) => (
                <li
                  key={entry.id}
                  className="flex flex-wrap items-center justify-between gap-2 py-2"
                >
                  <div>
                    <span className="font-semibold text-stone-900">
                      {getWalletDirectionLabel(entry.direction)}
                    </span>
                    <span className="mx-2 text-stone-400">•</span>
                    <span className="text-stone-700">{entry.reason}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-stone-500">{entry.jalali_date}</span>
                    <span className="font-bold text-stone-900">
                      {formatToman(entry.amount_toman)}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ) : !loading ? (
          <p className="text-xs text-stone-500">هنوز تراکنشی در کیف پول شما ثبت نشده است.</p>
        ) : null}
      </div>

      {/* Cancel confirmation / result banner */}
      {cancelState.step !== "idle" && cancelState.targetBooking ? (
        <div
          role="region"
          aria-label="تایید لغو رزرو"
          className="rounded-xl border border-amber-300 bg-amber-50 p-5 space-y-3"
        >
          {cancelState.step === "done" && cancelState.result ? (
            <div className="space-y-2">
              <h3 className="text-base font-bold text-emerald-900">
                رزرو #{cancelState.result.booking_id} لغو شد
              </h3>
              <p className="text-sm text-stone-800">
                {cancelState.result.refunded_to_wallet_toman > 0
                  ? `مبلغ ${formatToman(cancelState.result.refunded_to_wallet_toman)} به کیف پول شما واریز شد. موجودی جدید: ${formatToman(cancelState.result.wallet_balance_toman ?? wallet?.balance_toman ?? 0)}`
                  : "بدون بازپرداخت — قفل رزرو با موفقیت آزاد شد."}
              </p>
              <button
                type="button"
                onClick={() => dispatchCancel({ type: "RESET" })}
                className="rounded-lg bg-stone-900 px-4 py-2 text-xs font-medium text-white"
              >
                بستن
              </button>
            </div>
          ) : (
            (() => {
              const summary = getCancelConfirmationSummary(cancelState.targetBooking);
              return (
                <div className="space-y-3">
                  <h3 className="text-base font-bold text-stone-900">
                    تایید لغو رزرو #{cancelState.targetBooking.booking_id} —{" "}
                    {cancelState.targetBooking.venue_name}
                  </h3>
                  <p className="text-sm text-stone-800">{summary.refundText}</p>
                  <p className="text-xs text-stone-700">{summary.addonsNote}</p>
                  {cancelState.errorMessage ? (
                    <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-800">
                      {cancelState.errorMessage}
                    </div>
                  ) : null}
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      disabled={cancelState.step === "cancelling"}
                      onClick={() => void handleConfirmCancel()}
                      className="min-h-[44px] rounded-lg bg-red-700 px-4 py-2 text-xs font-semibold text-white hover:bg-red-800 disabled:opacity-50"
                    >
                      {cancelState.step === "cancelling" ? "در حال لغو..." : "تایید نهایی لغو رزرو"}
                    </button>
                    <button
                      type="button"
                      onClick={() => dispatchCancel({ type: "RESET" })}
                      className="min-h-[44px] rounded-lg border border-stone-300 bg-white px-4 py-2 text-xs font-medium text-stone-700"
                    >
                      انصراف
                    </button>
                  </div>
                </div>
              );
            })()
          )}
        </div>
      ) : null}

      {/* Bookings List */}
      {loading ? (
        <div className="space-y-3">
          <div className="h-28 animate-pulse rounded-xl bg-stone-200" />
          <div className="h-28 animate-pulse rounded-xl bg-stone-200" />
        </div>
      ) : bookings.length === 0 ? (
        <div className="rounded-xl border border-stone-200 bg-white p-8 text-center text-sm text-stone-600">
          هنوز رزروی ثبت نکرده‌اید.
        </div>
      ) : (
        <div className="space-y-4">
          {bookings.map((b) => (
            <div
              key={b.booking_id}
              className="rounded-xl border border-stone-200 bg-white p-5 shadow-sm space-y-3"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="text-base font-bold text-stone-900">
                      #{b.booking_id} — {b.venue_name}
                    </h2>
                    <span className="rounded-full bg-stone-100 px-2.5 py-0.5 text-xs font-medium text-stone-800">
                      {getCustomerBookingStatusLabel(b.status)}
                    </span>
                  </div>
                  <p className="text-xs text-stone-600">
                    میز: {b.table_number} • زمان: {b.start_jalali} تا {b.end_jalali}
                  </p>
                </div>

                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => void handleOpenReceipt(b.booking_id)}
                    className="min-h-[40px] rounded-lg border border-stone-300 px-3 py-1.5 text-xs font-medium text-stone-800 hover:bg-stone-100"
                  >
                    مشاهده رسید
                  </button>
                  {b.is_cancellable ? (
                    <button
                      type="button"
                      onClick={() => dispatchCancel({ type: "OPEN_CONFIRM", booking: b })}
                      className="min-h-[40px] rounded-lg bg-red-50 px-3 py-1.5 text-xs font-semibold text-red-800 border border-red-200 hover:bg-red-100"
                    >
                      لغو رزرو
                    </button>
                  ) : null}
                  {b.status === "COMPLETED" && !reviewsByBookingId[b.booking_id] ? (
                    <button
                      type="button"
                      onClick={() => openReviewForm(b.booking_id)}
                      className="min-h-[40px] rounded-lg bg-stone-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-stone-800"
                    >
                      ثبت نظر
                    </button>
                  ) : null}
                </div>
              </div>

              <div className="grid gap-2 rounded-lg bg-stone-50 p-3 text-xs sm:grid-cols-2">
                <div className="flex justify-between">
                  <span className="text-stone-600">مبلغ آنلاین (هزینه میز):</span>
                  <strong className="text-stone-900">{formatToman(b.amount_online_toman)}</strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-stone-600">پرداخت حضوری در کافه (افزودنی‌ها):</span>
                  <strong className="text-stone-900">
                    {formatToman(b.amount_in_person_toman)}
                  </strong>
                </div>
              </div>

              {reviewsByBookingId[b.booking_id] ? (
                <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs space-y-1">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-semibold text-emerald-950">نظر ثبت‌شده شما</span>
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-amber-700">
                        ★ {reviewsByBookingId[b.booking_id]!.rating} از ۵
                      </span>
                      <span className="text-stone-600">
                        {formatJalaliDate(reviewsByBookingId[b.booking_id]!.created_at)}
                      </span>
                    </div>
                  </div>
                  <p className="text-stone-800">{reviewsByBookingId[b.booking_id]!.text}</p>
                </div>
              ) : null}

              {reviewFormBookingId === b.booking_id && !reviewsByBookingId[b.booking_id] ? (
                <form
                  onSubmit={(e) => void handleSubmitReview(e, b.booking_id)}
                  className="rounded-lg border border-stone-200 bg-stone-50 p-4 space-y-3 text-xs"
                >
                  <div className="space-y-1.5">
                    <div className="font-semibold text-stone-800">امتیاز شما (۱ تا ۵ ستاره):</div>
                    <div
                      role="radiogroup"
                      aria-label="امتیاز از ۱ تا ۵ ستاره"
                      className="flex flex-wrap gap-2"
                    >
                      {[1, 2, 3, 4, 5].map((star) => (
                        <button
                          key={star}
                          type="button"
                          role="radio"
                          aria-checked={reviewRating === star}
                          aria-label={`${star} ستاره`}
                          onClick={() => setReviewRating(star)}
                          className={`rounded-lg border px-3 py-1.5 font-medium ${
                            reviewRating === star
                              ? "border-amber-500 bg-amber-50 text-amber-900"
                              : "border-stone-300 bg-white text-stone-700"
                          }`}
                        >
                          ★ {star}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="space-y-1">
                    <div className="flex items-center justify-between">
                      <label htmlFor={`review-text-${b.booking_id}`} className="font-semibold text-stone-800">
                        متن نظر
                      </label>
                      <span className="text-[11px] text-stone-500">
                        {reviewText.trim().length} / ۱۰۰۰
                      </span>
                    </div>
                    <textarea
                      id={`review-text-${b.booking_id}`}
                      aria-label="متن نظر"
                      rows={3}
                      value={reviewText}
                      onChange={(e) => setReviewText(e.target.value)}
                      placeholder="تجربه خود از این میز و کافه را بنویسید..."
                      className="w-full rounded-lg border border-stone-300 bg-white p-2.5 text-sm"
                    />
                  </div>

                  {reviewError ? (
                    <div
                      role="alert"
                      className="rounded-lg border border-red-200 bg-red-50 p-2.5 text-xs text-red-800"
                    >
                      {reviewError}
                    </div>
                  ) : null}

                  <div className="flex items-center gap-2">
                    <button
                      type="submit"
                      disabled={submittingReview}
                      className="min-h-[38px] rounded-lg bg-stone-900 px-4 py-1.5 text-xs font-medium text-white hover:bg-stone-800 disabled:opacity-50"
                    >
                      {submittingReview ? "در حال ثبت..." : "ارسال نظر"}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setReviewFormBookingId(null);
                        setReviewError(null);
                      }}
                      className="min-h-[38px] rounded-lg border border-stone-300 bg-white px-4 py-1.5 text-xs text-stone-700"
                    >
                      انصراف
                    </button>
                  </div>
                </form>
              ) : null}

              {selectedBookingId === b.booking_id ? (
                <div className="rounded-lg border border-stone-200 bg-stone-50 p-4 text-xs space-y-3">
                  {loadingReceipt ? (
                    <p className="text-stone-600">در حال دریافت رسید...</p>
                  ) : receiptError || !receipt ? (
                    <p className="text-amber-900">
                      {receiptError ?? "رسید برای این رزرو در دسترس نیست."}
                    </p>
                  ) : (
                    <div className="space-y-3">
                      <div className="flex justify-between border-b border-stone-200 pb-2">
                        <span className="font-semibold text-stone-900">بخش پرداخت آنلاین</span>
                        <span className="font-bold text-stone-900">
                          {formatToman(receipt.total_online_toman)}
                        </span>
                      </div>
                      <div className="text-stone-600">
                        درگاه: {receipt.paid_online.provider_name ?? "نامشخص"} • کارت:{" "}
                        <span dir="ltr">{receipt.paid_online.card_pan_masked ?? "—"}</span>
                      </div>

                      <div className="flex justify-between border-b border-stone-200 pb-2 pt-1">
                        <span className="font-semibold text-stone-900">پرداخت حضوری در کافه</span>
                        <span className="font-bold text-stone-900">
                          {formatToman(receipt.total_in_person_toman)}
                        </span>
                      </div>
                      {receipt.payable_in_person.items.length === 0 ? (
                        <p className="text-stone-500">بدون افزودنی</p>
                      ) : (
                        <ul className="space-y-1">
                          {receipt.payable_in_person.items.map((item) => (
                            <li key={item.addon_id} className="flex justify-between text-stone-700">
                              <span>{item.title}</span>
                              <span>{formatToman(item.line_total_toman)}</span>
                            </li>
                          ))}
                        </ul>
                      )}

                      <div className="flex justify-between border-t border-stone-300 pt-2 font-bold text-stone-900">
                        <span>جمع کل:</span>
                        <span>{formatToman(receipt.grand_total_toman)}</span>
                      </div>
                    </div>
                  )}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
