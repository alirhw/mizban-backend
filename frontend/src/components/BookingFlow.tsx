"use client";

import React, { useEffect, useMemo, useReducer, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import {
  ApiError,
  initiateBooking,
  initiatePayment,
  listVenueSlots,
  type DesignAddonOut,
  type PublicTablePinOut,
  type SlotOut,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  bookingReducer,
  buildBookingReturnUrl,
  computeBookingSummary,
  computeLockRemainingSeconds,
  formatCountdownMmSs,
  getOrCreateBookingIdempotencyKey,
  INITIAL_BOOKING_STATE,
  mapBookingErrorToPersian,
  type BookingResumeParams,
} from "@/lib/booking";
import {
  formatJalaliDate,
  formatJalaliFromIsoDate,
  getTehranDateIso,
  isSlotAtLeast24HoursAhead,
} from "@/lib/jalali";
import { formatToman } from "@/lib/panorama";

export interface BookingFlowProps {
  venueId: number;
  venueName: string;
  venueSlug: string;
  designAddons: DesignAddonOut[];
  selectedPin: PublicTablePinOut;
  onChangeTable?: () => void;
  initialResume?: BookingResumeParams | null;
}

function getTehranTimeHhMm(isoUtc: string): string {
  const date = new Date(isoUtc);
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Tehran",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const hour = parts.find((p) => p.type === "hour")?.value ?? "00";
  const minute = parts.find((p) => p.type === "minute")?.value ?? "00";
  return `${hour === "24" ? "00" : hour}:${minute}`;
}

function generateIdempotencyKey(bookingId: number): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `mizban-${bookingId}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export function BookingFlow({
  venueId,
  venueName,
  venueSlug,
  designAddons,
  selectedPin,
  onChangeTable,
  initialResume = null,
}: BookingFlowProps) {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [state, dispatch] = useReducer(
    bookingReducer,
    { pinId: selectedPin.id, resume: initialResume },
    ({ pinId, resume }) => {
      let next = bookingReducer(INITIAL_BOOKING_STATE, { type: "START" });
      next = bookingReducer(next, { type: "SELECT_TABLE", tablePinId: pinId });
      if (resume && resume.pinId === pinId) {
        next = bookingReducer(next, {
          type: "SELECT_SLOT",
          slotDate: resume.slotDate,
          slotStartIso: resume.slotStartIso,
          slotEndIso: resume.slotStartIso,
        });
        for (const addonId of resume.addonIds) {
          next = bookingReducer(next, { type: "TOGGLE_ADDON", addonId });
        }
        if (resume.step === "review") {
          next = bookingReducer(next, { type: "PROCEED_TO_REVIEW" });
        }
      }
      return next;
    }
  );

  const dateOptions = useMemo(
    () => Array.from({ length: 7 }, (_, index) => getTehranDateIso(index + 1)),
    []
  );

  const [activeDate, setActiveDate] = useState<string>(
    () => initialResume?.slotDate ?? getTehranDateIso(1)
  );
  const [slotsRefreshNonce, setSlotsRefreshNonce] = useState(0);
  const currentRequestKey = `${activeDate}:${selectedPin.id}:${slotsRefreshNonce}`;
  const [slotsState, setSlotsState] = useState<{
    requestKey: string;
    slots: SlotOut[];
    error: string | null;
  }>({
    requestKey: "",
    slots: [],
    error: null,
  });
  const [slotConflictNotice, setSlotConflictNotice] = useState<string | null>(null);
  const [selectedSlotLabel, setSelectedSlotLabel] = useState<string | null>(
    () => initialResume?.slotLabel ?? null
  );

  const [submittingLock, setSubmittingLock] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submittingPayment, setSubmittingPayment] = useState(false);
  const [nowMs, setNowMs] = useState<number>(() => Date.now());
  const paymentIdempotencyRef = useRef<{ bookingId: number; key: string } | null>(null);

  const loadingSlots = state.step === "slot" && slotsState.requestKey !== currentRequestKey;
  const slots = slotsState.requestKey === currentRequestKey ? slotsState.slots : [];
  const slotsError = slotsState.requestKey === currentRequestKey ? slotsState.error : null;

  useEffect(() => {
    if (state.step !== "slot") return;
    let active = true;
    const reqKey = currentRequestKey;

    listVenueSlots(venueId, {
      date: activeDate,
      table_pin_id: selectedPin.id,
    })
      .then((result) => {
        if (active) {
          setSlotsState({ requestKey: reqKey, slots: result, error: null });
        }
      })
      .catch((err) => {
        if (active) {
          setSlotsState({
            requestKey: reqKey,
            slots: [],
            error: mapBookingErrorToPersian(err),
          });
        }
      });

    return () => {
      active = false;
    };
  }, [state.step, venueId, activeDate, selectedPin.id, currentRequestKey]);

  useEffect(() => {
    if (state.step !== "locked" && state.step !== "failed") {
      return;
    }

    const timer = window.setInterval(() => {
      const current = Date.now();
      setNowMs(current);
      if (state.lockExpiresAt && computeLockRemainingSeconds(state.lockExpiresAt, current) <= 0) {
        dispatch({ type: "LOCK_EXPIRED" });
      }
    }, 1000);
    return () => window.clearInterval(timer);
  }, [state.step, state.lockExpiresAt]);

  const remainingSeconds =
    state.step === "locked" || state.step === "failed"
      ? computeLockRemainingSeconds(state.lockExpiresAt, nowMs)
      : 0;

  const activeAddons = useMemo(
    () => designAddons.filter((addon) => addon.is_active),
    [designAddons]
  );

  const selectedAddons = useMemo(
    () => activeAddons.filter((addon) => state.addonIds.includes(addon.id)),
    [activeAddons, state.addonIds]
  );

  const summary = useMemo(
    () => computeBookingSummary(selectedPin.reservation_fee_toman, selectedAddons),
    [selectedPin.reservation_fee_toman, selectedAddons]
  );

  if (state.step === "idle") {
    return null;
  }

  async function handleConfirmAndLock() {
    if (authLoading) return;
    setSubmitError(null);

    if (!user) {
      const returnPath = buildBookingReturnUrl(venueSlug, {
        pinId: selectedPin.id,
        slotDate: state.slotDate,
        slotStartIso: state.slotStartIso,
        slotLabel: selectedSlotLabel,
        addonIds: state.addonIds,
        step: "review",
      });
      router.push(`/login?next=${encodeURIComponent(returnPath)}`);
      return;
    }

    if (!state.slotDate || !state.slotStartIso) {
      setSubmitError("لطفاً ابتدا تاریخ و ساعت رزرو را انتخاب کنید.");
      return;
    }

    setSubmittingLock(true);
    try {
      const res = await initiateBooking({
        table_pin_id: selectedPin.id,
        slot_date: state.slotDate,
        slot_start_time: getTehranTimeHhMm(state.slotStartIso),
        venue_id: venueId,
        addon_ids: state.addonIds,
      });

      setSlotConflictNotice(null);
      dispatch({
        type: "LOCK_ACQUIRED",
        bookingId: res.booking_id,
        lockExpiresAt: res.lock_expires_at,
        amountOnlineToman: res.amount_online_toman,
        amountInPersonToman: res.amount_in_person_toman,
      });
    } catch (err) {
      if (err instanceof ApiError && err.errorCode === "SLOT_ALREADY_RESERVED") {
        setSlotConflictNotice("این اسلات همین‌الان رزرو شد؛ یک اسلات دیگر انتخاب کنید");
        dispatch({ type: "BACK_TO_SLOT" });
        setSlotsRefreshNonce((prev) => prev + 1);
      } else {
        setSubmitError(mapBookingErrorToPersian(err));
      }
    } finally {
      setSubmittingLock(false);
    }
  }

  async function handleStartPayment() {
    if (!state.bookingId) return;

    if (state.step === "failed") {
      dispatch({ type: "RETRY_PAYMENT" });
    }
    dispatch({ type: "START_PAYMENT" });
    setSubmittingPayment(true);

    try {
      const bookingId = state.bookingId;
      const nextKey = getOrCreateBookingIdempotencyKey(
        paymentIdempotencyRef.current,
        bookingId,
        () => generateIdempotencyKey(bookingId)
      );
      paymentIdempotencyRef.current = nextKey;
      const callbackUrl = `${window.location.origin}/bookings/callback?venue=${encodeURIComponent(venueSlug)}&booking_id=${bookingId}`;
      const res = await initiatePayment({
        booking_id: bookingId,
        idempotency_key: nextKey.key,
        callback_url: callbackUrl,
      });
      window.location.assign(res.redirect_url);
    } catch (err) {
      dispatch({ type: "PAYMENT_FAILED", error: err });
      setSubmittingPayment(false);
    }
  }

  function handleRestartBooking() {
    paymentIdempotencyRef.current = null;
    setSlotConflictNotice(null);
    setSubmitError(null);
    setSelectedSlotLabel(null);
    dispatch({ type: "RESTART" });
    dispatch({ type: "START" });
    dispatch({ type: "SELECT_TABLE", tablePinId: selectedPin.id });
    setSlotsRefreshNonce((prev) => prev + 1);
  }

  return (
    <section
      aria-label="فرآیند رزرو میز"
      className="space-y-5 rounded-xl border border-stone-300 bg-white p-5 shadow-sm"
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-stone-200 pb-3">
        <div>
          <h2 className="text-lg font-bold text-stone-900">
            رزرو میز «{selectedPin.table_number}» در {venueName}
          </h2>
          <p className="text-xs text-stone-500">
            ظرفیت {selectedPin.capacity} نفر — هزینه رزرو آنلاین:{" "}
            {formatToman(selectedPin.reservation_fee_toman)}
          </p>
        </div>

        {onChangeTable && state.step !== "locked" && state.step !== "paying" ? (
          <button
            type="button"
            onClick={onChangeTable}
            className="text-xs text-stone-600 underline hover:text-stone-900"
          >
            تغییر میز از نمای ۳۶۰ درجه
          </button>
        ) : null}
      </div>

      {/* Step 2: Slot Selection */}
      {state.step === "slot" ? (
        <div className="space-y-4">
          <div className="space-y-2">
            <h3 className="text-sm font-semibold text-stone-800">۱. انتخاب تاریخ (۷ روز آینده)</h3>
            <div className="flex flex-wrap gap-2">
              {dateOptions.map((dateIso) => {
                const isSelected = dateIso === activeDate;
                return (
                  <button
                    key={dateIso}
                    type="button"
                    onClick={() => {
                      setActiveDate(dateIso);
                      setSlotConflictNotice(null);
                    }}
                    className={`min-h-[40px] rounded-lg px-3 py-2 text-xs font-medium transition ${
                      isSelected
                        ? "bg-stone-900 text-white"
                        : "border border-stone-300 bg-white text-stone-700 hover:bg-stone-100"
                    }`}
                  >
                    {formatJalaliFromIsoDate(dateIso)}
                  </button>
                );
              })}
            </div>
          </div>

          {slotConflictNotice ? (
            <div
              role="alert"
              className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900"
            >
              {slotConflictNotice}
            </div>
          ) : null}

          <div className="space-y-2">
            <h3 className="text-sm font-semibold text-stone-800">
              ۲. انتخاب ساعت برای {formatJalaliFromIsoDate(activeDate)}
            </h3>

            {loadingSlots ? (
              <div className="rounded-lg border border-stone-200 bg-stone-50 p-4 text-sm text-stone-600">
                در حال دریافت زمان‌های قابل رزرو...
              </div>
            ) : slotsError ? (
              <div
                role="alert"
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800"
              >
                <span>{slotsError}</span>
                <button
                  type="button"
                  onClick={() => setSlotsRefreshNonce((prev) => prev + 1)}
                  className="rounded-md border border-red-300 bg-white px-3 py-1 text-xs font-medium text-red-800 hover:bg-red-100"
                >
                  تلاش مجدد
                </button>
              </div>
            ) : slots.length === 0 ? (
              <div className="rounded-lg border border-stone-200 bg-stone-50 p-4 text-sm text-stone-600">
                در این تاریخ زمانی برای رزرو یافت نشد.
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 md:grid-cols-3">
                {slots.map((slot) => {
                  const meetsLeadTime = isSlotAtLeast24HoursAhead(slot.start);
                  const selectable = slot.is_bookable && meetsLeadTime;
                  const jalaliDateLabel = formatJalaliFromIsoDate(activeDate);
                  const timeRangeLabel = `${slot.start_jalali} تا ${slot.end_jalali}`;

                  return (
                    <button
                      key={slot.start}
                      type="button"
                      disabled={!selectable}
                      onClick={() => {
                        setSelectedSlotLabel(`${jalaliDateLabel} — ${timeRangeLabel}`);
                        setSlotConflictNotice(null);
                        dispatch({
                          type: "SELECT_SLOT",
                          slotDate: activeDate,
                          slotStartIso: slot.start,
                          slotEndIso: slot.end,
                        });
                      }}
                      className={`flex flex-col items-start gap-1 rounded-lg border p-3 text-right transition ${
                        selectable
                          ? "border-stone-300 bg-white text-stone-900 hover:border-stone-900 hover:bg-stone-50"
                          : "cursor-not-allowed border-stone-200 bg-stone-100 text-stone-400"
                      }`}
                    >
                      <span className="text-sm font-semibold">{timeRangeLabel}</span>
                      <span className="text-xs">{jalaliDateLabel}</span>
                      {!selectable ? (
                        <span className="text-[11px] text-stone-500">
                          {!meetsLeadTime ? "کمتر از ۲۴ ساعت تا شروع" : "غیرقابل رزرو"}
                        </span>
                      ) : null}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      ) : null}

      {/* Step 3: Design Add-ons */}
      {state.step === "addons" ? (
        <div className="space-y-4">
          <div className="space-y-1">
            <h3 className="text-sm font-semibold text-stone-800">
              ۳. افزودنی‌های طراحی میز (اختیاری)
            </h3>
            <p className="text-xs text-stone-600">
              هزینه افزودنی‌های انتخابی به‌صورت{" "}
              <strong className="font-semibold text-stone-900">پرداخت حضوری در کافه</strong> محاسبه
              می‌شود و در پرداخت آنلاین دریافت نمی‌گردد.
            </p>
          </div>

          {activeAddons.length === 0 ? (
            <div className="rounded-lg border border-stone-200 bg-stone-50 p-4 text-sm text-stone-600">
              افزودنی طراحی برای این مجموعه ثبت نشده است.
            </div>
          ) : (
            <div className="space-y-2">
              {activeAddons.map((addon) => {
                const checked = state.addonIds.includes(addon.id);
                return (
                  <label
                    key={addon.id}
                    className={`flex cursor-pointer items-center justify-between gap-3 rounded-lg border p-3 transition ${
                      checked
                        ? "border-stone-900 bg-stone-50"
                        : "border-stone-200 bg-white hover:bg-stone-50"
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => dispatch({ type: "TOGGLE_ADDON", addonId: addon.id })}
                        className="h-4 w-4 accent-stone-900"
                      />
                      <div>
                        <div className="text-sm font-medium text-stone-900">{addon.title}</div>
                        <div className="text-xs text-stone-500">پرداخت حضوری در کافه</div>
                      </div>
                    </div>
                    <span className="text-sm font-semibold text-stone-900">
                      {formatToman(addon.fee)}
                    </span>
                  </label>
                );
              })}
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
            <button
              type="button"
              onClick={() => dispatch({ type: "BACK_TO_SLOT" })}
              className="rounded-lg border border-stone-300 px-4 py-2 text-sm text-stone-700 hover:bg-stone-100"
            >
              بازگشت به انتخاب زمان
            </button>
            <button
              type="button"
              onClick={() => dispatch({ type: "PROCEED_TO_REVIEW" })}
              className="min-h-[44px] rounded-lg bg-stone-900 px-5 py-2.5 text-sm font-medium text-white hover:bg-stone-800"
            >
              ادامه به مرور و تایید
            </button>
          </div>
        </div>
      ) : null}

      {/* Step 4: Review & Confirm */}
      {state.step === "review" ? (
        <div className="space-y-4">
          <h3 className="text-sm font-semibold text-stone-800">۴. مرور اطلاعات و تایید رزرو</h3>

          <div className="space-y-2 rounded-lg border border-stone-200 bg-stone-50 p-4 text-sm">
            <div className="flex justify-between gap-2">
              <span className="text-stone-600">مجموعه:</span>
              <span className="font-medium text-stone-900">{venueName}</span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-stone-600">میز:</span>
              <span className="font-medium text-stone-900">
                {selectedPin.table_number} (ظرفیت {selectedPin.capacity} نفر)
              </span>
            </div>
            <div className="flex justify-between gap-2">
              <span className="text-stone-600">تاریخ و ساعت:</span>
              <span className="font-medium text-stone-900">
                {selectedSlotLabel ??
                  (state.slotStartIso
                    ? formatJalaliDate(state.slotStartIso, { includeTime: true })
                    : "")}
              </span>
            </div>

            <hr className="my-2 border-stone-200" />

            <div className="flex justify-between gap-2">
              <span className="text-stone-600">هزینه رزرو میز (پرداخت آنلاین):</span>
              <span className="font-semibold text-stone-900">
                {formatToman(summary.onlineTotalToman)}
              </span>
            </div>

            <div className="space-y-1">
              <div className="flex justify-between gap-2">
                <span className="text-stone-600">افزودنی‌ها (پرداخت حضوری در کافه):</span>
                <span className="font-medium text-stone-900">
                  {selectedAddons.length === 0
                    ? "بدون افزودنی — پرداخت حضوری در کافه"
                    : `${formatToman(summary.inPersonTotalToman)} (پرداخت حضوری در کافه)`}
                </span>
              </div>
              {selectedAddons.length > 0 ? (
                <ul className="space-y-1 pr-4 text-xs text-stone-600">
                  {selectedAddons.map((addon) => (
                    <li key={addon.id} className="flex justify-between">
                      <span>{addon.title}</span>
                      <span>{formatToman(addon.fee)}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>

            <hr className="my-2 border-stone-200" />

            <div className="flex justify-between gap-2 text-base font-bold text-stone-900">
              <span>مبلغ قابل پرداخت آنلاین همین الان:</span>
              <span>{formatToman(summary.onlineTotalToman)}</span>
            </div>
          </div>

          {submitError ? (
            <div
              role="alert"
              className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
            >
              {submitError}
            </div>
          ) : null}

          <div className="flex flex-wrap items-center justify-between gap-3">
            <button
              type="button"
              onClick={() => dispatch({ type: "BACK_TO_ADDONS" })}
              className="rounded-lg border border-stone-300 px-4 py-2 text-sm text-stone-700 hover:bg-stone-100"
            >
              بازگشت به افزودنی‌ها
            </button>
            <button
              type="button"
              disabled={submittingLock || authLoading}
              onClick={() => void handleConfirmAndLock()}
              className="min-h-[44px] rounded-lg bg-stone-900 px-5 py-2.5 text-sm font-medium text-white hover:bg-stone-800 disabled:opacity-50"
            >
              {submittingLock
                ? "در حال قفل کردن میز..."
                : !user
                  ? "ورود و تایید رزرو"
                  : "تایید و قفل موقت میز"}
            </button>
          </div>
        </div>
      ) : null}

      {/* Step 5: Locked / Paying / Failed */}
      {state.step === "locked" || state.step === "paying" || state.step === "failed" ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-emerald-200 bg-emerald-50 p-4">
            <div className="space-y-1">
              <h3 className="text-sm font-bold text-emerald-950">
                میز برای شما به‌صورت موقت قفل شد
              </h3>
              <p className="text-xs text-emerald-800">
                لطفاً پیش از پایان زمان باقی‌مانده، پرداخت آنلاین را تکمیل کنید.
              </p>
            </div>
            <div className="rounded-lg bg-white px-3 py-1.5 text-center shadow-xs">
              <div className="text-[11px] text-stone-500">زمان باقی‌مانده</div>
              <div dir="ltr" className="font-mono text-lg font-bold text-stone-900">
                {formatCountdownMmSs(remainingSeconds)}
              </div>
            </div>
          </div>

          <div className="space-y-2 rounded-lg border border-stone-200 bg-stone-50 p-4 text-sm">
            <div className="flex justify-between gap-2">
              <span className="text-stone-600">مبلغ قابل پرداخت آنلاین:</span>
              <span className="font-bold text-stone-900">
                {formatToman(state.amountOnlineToman ?? summary.onlineTotalToman)}
              </span>
            </div>
            <div className="flex justify-between gap-2 text-xs text-stone-600">
              <span>مبلغ پرداخت حضوری در کافه:</span>
              <span>
                {(state.amountInPersonToman ?? summary.inPersonTotalToman) > 0
                  ? `${formatToman(state.amountInPersonToman ?? summary.inPersonTotalToman)} (پرداخت حضوری در کافه)`
                  : "بدون افزودنی — پرداخت حضوری در کافه"}
              </span>
            </div>
          </div>

          {state.errorMessage ? (
            <div
              role="alert"
              className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
            >
              {state.errorMessage}
            </div>
          ) : null}

          <button
            type="button"
            disabled={submittingPayment || state.step === "paying" || remainingSeconds <= 0}
            onClick={() => void handleStartPayment()}
            className="min-h-[44px] w-full rounded-lg bg-stone-900 px-5 py-3 text-sm font-medium text-white hover:bg-stone-800 disabled:opacity-50"
          >
            {submittingPayment || state.step === "paying"
              ? "در حال انتقال به درگاه پرداخت..."
              : "پرداخت آنلاین (درگاه آزمایشی)"}
          </button>
        </div>
      ) : null}

      {/* Expired state */}
      {state.step === "expired" ? (
        <div className="space-y-4">
          <div
            role="alert"
            className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900"
          >
            <div className="font-semibold">زمان قفل رزرو به پایان رسید (۰۰:۰۰)</div>
            <p className="mt-1 text-xs">
              مهلت ۱۰ دقیقه‌ای پرداخت به اتمام رسیده و میز آزاد شده است. برای رزرو مجدد، زمان مورد
              نظر را دوباره انتخاب کنید.
            </p>
          </div>
          <button
            type="button"
            onClick={handleRestartBooking}
            className="min-h-[44px] rounded-lg bg-stone-900 px-5 py-2.5 text-sm font-medium text-white hover:bg-stone-800"
          >
            شروع مجدد رزرو
          </button>
        </div>
      ) : null}
    </section>
  );
}
