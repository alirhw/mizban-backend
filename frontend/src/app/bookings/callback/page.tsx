"use client";

import Link from "next/link";
import React, { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";

import { ApiError, getBookingReceipt, initiatePayment, type SplitReceiptOut } from "@/lib/api";
import {
  getOrCreateBookingIdempotencyKey,
  mapBookingErrorToPersian,
  resolveCallbackReceiptConfirmed,
} from "@/lib/booking";
import { formatToman } from "@/lib/panorama";

function generateIdempotencyKey(bookingId: number): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `mizban-retry-${bookingId}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function BookingCallbackContent() {
  const searchParams = useSearchParams();

  const rawBookingId = searchParams.get("booking_id");
  const bookingStatus = searchParams.get("booking_status");
  const paymentStatus = searchParams.get("payment_status");
  const refundRequired = searchParams.get("refund_required");
  const venueSlug = searchParams.get("venue");

  const parsedBookingId = rawBookingId ? Number(rawBookingId) : NaN;
  const hasValidBookingId = Number.isInteger(parsedBookingId) && parsedBookingId > 0;
  const isConfirmed = bookingStatus === "CONFIRMED";
  const restartHref = venueSlug ? `/venues/${encodeURIComponent(venueSlug)}` : "/";

  const [receipt, setReceipt] = useState<SplitReceiptOut | null>(null);
  const [loadingReceipt, setLoadingReceipt] = useState(isConfirmed && hasValidBookingId);
  const [receiptError, setReceiptError] = useState<string | null>(null);

  const [retryingPayment, setRetryingPayment] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);
  const [lockExpired, setLockExpired] = useState(false);
  const retryIdempotencyRef = useRef<{ bookingId: number; key: string } | null>(null);

  useEffect(() => {
    if (!isConfirmed || !hasValidBookingId) {
      return;
    }

    let active = true;

    getBookingReceipt(parsedBookingId)
      .then((data) => {
        if (active) {
          setReceipt(data);
          setReceiptError(null);
        }
      })
      .catch((err) => {
        if (active) setReceiptError(mapBookingErrorToPersian(err));
      })
      .finally(() => {
        if (active) setLoadingReceipt(false);
      });

    return () => {
      active = false;
    };
  }, [isConfirmed, hasValidBookingId, parsedBookingId]);

  async function handleRetryPayment() {
    if (!hasValidBookingId) return;
    setRetryingPayment(true);
    setRetryError(null);

    try {
      const nextKey = getOrCreateBookingIdempotencyKey(
        retryIdempotencyRef.current,
        parsedBookingId,
        () => generateIdempotencyKey(parsedBookingId)
      );
      retryIdempotencyRef.current = nextKey;
      const venueQuery = venueSlug ? `venue=${encodeURIComponent(venueSlug)}&` : "";
      const callbackUrl = `${window.location.origin}/bookings/callback?${venueQuery}booking_id=${parsedBookingId}`;
      const res = await initiatePayment({
        booking_id: parsedBookingId,
        idempotency_key: nextKey.key,
        callback_url: callbackUrl,
      });
      window.location.assign(res.redirect_url);
    } catch (err) {
      if (
        err instanceof ApiError &&
        (err.errorCode === "BOOKING_LOCK_EXPIRED" || err.errorCode === "LOCK_EXPIRED")
      ) {
        setLockExpired(true);
      }
      setRetryError(mapBookingErrorToPersian(err));
      setRetryingPayment(false);
    }
  }

  if (!hasValidBookingId) {
    return (
      <div className="mx-auto max-w-xl space-y-4 rounded-xl border border-red-200 bg-white p-6">
        <h1 className="text-lg font-bold text-red-900">اطلاعات بازگشت از درگاه ناقص است</h1>
        <p className="text-sm text-stone-700">
          شناسه رزرو معتبر نیست. لطفاً مجدداً فرآیند رزرو را شروع کنید.
        </p>
        <Link
          href={restartHref}
          className="inline-block rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white hover:bg-stone-800"
        >
          شروع مجدد رزرو
        </Link>
      </div>
    );
  }

  if (isConfirmed) {
    if (loadingReceipt) {
      return (
        <div className="mx-auto max-w-xl rounded-xl border border-stone-200 bg-white p-6 text-sm text-stone-600">
          در حال دریافت رسید رزرو...
        </div>
      );
    }

    if (receiptError || !receipt) {
      return (
        <div className="mx-auto max-w-xl space-y-4 rounded-xl border border-red-200 bg-white p-6">
          <h1 className="text-lg font-bold text-red-900">دریافت رسید رزرو ناموفق بود</h1>
          <p className="text-sm text-red-800">
            {receiptError ?? "دریافت جزئیات رسید با خطا مواجه شد."}
          </p>
          <Link
            href={restartHref}
            className="inline-block rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white hover:bg-stone-800"
          >
            بازگشت به صفحه مجموعه
          </Link>
        </div>
      );
    }

    const isReceiptConfirmed = resolveCallbackReceiptConfirmed(receipt, receiptError);

    return (
      <div className="mx-auto max-w-2xl space-y-5 rounded-xl border border-emerald-200 bg-white p-6 shadow-sm">
        <div className="space-y-1 border-b border-stone-200 pb-4">
          {isReceiptConfirmed ? (
            <div className="inline-block rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-900">
              رزرو تایید شد
            </div>
          ) : null}
          <h1 className="text-xl font-bold text-stone-900">
            رسید تفکیک‌شده رزرو #{receipt.booking_id}
          </h1>
          <p className="text-sm text-stone-600">
            {receipt.venue_name} — میز {receipt.table_number}
          </p>
          <p className="text-xs text-stone-500">
            تاریخ: {receipt.jalali_date} | بازه زمانی: {receipt.jalali_start_datetime} تا{" "}
            {receipt.jalali_end_datetime}
          </p>
        </div>

        {/* Paid Online Section */}
        <div className="space-y-2 rounded-lg border border-stone-200 bg-stone-50 p-4">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-sm font-bold text-stone-900">{receipt.paid_online.label}</h2>
            <span className="text-sm font-bold text-emerald-800">
              {formatToman(receipt.paid_online.amount_online_toman)}
            </span>
          </div>
          <p className="text-xs text-stone-600">{receipt.paid_online.description}</p>
          {receipt.paid_online.provider_name ? (
            <p className="text-xs text-stone-600">
              درگاه پرداخت: {receipt.paid_online.provider_name}
            </p>
          ) : null}
          {receipt.paid_online.card_pan_masked ? (
            <p className="text-xs text-stone-600">
              شماره کارت: <span dir="ltr">{receipt.paid_online.card_pan_masked}</span>
            </p>
          ) : null}
        </div>

        {/* Payable In Person Section */}
        <div className="space-y-2 rounded-lg border border-stone-200 bg-stone-50 p-4">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-sm font-bold text-stone-900">
              {receipt.payable_in_person.label} (پرداخت حضوری در کافه)
            </h2>
            <span className="text-sm font-bold text-stone-900">
              {formatToman(receipt.payable_in_person.total_in_person_toman)}
            </span>
          </div>

          {receipt.payable_in_person.items.length === 0 ? (
            <p className="text-xs text-stone-600">بدون افزودنی — پرداخت حضوری در کافه</p>
          ) : (
            <ul className="space-y-1 text-xs text-stone-700">
              {receipt.payable_in_person.items.map((item) => (
                <li key={item.addon_id} className="flex justify-between gap-2">
                  <span>{item.title}</span>
                  <span>{formatToman(item.line_total_toman)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Totals */}
        <div className="space-y-1.5 rounded-lg border border-stone-200 bg-white p-4 text-sm">
          <div className="flex justify-between">
            <span className="text-stone-600">جمع پرداخت آنلاین:</span>
            <span className="font-semibold text-stone-900">
              {formatToman(receipt.total_online_toman)}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-stone-600">جمع پرداخت حضوری در کافه:</span>
            <span className="font-semibold text-stone-900">
              {formatToman(receipt.total_in_person_toman)}
            </span>
          </div>
          <hr className="my-1 border-stone-200" />
          <div className="flex justify-between text-base font-bold text-stone-900">
            <span>مبلغ کل رزرو:</span>
            <span>{formatToman(receipt.grand_total_toman)}</span>
          </div>
        </div>

        <div className="flex flex-wrap gap-3">
          <Link
            href={
              receipt.venue_slug ? `/venues/${encodeURIComponent(receipt.venue_slug)}` : restartHref
            }
            className="rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white hover:bg-stone-800"
          >
            بازگشت به صفحه مجموعه
          </Link>
          <Link
            href="/"
            className="rounded-lg border border-stone-300 px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-100"
          >
            صفحه اصلی
          </Link>
        </div>
      </div>
    );
  }

  // FAILED / TIMEOUT or non-CONFIRMED
  const isTimeout = paymentStatus === "TIMEOUT";
  const showRefundNotice = refundRequired === "true" || refundRequired === "1";

  return (
    <div className="mx-auto max-w-xl space-y-4 rounded-xl border border-red-200 bg-white p-6 shadow-sm">
      <h1 className="text-lg font-bold text-red-900">
        {isTimeout ? "زمان پرداخت در درگاه به پایان رسید" : "پرداخت آنلاین ناموفق بود"}
      </h1>
      <p className="text-sm text-stone-700">
        {isTimeout
          ? "به دلیل اتمام زمان تراکنش، پرداخت تکمیل نشد."
          : "تراکنش بانکی تکمیل نشد. در صورت فعال بودن قفل رزرو می‌توانید دوباره تلاش کنید."}
      </p>

      {showRefundNotice ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
          در صورت کسر وجه از حساب شما، مبلغ به‌صورت خودکار به کارت بانکی شما بازگردانده می‌شود.
        </div>
      ) : null}

      {retryError ? (
        <div
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
        >
          {retryError}
        </div>
      ) : null}

      <div className="flex flex-wrap gap-3 pt-2">
        {!lockExpired ? (
          <button
            type="button"
            disabled={retryingPayment}
            onClick={() => void handleRetryPayment()}
            className="min-h-[44px] rounded-lg bg-stone-900 px-5 py-2.5 text-sm font-medium text-white hover:bg-stone-800 disabled:opacity-50"
          >
            {retryingPayment ? "در حال انتقال به درگاه..." : "تلاش مجدد پرداخت"}
          </button>
        ) : null}

        <Link
          href={restartHref}
          className="inline-flex min-h-[44px] items-center rounded-lg border border-stone-300 px-5 py-2.5 text-sm font-medium text-stone-700 hover:bg-stone-100"
        >
          شروع مجدد رزرو
        </Link>
      </div>
    </div>
  );
}

export default function BookingCallbackPage() {
  return (
    <Suspense
      fallback={
        <div className="mx-auto max-w-xl rounded-xl border border-stone-200 bg-white p-6 text-sm text-stone-600">
          در حال بررسی وضعیت پرداخت...
        </div>
      }
    >
      <BookingCallbackContent />
    </Suspense>
  );
}
