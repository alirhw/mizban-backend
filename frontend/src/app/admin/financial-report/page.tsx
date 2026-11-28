"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useEffect, useState } from "react";

import {
  ApiError,
  getFinancialReport,
  type FinancialReportOut,
  type FinancialReportPaymentRowOut,
  type FinancialReportWalletRowOut,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatJalaliDate } from "@/lib/jalali";
import { formatToman } from "@/lib/panorama";

const PAGE_SIZE = 50;
const PAYMENT_STATUS_OPTIONS = ["INITIATED", "PENDING", "SUCCESS", "FAILED", "TIMEOUT"] as const;

function mapFinancialReportErrorToPersian(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 403 || err.errorCode === "FORBIDDEN") {
      return "فقط مدیران کل پلتفرم به گزارش مالی دسترسی دارند.";
    }
    if (err.status === 422 || err.errorCode === "VALIDATION_ERROR") {
      return "بازه یا فرمت تاریخ انتخاب‌شده معتبر نیست.";
    }
  }
  return "خطایی در دریافت گزارش مالی رخ داد.";
}

export default function AdminFinancialReportPage() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();

  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [paymentStatus, setPaymentStatus] = useState("");

  const [report, setReport] = useState<FinancialReportOut | null>(null);
  const [paymentRows, setPaymentRows] = useState<FinancialReportPaymentRowOut[]>([]);
  const [walletRows, setWalletRows] = useState<FinancialReportWalletRowOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [forbidden, setForbidden] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      router.replace(`/login?next=${encodeURIComponent("/admin/financial-report")}`);
      return;
    }

    let active = true;
    setLoading(true);
    setErrorMessage(null);

    getFinancialReport({
      ...(fromDate ? { from_date: fromDate } : {}),
      ...(toDate ? { to_date: toDate } : {}),
      ...(paymentStatus ? { payment_status: paymentStatus } : {}),
      limit: PAGE_SIZE,
      offset: 0,
    })
      .then((data) => {
        if (!active) return;
        setReport(data);
        setPaymentRows(data.payments.rows);
        setWalletRows(data.wallet.rows);
        setHasMore(
          data.payments.rows.length === PAGE_SIZE || data.wallet.rows.length === PAGE_SIZE
        );
        setForbidden(false);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof ApiError && err.status === 401) {
          router.replace(`/login?next=${encodeURIComponent("/admin/financial-report")}`);
          return;
        }
        if (err instanceof ApiError && (err.status === 403 || err.errorCode === "FORBIDDEN")) {
          setForbidden(true);
          setErrorMessage(mapFinancialReportErrorToPersian(err));
          return;
        }
        setErrorMessage(mapFinancialReportErrorToPersian(err));
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [authLoading, user, fromDate, toDate, paymentStatus, router]);

  async function handleShowMore() {
    setLoadingMore(true);
    setErrorMessage(null);
    try {
      const nextOffset = Math.max(paymentRows.length, walletRows.length);
      const data = await getFinancialReport({
        ...(fromDate ? { from_date: fromDate } : {}),
        ...(toDate ? { to_date: toDate } : {}),
        ...(paymentStatus ? { payment_status: paymentStatus } : {}),
        limit: PAGE_SIZE,
        offset: nextOffset,
      });
      setReport(data);
      setPaymentRows((prev) => [...prev, ...data.payments.rows]);
      setWalletRows((prev) => [...prev, ...data.wallet.rows]);
      setHasMore(
        data.payments.rows.length === PAGE_SIZE || data.wallet.rows.length === PAGE_SIZE
      );
    } catch (err) {
      setErrorMessage(mapFinancialReportErrorToPersian(err));
    } finally {
      setLoadingMore(false);
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
          {errorMessage ?? "فقط مدیران کل پلتفرم به گزارش مالی دسترسی دارند."}
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
          <h1 className="text-2xl font-bold text-stone-900">گزارش مالی پلتفرم</h1>
          <p className="text-sm text-stone-600">
            مجموع تراکنش‌های پرداخت آنلاین، دفتر کل کیف پول و بخش اشتراک‌ها بر اساس تاریخ تهران
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
            htmlFor="report-from-date"
            className="mb-1 block text-xs font-medium text-stone-700"
          >
            از تاریخ (تهران)
          </label>
          <input
            id="report-from-date"
            type="date"
            aria-label="از تاریخ"
            value={fromDate}
            onChange={(e) => setFromDate(e.target.value)}
            className="rounded-lg border border-stone-300 bg-white px-3 py-1.5 text-sm"
          />
        </div>

        <div>
          <label
            htmlFor="report-to-date"
            className="mb-1 block text-xs font-medium text-stone-700"
          >
            تا تاریخ (تهران)
          </label>
          <input
            id="report-to-date"
            type="date"
            aria-label="تا تاریخ"
            value={toDate}
            onChange={(e) => setToDate(e.target.value)}
            className="rounded-lg border border-stone-300 bg-white px-3 py-1.5 text-sm"
          />
        </div>

        <div>
          <label
            htmlFor="report-payment-status"
            className="mb-1 block text-xs font-medium text-stone-700"
          >
            وضعیت پرداخت (فیلتر ردیف‌ها)
          </label>
          <select
            id="report-payment-status"
            aria-label="وضعیت پرداخت"
            value={paymentStatus}
            onChange={(e) => setPaymentStatus(e.target.value)}
            className="rounded-lg border border-stone-300 bg-white px-3 py-1.5 text-sm"
          >
            <option value="">همه</option>
            {PAYMENT_STATUS_OPTIONS.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
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

      {loading || !report ? (
        <div className="rounded-xl border border-stone-200 bg-white p-6 text-sm text-stone-600">
          در حال دریافت گزارش مالی...
        </div>
      ) : (
        <div className="space-y-6">
          {/* Payments Totals & Rows */}
          <div className="rounded-xl border border-stone-200 bg-white p-5 space-y-4">
            <h2 className="text-lg font-bold text-stone-900">پرداخت‌های آنلاین</h2>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg bg-stone-50 p-3 text-sm">
                <div className="text-xs text-stone-500">
                  مجموع پرداخت‌های موفق (کل بازه فیلتر)
                </div>
                <div className="mt-1 text-lg font-bold text-stone-900">
                  {formatToman(report.payments.total_toman)}
                </div>
              </div>
              <div className="rounded-lg bg-stone-50 p-3 text-sm">
                <div className="text-xs text-stone-500">
                  تعداد کل تراکنش‌ها (کل بازه فیلتر)
                </div>
                <div className="mt-1 text-lg font-bold text-stone-900">{report.payments.count}</div>
              </div>
            </div>

            <div className="flex flex-wrap gap-2 text-xs">
              {Object.entries(report.payments.counts_by_status).map(([status, statusCount]) => (
                <span
                  key={status}
                  className="rounded-full border border-stone-200 bg-stone-50 px-3 py-1 text-stone-700"
                >
                  {status}: {statusCount}
                </span>
              ))}
            </div>

            {paymentRows.length === 0 ? (
              <p className="text-sm text-stone-500">تراکنش پرداختی در این بازه یافت نشد.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-right text-sm">
                  <thead>
                    <tr className="border-b border-stone-200 text-xs text-stone-500">
                      <th className="py-2 pl-3">شناسه</th>
                      <th className="py-2 pl-3">رزرو</th>
                      <th className="py-2 pl-3">شناسه مشتری</th>
                      <th className="py-2 pl-3">درگاه</th>
                      <th className="py-2 pl-3">مبلغ</th>
                      <th className="py-2 pl-3">وضعیت</th>
                      <th className="py-2">تاریخ</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-stone-100">
                    {paymentRows.map((row) => (
                      <tr key={row.id}>
                        <td className="py-2.5 pl-3 font-mono text-xs">{row.id}</td>
                        <td className="py-2.5 pl-3">#{row.booking_id}</td>
                        <td className="py-2.5 pl-3">{row.customer_id}</td>
                        <td className="py-2.5 pl-3">{row.provider_name}</td>
                        <td className="py-2.5 pl-3 font-medium">{formatToman(row.amount_toman)}</td>
                        <td className="py-2.5 pl-3 text-xs">{row.status}</td>
                        <td className="py-2.5 text-xs text-stone-600">
                          {formatJalaliDate(row.created_at, { includeTime: true })}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Wallet Section */}
          <div className="rounded-xl border border-stone-200 bg-white p-5 space-y-4">
            <h2 className="text-lg font-bold text-stone-900">تراکنش‌های کیف پول</h2>

            <div className="grid gap-3 sm:grid-cols-3 text-sm">
              <div className="rounded-lg bg-stone-50 p-3">
                <div className="text-xs text-stone-500">مجموع واریز (CREDIT)</div>
                <div className="mt-1 font-bold text-stone-900">
                  {formatToman(report.wallet.total_credit_toman)}
                </div>
              </div>
              <div className="rounded-lg bg-stone-50 p-3">
                <div className="text-xs text-stone-500">مجموع برداشت (DEBIT)</div>
                <div className="mt-1 font-bold text-stone-900">
                  {formatToman(report.wallet.total_debit_toman)}
                </div>
              </div>
              <div className="rounded-lg bg-stone-50 p-3">
                <div className="text-xs text-stone-500">تعداد کل ردیف‌های کیف پول</div>
                <div className="mt-1 font-bold text-stone-900">{report.wallet.count}</div>
              </div>
            </div>

            {walletRows.length === 0 ? (
              <p className="text-sm text-stone-500">تراکنش کیف پولی در این بازه یافت نشد.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-right text-sm">
                  <thead>
                    <tr className="border-b border-stone-200 text-xs text-stone-500">
                      <th className="py-2 pl-3">شناسه</th>
                      <th className="py-2 pl-3">کاربر</th>
                      <th className="py-2 pl-3">نوع</th>
                      <th className="py-2 pl-3">مبلغ</th>
                      <th className="py-2 pl-3">مانده پس از تراکنش</th>
                      <th className="py-2 pl-3">دلیل</th>
                      <th className="py-2 pl-3">رزرو</th>
                      <th className="py-2">تاریخ</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-stone-100">
                    {walletRows.map((row) => (
                      <tr key={row.id}>
                        <td className="py-2.5 pl-3 font-mono text-xs">{row.id}</td>
                        <td className="py-2.5 pl-3">{row.user_id}</td>
                        <td className="py-2.5 pl-3 text-xs">{row.type}</td>
                        <td className="py-2.5 pl-3 font-medium">{formatToman(row.amount_toman)}</td>
                        <td className="py-2.5 pl-3">{formatToman(row.balance_after_toman)}</td>
                        <td className="py-2.5 pl-3 text-xs">{row.reason}</td>
                        <td className="py-2.5 pl-3 text-xs">
                          {row.booking_id !== null ? `#${row.booking_id}` : "—"}
                        </td>
                        <td className="py-2.5 text-xs text-stone-600">
                          {formatJalaliDate(row.created_at, { includeTime: true })}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Subscriptions Section (Always empty until FR-27) */}
          <div className="rounded-xl border border-stone-200 bg-white p-5 space-y-3">
            <h2 className="text-lg font-bold text-stone-900">اشتراک‌ها</h2>
            <div className="grid gap-3 sm:grid-cols-2 text-sm">
              <div className="rounded-lg bg-stone-50 p-3">
                <div className="text-xs text-stone-500">مجموع اشتراک‌ها</div>
                <div className="mt-1 font-bold text-stone-900">
                  {formatToman(report.subscriptions.total_toman)}
                </div>
              </div>
              <div className="rounded-lg bg-stone-50 p-3">
                <div className="text-xs text-stone-500">تعداد</div>
                <div className="mt-1 font-bold text-stone-900">{report.subscriptions.count}</div>
              </div>
            </div>
            {report.subscriptions.rows.length === 0 ? (
              <p className="text-sm text-stone-500">
                هنوز پرداخت آنلاین اشتراکی ثبت نشده است (تا پیاده‌سازی FR-27 خالی است).
              </p>
            ) : null}
          </div>

          {hasMore ? (
            <div>
              <button
                type="button"
                disabled={loadingMore}
                onClick={() => void handleShowMore()}
                className="rounded-lg border border-stone-300 px-4 py-2 text-xs font-medium text-stone-800 hover:bg-stone-100 disabled:opacity-50"
              >
                {loadingMore ? "در حال بارگذاری..." : "نمایش ردیف‌های بیشتر"}
              </button>
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}
