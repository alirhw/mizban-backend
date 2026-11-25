"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useEffect, useMemo, useState } from "react";

import { OwnerForbidden } from "@/components/OwnerForbidden";
import {
  ApiError,
  createPinBlockedSlot,
  deleteBlockedSlot,
  getOwnerVenue,
  getOwnerVenueSubscription,
  listOwnerVenueBookings,
  listOwnerVenueSpaces,
  listPinBlockedSlots,
  listSpaceTablePins,
  listVenueSlots,
  updateTablePin,
  type BlockedSlotOut,
  type OwnerBookingOut,
  type SlotOut,
  type SpaceOut,
  type TablePinOut,
  type VenueOwnerOut,
  type VenueSubscriptionOut,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatJalaliDate, formatJalaliFromIsoDate, getTehranDateIso } from "@/lib/jalali";
import {
  formatMaskedPhone,
  getBookingStatusLabel,
  getPanoramaStatusLabel,
  getSubscriptionBadge,
  isForbiddenError,
  validateBlockedSlotInput,
} from "@/lib/owner";
import { formatToman } from "@/lib/panorama";

export interface OwnerVenueDashboardProps {
  venueId: number;
}

export function OwnerVenueDashboard({ venueId }: OwnerVenueDashboardProps) {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const isOwnerRole = user?.role === "VENUE_OWNER" || user?.role === "ADMIN";

  const [loadedVenueId, setLoadedVenueId] = useState<number | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [notFoundError, setNotFoundError] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const loading = Boolean(
    user && isOwnerRole && loadedVenueId !== venueId && !forbidden && !notFoundError && !loadError
  );

  const [venue, setVenue] = useState<VenueOwnerOut | null>(null);
  const [subscription, setSubscription] = useState<VenueSubscriptionOut | null>(null);
  const [spaces, setSpaces] = useState<SpaceOut[]>([]);
  const [pins, setPins] = useState<TablePinOut[]>([]);
  const [bookings, setBookings] = useState<OwnerBookingOut[]>([]);

  // Section (b): Pin edit state
  const [editingPinId, setEditingPinId] = useState<number | null>(null);
  const [editFee, setEditFee] = useState<string>("");
  const [editCapacity, setEditCapacity] = useState<string>("");
  const [editSmoking, setEditSmoking] = useState<boolean>(false);
  const [savingPin, setSavingPin] = useState(false);
  const [pinError, setPinError] = useState<string | null>(null);
  const [pinSuccess, setPinSuccess] = useState<string | null>(null);

  // Section (c): BlockedSlot manager state
  const dateOptions = useMemo(
    () => Array.from({ length: 14 }, (_, idx) => getTehranDateIso(idx)),
    []
  );
  const [selectedPinId, setSelectedPinId] = useState<number | null>(null);
  const [selectedDate, setSelectedDate] = useState<string>(() => getTehranDateIso(1));
  const [scheduleRefreshNonce, setScheduleRefreshNonce] = useState(0);
  const currentScheduleKey =
    selectedPinId !== null ? `${selectedPinId}:${selectedDate}:${scheduleRefreshNonce}` : "";
  const [scheduleState, setScheduleState] = useState<{
    key: string;
    slots: SlotOut[];
    blocks: BlockedSlotOut[];
    fetchError: string | null;
  }>({
    key: "",
    slots: [],
    blocks: [],
    fetchError: null,
  });
  const loadingSchedule = Boolean(
    selectedPinId !== null && venue && scheduleState.key !== currentScheduleKey
  );
  const daySlots = scheduleState.key === currentScheduleKey ? scheduleState.slots : [];
  const blockedSlots = scheduleState.key === currentScheduleKey ? scheduleState.blocks : [];
  const [blockReason, setBlockReason] = useState<string>("");
  const [blockError, setBlockError] = useState<string | null>(null);
  const [blockSuccess, setBlockSuccess] = useState<string | null>(null);
  const [mutatingBlockKey, setMutatingBlockKey] = useState<string | null>(null);

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      router.replace(`/login?next=${encodeURIComponent(`/owner/venues/${venueId}`)}`);
      return;
    }
    if (!isOwnerRole) return;

    let active = true;
    Promise.all([
      getOwnerVenue(venueId),
      getOwnerVenueSubscription(venueId),
      listOwnerVenueSpaces(venueId),
      listOwnerVenueBookings(venueId),
    ])
      .then(async ([venueData, subData, spaceList, bookingList]) => {
        const pinLists = await Promise.all(
          spaceList.map((space) => listSpaceTablePins(space.id).catch(() => [] as TablePinOut[]))
        );
        if (!active) return;
        const flatPins = pinLists.flat();

        setVenue(venueData);
        setSubscription(subData);
        setSpaces(spaceList);
        setPins(flatPins);
        setBookings(bookingList);
        setSelectedPinId((prev) =>
          prev && flatPins.some((p) => p.id === prev) ? prev : (flatPins[0]?.id ?? null)
        );
        setLoadError(null);
        setForbidden(false);
        setNotFoundError(false);
        setLoadedVenueId(venueId);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof ApiError && err.status === 401) {
          router.replace(`/login?next=${encodeURIComponent(`/owner/venues/${venueId}`)}`);
          return;
        }
        if (isForbiddenError(err)) {
          setForbidden(true);
          return;
        }
        if (err instanceof ApiError && err.status === 404) {
          setNotFoundError(true);
          return;
        }
        setLoadError("دریافت اطلاعات مجموعه با خطا مواجه شد.");
      });

    return () => {
      active = false;
    };
  }, [authLoading, user, isOwnerRole, venueId, router]);

  useEffect(() => {
    if (selectedPinId === null || !venue) return;
    let active = true;
    const reqKey = currentScheduleKey;

    Promise.all([
      listVenueSlots(venueId, { date: selectedDate, table_pin_id: selectedPinId }),
      listPinBlockedSlots(selectedPinId),
    ])
      .then(([slotsRes, blocksRes]) => {
        if (!active) return;
        setScheduleState({ key: reqKey, slots: slotsRes, blocks: blocksRes, fetchError: null });
      })
      .catch(() => {
        if (!active) return;
        setScheduleState({
          key: reqKey,
          slots: [],
          blocks: [],
          fetchError: "دریافت وضعیت اسلات‌های این روز با خطا مواجه شد.",
        });
      });

    return () => {
      active = false;
    };
  }, [selectedPinId, selectedDate, venue, venueId, currentScheduleKey]);

  function startEditPin(pin: TablePinOut) {
    setEditingPinId(pin.id);
    setEditFee(String(pin.reservation_fee_toman));
    setEditCapacity(String(pin.capacity));
    setEditSmoking(pin.is_smoking);
    setPinError(null);
    setPinSuccess(null);
  }

  async function handleSavePin(pinId: number) {
    const parsedFee = Number(editFee);
    const parsedCapacity = Number(editCapacity);
    if (!Number.isInteger(parsedFee) || parsedFee < 0) {
      setPinError("هزینه رزرو باید عدد صحیح نامنفی باشد.");
      return;
    }
    if (!Number.isInteger(parsedCapacity) || parsedCapacity < 1) {
      setPinError("ظرفیت میز باید حداقل ۱ نفر باشد.");
      return;
    }

    setSavingPin(true);
    setPinError(null);
    setPinSuccess(null);
    try {
      const updated = await updateTablePin(pinId, {
        reservation_fee_toman: parsedFee,
        capacity: parsedCapacity,
        is_smoking: editSmoking,
      });
      setPins((prev) => prev.map((p) => (p.id === pinId ? updated : p)));
      setEditingPinId(null);
      setPinSuccess(`تغییرات میز «${updated.table_number}» ذخیره شد.`);
    } catch {
      setPinError("ذخیره تغییرات میز با خطا مواجه شد.");
    } finally {
      setSavingPin(false);
    }
  }

  async function handleBlockSlot(slotStartIso: string) {
    if (selectedPinId === null || !venue) return;
    setBlockError(null);
    setBlockSuccess(null);

    const validation = validateBlockedSlotInput(slotStartIso, venue.operating_hours);
    if (!validation.valid) {
      setBlockError(validation.error);
      return;
    }

    setMutatingBlockKey(slotStartIso);
    try {
      await createPinBlockedSlot(selectedPinId, {
        start_at: slotStartIso,
        reason: blockReason.trim(),
      });
      setBlockReason("");
      setBlockSuccess("اسلات انتخاب‌شده با موفقیت مسدود شد.");
      setScheduleRefreshNonce((prev) => prev + 1);
    } catch (err) {
      if (err instanceof ApiError && err.message) {
        setBlockError(
          "مسدودسازی این اسلات امکان‌پذیر نیست (ممکن است رزرو یا قبلاً مسدود شده باشد)."
        );
      } else {
        setBlockError("مسدودسازی اسلات با خطا مواجه شد.");
      }
    } finally {
      setMutatingBlockKey(null);
    }
  }

  async function handleUnblockSlot(blockId: number) {
    if (selectedPinId === null) return;
    setBlockError(null);
    setBlockSuccess(null);
    setMutatingBlockKey(`del-${blockId}`);
    try {
      await deleteBlockedSlot(blockId);
      setBlockSuccess("مسدودیت اسلات برداشته شد.");
      setScheduleRefreshNonce((prev) => prev + 1);
    } catch {
      setBlockError("حذف مسدودیت اسلات با خطا مواجه شد.");
    } finally {
      setMutatingBlockKey(null);
    }
  }

  if (authLoading || (!user && !authLoading)) {
    return (
      <div className="space-y-4">
        <div className="h-10 w-64 animate-pulse rounded bg-stone-200" />
        <div className="h-48 animate-pulse rounded-xl bg-stone-200" />
      </div>
    );
  }

  if (!isOwnerRole || forbidden) {
    return <OwnerForbidden />;
  }

  if (notFoundError) {
    return (
      <div className="mx-auto max-w-lg space-y-4 rounded-xl border border-stone-200 bg-white p-6">
        <h1 className="text-lg font-bold text-stone-900">مجموعه یافت نشد</h1>
        <Link href="/owner" className="text-sm font-medium text-stone-700 underline">
          بازگشت به فهرست مجموعه‌ها
        </Link>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="space-y-4">
        <div className="h-10 w-64 animate-pulse rounded bg-stone-200" />
        <div className="h-48 animate-pulse rounded-xl bg-stone-200" />
        <div className="h-48 animate-pulse rounded-xl bg-stone-200" />
      </div>
    );
  }

  if (loadError || !venue) {
    return (
      <div
        role="alert"
        className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-900"
      >
        {loadError ?? "بارگذاری داشبورد ناموفق بود."}
      </div>
    );
  }

  const subBadge = subscription ? getSubscriptionBadge(subscription) : null;
  const blockedByStartMs = new Map<number, BlockedSlotOut>();
  for (const b of blockedSlots) {
    blockedByStartMs.set(Date.parse(b.start_at), b);
  }
  const dayBlocks = blockedSlots.filter((b) => {
    const tehranDate = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Tehran",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date(b.start_at));
    return tehranDate === selectedDate;
  });

  return (
    <section className="space-y-8">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4 rounded-xl border border-stone-200 bg-white p-5">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-bold text-stone-900">{venue.name}</h1>
            <span
              className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
                venue.is_approved
                  ? "bg-emerald-100 text-emerald-900"
                  : "bg-stone-100 text-stone-700"
              }`}
            >
              {venue.is_approved ? "تایید شده" : "در انتظار تایید"}
            </span>
          </div>
          <p className="text-sm text-stone-600">
            {venue.city} — {venue.address}
          </p>
        </div>

        <Link
          href="/owner"
          className="text-sm font-medium text-stone-700 underline hover:text-stone-900"
        >
          بازگشت به مجموعه‌های من
        </Link>
      </div>

      {/* (d) Read-only Subscription Card */}
      <div className="rounded-xl border border-stone-200 bg-white p-5 space-y-3">
        <h2 className="text-lg font-bold text-stone-900">وضعیت اشتراک (فقط نمایش)</h2>
        {subscription && subBadge ? (
          <div className="grid gap-3 text-sm sm:grid-cols-4">
            <div className="rounded-lg bg-stone-50 p-3">
              <div className="text-xs text-stone-500">وضعیت</div>
              <div className="mt-1 font-bold text-stone-900">
                {subscription.is_active ? "ACTIVE" : "INACTIVE"} ({subBadge.label})
              </div>
            </div>
            <div className="rounded-lg bg-stone-50 p-3">
              <div className="text-xs text-stone-500">طرح</div>
              <div className="mt-1 font-medium text-stone-900">
                {subscription.plan_name ?? "بدون طرح"}
              </div>
            </div>
            <div className="rounded-lg bg-stone-50 p-3">
              <div className="text-xs text-stone-500">روزهای باقی‌مانده</div>
              <div className="mt-1 font-medium text-stone-900">{subBadge.detail}</div>
            </div>
            <div className="rounded-lg bg-stone-50 p-3">
              <div className="text-xs text-stone-500">تاریخ انقضا</div>
              <div className="mt-1 font-medium text-stone-900">
                {subscription.jalali_expires_at ?? "—"}
              </div>
            </div>
          </div>
        ) : (
          <p className="text-sm text-stone-500">اطلاعات اشتراک در دسترس نیست.</p>
        )}
      </div>

      {/* (a) Spaces & Panorama Status */}
      <div className="rounded-xl border border-stone-200 bg-white p-5 space-y-3">
        <h2 className="text-lg font-bold text-stone-900">فضاها و وضعیت پانوراما ۳۶۰ درجه</h2>
        {spaces.length === 0 ? (
          <p className="text-sm text-stone-500">هنوز فضایی برای این مجموعه ثبت نشده است.</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {spaces.map((space) => (
              <div
                key={space.id}
                className="flex items-center justify-between rounded-lg border border-stone-200 p-3 text-sm"
              >
                <div>
                  <div className="font-semibold text-stone-900">{space.name}</div>
                  <div className="text-xs text-stone-500">
                    {space.is_active ? "فعال" : "غیرفعال"}
                  </div>
                </div>
                <span
                  className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
                    space.panorama_status === "READY"
                      ? "bg-emerald-100 text-emerald-900"
                      : space.panorama_status === "FAILED"
                        ? "bg-red-100 text-red-900"
                        : "bg-stone-100 text-stone-700"
                  }`}
                >
                  {getPanoramaStatusLabel(space.panorama_status)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* (b) Table Pins Manager (Edit only) */}
      <div className="rounded-xl border border-stone-200 bg-white p-5 space-y-4">
        <h2 className="text-lg font-bold text-stone-900">مدیریت میزها (ویرایش تعرفه و ظرفیت)</h2>
        {pinError ? (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-800">
            {pinError}
          </div>
        ) : null}
        {pinSuccess ? (
          <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800">
            {pinSuccess}
          </div>
        ) : null}

        {pins.length === 0 ? (
          <p className="text-sm text-stone-500">هنوز میزی برای این مجموعه ثبت نشده است.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-right text-sm">
              <thead>
                <tr className="border-b border-stone-200 text-xs text-stone-500">
                  <th className="py-2 pl-3">شماره میز</th>
                  <th className="py-2 pl-3">ظرفیت</th>
                  <th className="py-2 pl-3">هزینه رزرو آنلاین</th>
                  <th className="py-2 pl-3">دخانیات</th>
                  <th className="py-2">عملیات</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {pins.map((pin) => {
                  const isEditing = editingPinId === pin.id;
                  return (
                    <tr key={pin.id}>
                      <td className="py-3 pl-3 font-medium text-stone-900">{pin.table_number}</td>
                      <td className="py-3 pl-3">
                        {isEditing ? (
                          <input
                            type="number"
                            min={1}
                            value={editCapacity}
                            onChange={(e) => setEditCapacity(e.target.value)}
                            aria-label={`ظرفیت ${pin.table_number}`}
                            className="w-20 rounded border border-stone-300 px-2 py-1 text-sm"
                          />
                        ) : (
                          `${pin.capacity} نفر`
                        )}
                      </td>
                      <td className="py-3 pl-3">
                        {isEditing ? (
                          <input
                            type="number"
                            min={0}
                            step={1000}
                            value={editFee}
                            onChange={(e) => setEditFee(e.target.value)}
                            aria-label={`هزینه رزرو ${pin.table_number}`}
                            className="w-32 rounded border border-stone-300 px-2 py-1 text-sm"
                          />
                        ) : (
                          formatToman(pin.reservation_fee_toman)
                        )}
                      </td>
                      <td className="py-3 pl-3">
                        {isEditing ? (
                          <label className="inline-flex items-center gap-1.5 text-xs">
                            <input
                              type="checkbox"
                              checked={editSmoking}
                              onChange={(e) => setEditSmoking(e.target.checked)}
                            />
                            سیگار آزاد
                          </label>
                        ) : pin.is_smoking ? (
                          "آزاد"
                        ) : (
                          "ممنوع"
                        )}
                      </td>
                      <td className="py-3">
                        {isEditing ? (
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              disabled={savingPin}
                              onClick={() => void handleSavePin(pin.id)}
                              className="rounded bg-stone-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-stone-800 disabled:opacity-50"
                            >
                              {savingPin ? "در حال ذخیره..." : "ذخیره"}
                            </button>
                            <button
                              type="button"
                              onClick={() => setEditingPinId(null)}
                              className="rounded border border-stone-300 px-3 py-1.5 text-xs text-stone-700"
                            >
                              انصراف
                            </button>
                          </div>
                        ) : (
                          <button
                            type="button"
                            onClick={() => startEditPin(pin)}
                            className="rounded border border-stone-300 px-3 py-1.5 text-xs font-medium text-stone-800 hover:bg-stone-100"
                          >
                            ویرایش
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* (c) BlockedSlot Manager */}
      <div className="rounded-xl border border-stone-200 bg-white p-5 space-y-4">
        <div className="space-y-1">
          <h2 className="text-lg font-bold text-stone-900">مسدودسازی اسلات‌ها (BlockedSlot)</h2>
          <p className="text-xs text-stone-500">
            دلیل مسدودسازی فقط برای مالک قابل مشاهده است و هرگز به مشتریان نمایش داده نمی‌شود.
          </p>
        </div>

        {pins.length === 0 ? (
          <p className="text-sm text-stone-500">ابتدا باید میزی برای مجموعه تعریف شده باشد.</p>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-3">
              <div>
                <label className="mb-1 block text-xs font-medium text-stone-700">انتخاب میز</label>
                <select
                  value={selectedPinId ?? ""}
                  onChange={(e) => setSelectedPinId(Number(e.target.value))}
                  className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
                >
                  {pins.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.table_number}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium text-stone-700">
                  تاریخ (جلالی)
                </label>
                <select
                  value={selectedDate}
                  onChange={(e) => setSelectedDate(e.target.value)}
                  className="w-full rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm"
                >
                  {dateOptions.map((d) => (
                    <option key={d} value={d}>
                      {formatJalaliFromIsoDate(d)}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium text-stone-700">
                  دلیل مسدودسازی (اختیاری و محرمانه)
                </label>
                <input
                  type="text"
                  maxLength={255}
                  value={blockReason}
                  onChange={(e) => setBlockReason(e.target.value)}
                  placeholder="مثلاً: رزرو خصوصی یا تعمیرات"
                  className="w-full rounded-lg border border-stone-300 px-3 py-2 text-sm"
                />
              </div>
            </div>

            {blockError || scheduleState.fetchError ? (
              <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-800">
                {blockError ?? scheduleState.fetchError}
              </div>
            ) : null}
            {blockSuccess ? (
              <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800">
                {blockSuccess}
              </div>
            ) : null}

            {loadingSchedule ? (
              <p className="text-sm text-stone-500">در حال بارگذاری اسلات‌ها...</p>
            ) : (
              <div className="space-y-4">
                {dayBlocks.length > 0 ? (
                  <div className="space-y-2">
                    <h3 className="text-sm font-semibold text-stone-800">
                      اسلات‌های مسدودشده این روز
                    </h3>
                    <div className="grid gap-2 sm:grid-cols-2">
                      {dayBlocks.map((block) => (
                        <div
                          key={block.id}
                          className="flex items-center justify-between rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs"
                        >
                          <div>
                            <div className="font-semibold text-amber-950">
                              {block.jalali_start_at}
                            </div>
                            {block.reason ? (
                              <div className="text-amber-800">دلیل: {block.reason}</div>
                            ) : null}
                          </div>
                          <button
                            type="button"
                            disabled={mutatingBlockKey === `del-${block.id}`}
                            onClick={() => void handleUnblockSlot(block.id)}
                            className="rounded bg-white px-3 py-1.5 font-medium text-red-700 border border-red-200 hover:bg-red-50 disabled:opacity-50"
                          >
                            {mutatingBlockKey === `del-${block.id}`
                              ? "در حال حذف..."
                              : "رفع مسدودیت"}
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}

                {daySlots.length === 0 ? (
                  <p className="text-sm text-stone-500">
                    هیچ اسلات فعالی برای این تاریخ و میز باقی نمانده است.
                  </p>
                ) : (
                  <div className="grid gap-2 sm:grid-cols-3">
                    {daySlots.map((slot) => {
                      const existingBlock = blockedByStartMs.get(Date.parse(slot.start));
                      return (
                        <div
                          key={slot.start}
                          className="flex items-center justify-between rounded-lg border border-stone-200 p-3 text-xs"
                        >
                          <div>
                            <div className="font-semibold text-stone-900">
                              {slot.start_jalali} تا {slot.end_jalali}
                            </div>
                            <div className="text-stone-500">
                              {existingBlock ? "مسدود شده" : "آزاد در دسترس"}
                            </div>
                          </div>
                          {existingBlock ? (
                            <button
                              type="button"
                              disabled={mutatingBlockKey === `del-${existingBlock.id}`}
                              onClick={() => void handleUnblockSlot(existingBlock.id)}
                              className="rounded border border-red-200 px-2.5 py-1.5 font-medium text-red-700 hover:bg-red-50"
                            >
                              رفع مسدودیت
                            </button>
                          ) : (
                            <button
                              type="button"
                              disabled={mutatingBlockKey === slot.start}
                              onClick={() => void handleBlockSlot(slot.start)}
                              className="rounded bg-stone-900 px-2.5 py-1.5 font-medium text-white hover:bg-stone-800 disabled:opacity-50"
                            >
                              {mutatingBlockKey === slot.start ? "در حال ثبت..." : "مسدود کن"}
                            </button>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>

      {/* (e) Bookings Overview (Read-only, masked phone, no money actions) */}
      <div className="rounded-xl border border-stone-200 bg-white p-5 space-y-4">
        <h2 className="text-lg font-bold text-stone-900">نمای کلی رزروها</h2>
        {bookings.length === 0 ? (
          <p className="text-sm text-stone-500">هنوز رزروی برای این مجموعه ثبت نشده است.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-right text-sm">
              <thead>
                <tr className="border-b border-stone-200 text-xs text-stone-500">
                  <th className="py-2 pl-3">شناسه</th>
                  <th className="py-2 pl-3">وضعیت</th>
                  <th className="py-2 pl-3">میز</th>
                  <th className="py-2 pl-3">تاریخ و ساعت (جلالی)</th>
                  <th className="py-2 pl-3">پرداخت آنلاین</th>
                  <th className="py-2 pl-3">پرداخت حضوری</th>
                  <th className="py-2">شماره مشتری</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {bookings.map((b) => (
                  <tr key={b.booking_id}>
                    <td className="py-3 pl-3 font-medium text-stone-900">#{b.booking_id}</td>
                    <td className="py-3 pl-3 text-xs font-medium text-stone-800">
                      {getBookingStatusLabel(b.status)}
                    </td>
                    <td className="py-3 pl-3">{b.table_number}</td>
                    <td className="py-3 pl-3 text-xs text-stone-700">
                      {b.start_jalali || formatJalaliDate(b.start_at, { includeTime: true })}
                    </td>
                    <td className="py-3 pl-3">{formatToman(b.amount_online_toman)}</td>
                    <td className="py-3 pl-3">{formatToman(b.amount_in_person_toman)}</td>
                    <td className="py-3 text-xs font-mono text-stone-700" dir="ltr">
                      {formatMaskedPhone(b.customer_phone_masked)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
