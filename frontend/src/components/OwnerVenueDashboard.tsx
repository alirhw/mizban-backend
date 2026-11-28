"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useEffect, useMemo, useState } from "react";

import { OwnerForbidden } from "@/components/OwnerForbidden";
import {
  ApiError,
  createPinBlockedSlot,
  createVenueAddon,
  deleteBlockedSlot,
  deleteVenueAddon,
  getOwnerVenue,
  getOwnerVenueSubscription,
  listOwnerVenueBookings,
  listOwnerVenueSpaces,
  listPinBlockedSlots,
  listSpaceTablePins,
  listVenueAddons,
  listVenueSlots,
  updateTablePin,
  updateVenueAddon,
  type BlockedSlotOut,
  type DesignAddonOut,
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

function validateAddonInput(
  titleInput: string,
  feeInput: string
): { valid: true; title: string; fee: number } | { valid: false; error: string } {
  const title = titleInput.trim();
  if (!title) {
    return { valid: false, error: "عنوان افزودنی طراحی الزامی است." };
  }
  if (title.length > 200) {
    return { valid: false, error: "عنوان افزودنی طراحی نباید بیش از ۲۰۰ کاراکتر باشد." };
  }
  const trimmedFee = feeInput.trim();
  if (!/^\d+$/.test(trimmedFee)) {
    return { valid: false, error: "هزینه افزودنی باید عدد صحیح نامنفی (به تومان) باشد." };
  }
  const fee = Number(trimmedFee);
  if (!Number.isSafeInteger(fee) || fee < 0) {
    return { valid: false, error: "هزینه افزودنی باید عدد صحیح نامنفی (به تومان) باشد." };
  }
  return { valid: true, title, fee };
}

function mapAddonErrorToPersian(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 409 || err.errorCode === "ADDON_IN_USE") {
      return "این افزودنی در رزروهای ثبت‌شده استفاده شده و قابل حذف نیست؛ می‌توانید آن را غیرفعال کنید.";
    }
    if (err.errorCode === "VALIDATION_ERROR") {
      return "اطلاعات واردشده معتبر نیست؛ لطفاً عنوان و هزینه را بررسی کنید.";
    }
    if (err.status === 403 || err.errorCode === "FORBIDDEN") {
      return "شما دسترسی لازم برای مدیریت افزودنی‌های این مجموعه را ندارید.";
    }
    if (err.status === 404 || err.errorCode === "NOT_FOUND") {
      return "افزودنی مورد نظر یافت نشد.";
    }
  }
  return fallback;
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
  const [addons, setAddons] = useState<DesignAddonOut[]>([]);
  const [bookings, setBookings] = useState<OwnerBookingOut[]>([]);

  // Section (b): Pin edit state
  const [editingPinId, setEditingPinId] = useState<number | null>(null);
  const [editFee, setEditFee] = useState<string>("");
  const [editCapacity, setEditCapacity] = useState<string>("");
  const [editSmoking, setEditSmoking] = useState<boolean>(false);
  const [savingPin, setSavingPin] = useState(false);
  const [pinError, setPinError] = useState<string | null>(null);
  const [pinSuccess, setPinSuccess] = useState<string | null>(null);

  // Section (b2): Design add-ons manager state
  const [showCreateAddon, setShowCreateAddon] = useState(false);
  const [newAddonTitle, setNewAddonTitle] = useState("");
  const [newAddonFee, setNewAddonFee] = useState("");
  const [newAddonActive, setNewAddonActive] = useState(true);
  const [creatingAddon, setCreatingAddon] = useState(false);
  const [editingAddonId, setEditingAddonId] = useState<number | null>(null);
  const [editAddonTitle, setEditAddonTitle] = useState("");
  const [editAddonFee, setEditAddonFee] = useState("");
  const [editAddonActive, setEditAddonActive] = useState(true);
  const [savingAddon, setSavingAddon] = useState(false);
  const [confirmDeleteAddonId, setConfirmDeleteAddonId] = useState<number | null>(null);
  const [deletingAddonId, setDeletingAddonId] = useState<number | null>(null);
  const [inUseAddonId, setInUseAddonId] = useState<number | null>(null);
  const [addonError, setAddonError] = useState<string | null>(null);
  const [addonSuccess, setAddonSuccess] = useState<string | null>(null);

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
      listVenueAddons(venueId),
    ])
      .then(async ([venueData, subData, spaceList, bookingList, addonList]) => {
        const pinLists = await Promise.all(
          spaceList.map((space) => listSpaceTablePins(space.id).catch(() => [] as TablePinOut[]))
        );
        if (!active) return;
        const flatPins = pinLists.flat();

        setVenue(venueData);
        setSubscription(subData);
        setSpaces(spaceList);
        setPins(flatPins);
        setAddons(addonList);
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

  function startEditAddon(addon: DesignAddonOut) {
    setEditingAddonId(addon.id);
    setEditAddonTitle(addon.title);
    setEditAddonFee(String(addon.fee));
    setEditAddonActive(addon.is_active);
    setConfirmDeleteAddonId(null);
    setInUseAddonId(null);
    setAddonError(null);
    setAddonSuccess(null);
  }

  async function handleCreateAddon(e: React.FormEvent) {
    e.preventDefault();
    setAddonError(null);
    setAddonSuccess(null);
    const validation = validateAddonInput(newAddonTitle, newAddonFee);
    if (!validation.valid) {
      setAddonError(validation.error);
      return;
    }

    setCreatingAddon(true);
    try {
      const created = await createVenueAddon(venueId, {
        title: validation.title,
        fee: validation.fee,
        is_active: newAddonActive,
      });
      const refreshed = await listVenueAddons(venueId).catch(() =>
        [...addons, created].sort((a, b) => a.title.localeCompare(b.title))
      );
      setAddons(refreshed);
      setNewAddonTitle("");
      setNewAddonFee("");
      setNewAddonActive(true);
      setShowCreateAddon(false);
      setAddonSuccess(`افزودنی «${created.title}» با موفقیت ایجاد شد.`);
    } catch (err) {
      setAddonError(mapAddonErrorToPersian(err, "ایجاد افزودنی طراحی با خطا مواجه شد."));
    } finally {
      setCreatingAddon(false);
    }
  }

  async function handleSaveAddon(addonId: number) {
    setAddonError(null);
    setAddonSuccess(null);
    const validation = validateAddonInput(editAddonTitle, editAddonFee);
    if (!validation.valid) {
      setAddonError(validation.error);
      return;
    }

    setSavingAddon(true);
    try {
      const updated = await updateVenueAddon(venueId, addonId, {
        title: validation.title,
        fee: validation.fee,
        is_active: editAddonActive,
      });
      setAddons((prev) => prev.map((a) => (a.id === addonId ? updated : a)));
      setEditingAddonId(null);
      setInUseAddonId(null);
      setAddonSuccess(`تغییرات افزودنی «${updated.title}» ذخیره شد.`);
    } catch (err) {
      setAddonError(mapAddonErrorToPersian(err, "ذخیره تغییرات افزودنی با خطا مواجه شد."));
    } finally {
      setSavingAddon(false);
    }
  }

  async function handleDeleteAddon(addon: DesignAddonOut) {
    setAddonError(null);
    setAddonSuccess(null);
    setInUseAddonId(null);
    setDeletingAddonId(addon.id);
    try {
      await deleteVenueAddon(venueId, addon.id);
      setAddons((prev) => prev.filter((a) => a.id !== addon.id));
      setConfirmDeleteAddonId(null);
      setAddonSuccess(`افزودنی «${addon.title}» حذف شد.`);
    } catch (err) {
      setConfirmDeleteAddonId(null);
      if (err instanceof ApiError && (err.status === 409 || err.errorCode === "ADDON_IN_USE")) {
        setInUseAddonId(addon.id);
      }
      setAddonError(mapAddonErrorToPersian(err, "حذف افزودنی طراحی با خطا مواجه شد."));
    } finally {
      setDeletingAddonId(null);
    }
  }

  async function handleDeactivateAddon(addon: DesignAddonOut) {
    setAddonError(null);
    setAddonSuccess(null);
    setSavingAddon(true);
    try {
      const updated = await updateVenueAddon(venueId, addon.id, {
        title: addon.title,
        fee: addon.fee,
        is_active: false,
      });
      setAddons((prev) => prev.map((a) => (a.id === addon.id ? updated : a)));
      setInUseAddonId(null);
      setAddonSuccess(`افزودنی «${updated.title}» غیرفعال شد.`);
    } catch (err) {
      setAddonError(mapAddonErrorToPersian(err, "غیرفعال‌سازی افزودنی با خطا مواجه شد."));
    } finally {
      setSavingAddon(false);
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

      {/* (b2) Design Add-ons Manager */}
      <div className="rounded-xl border border-stone-200 bg-white p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-bold text-stone-900">مدیریت افزودنی‌های طراحی</h2>
          {!showCreateAddon ? (
            <button
              type="button"
              onClick={() => {
                setShowCreateAddon(true);
                setAddonError(null);
                setAddonSuccess(null);
              }}
              className="rounded-lg bg-stone-900 px-3.5 py-2 text-xs font-medium text-white hover:bg-stone-800"
            >
              افزودن افزودنی جدید
            </button>
          ) : null}
        </div>

        {addonError ? (
          <div
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-800"
          >
            {addonError}
          </div>
        ) : null}
        {addonSuccess ? (
          <div
            role="status"
            className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800"
          >
            {addonSuccess}
          </div>
        ) : null}

        {showCreateAddon ? (
          <form
            onSubmit={(e) => void handleCreateAddon(e)}
            className="rounded-lg border border-stone-200 bg-stone-50 p-4 space-y-3"
          >
            <div className="grid gap-3 sm:grid-cols-3">
              <div>
                <label className="mb-1 block text-xs font-medium text-stone-700">
                  عنوان افزودنی
                </label>
                <input
                  type="text"
                  maxLength={200}
                  value={newAddonTitle}
                  onChange={(e) => setNewAddonTitle(e.target.value)}
                  aria-label="عنوان افزودنی جدید"
                  placeholder="مثلاً گل‌آرایی میز"
                  className="w-full rounded border border-stone-300 bg-white px-2.5 py-1.5 text-sm"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-stone-700">
                  هزینه (تومان)
                </label>
                <input
                  type="text"
                  inputMode="numeric"
                  value={newAddonFee}
                  onChange={(e) => setNewAddonFee(e.target.value)}
                  aria-label="هزینه افزودنی جدید"
                  placeholder="مثلاً 150000"
                  className="w-full rounded border border-stone-300 bg-white px-2.5 py-1.5 text-sm"
                />
              </div>
              <div className="flex items-end pb-1.5">
                <label className="inline-flex items-center gap-2 text-xs text-stone-700">
                  <input
                    type="checkbox"
                    checked={newAddonActive}
                    onChange={(e) => setNewAddonActive(e.target.checked)}
                    aria-label="وضعیت فعال افزودنی جدید"
                  />
                  فعال برای انتخاب مشتری
                </label>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="submit"
                disabled={creatingAddon}
                className="rounded-lg bg-stone-900 px-4 py-2 text-xs font-medium text-white hover:bg-stone-800 disabled:opacity-50"
              >
                {creatingAddon ? "در حال ثبت..." : "ثبت افزودنی"}
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowCreateAddon(false);
                  setAddonError(null);
                }}
                className="rounded-lg border border-stone-300 px-4 py-2 text-xs text-stone-700"
              >
                انصراف
              </button>
            </div>
          </form>
        ) : null}

        {addons.length === 0 ? (
          <div className="space-y-2 py-2">
            <p className="text-sm text-stone-500">
              هنوز افزودنی طراحی برای این مجموعه ثبت نشده است.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-right text-sm">
              <thead>
                <tr className="border-b border-stone-200 text-xs text-stone-500">
                  <th className="py-2 pl-3">عنوان</th>
                  <th className="py-2 pl-3">هزینه (پرداخت در محل)</th>
                  <th className="py-2 pl-3">وضعیت</th>
                  <th className="py-2">عملیات</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                {addons.map((addon) => {
                  const isEditing = editingAddonId === addon.id;
                  const isConfirmingDelete = confirmDeleteAddonId === addon.id;
                  const isInUse = inUseAddonId === addon.id;
                  return (
                    <tr key={addon.id}>
                      <td className="py-3 pl-3 font-medium text-stone-900">
                        {isEditing ? (
                          <div className="space-y-1">
                            <input
                              type="text"
                              maxLength={200}
                              value={editAddonTitle}
                              onChange={(e) => setEditAddonTitle(e.target.value)}
                              aria-label={`عنوان ${addon.title}`}
                              className="w-44 rounded border border-stone-300 px-2 py-1 text-sm"
                            />
                            <p className="text-[11px] text-stone-500">
                              تغییر هزینه فقط برای رزروهای آینده اعمال می‌شود و مبلغ رزروهای قبلی
                              تغییر نمی‌کند.
                            </p>
                          </div>
                        ) : (
                          addon.title
                        )}
                      </td>
                      <td className="py-3 pl-3">
                        {isEditing ? (
                          <input
                            type="text"
                            inputMode="numeric"
                            value={editAddonFee}
                            onChange={(e) => setEditAddonFee(e.target.value)}
                            aria-label={`هزینه ${addon.title}`}
                            className="w-32 rounded border border-stone-300 px-2 py-1 text-sm"
                          />
                        ) : (
                          formatToman(addon.fee)
                        )}
                      </td>
                      <td className="py-3 pl-3">
                        {isEditing ? (
                          <label className="inline-flex items-center gap-1.5 text-xs">
                            <input
                              type="checkbox"
                              checked={editAddonActive}
                              onChange={(e) => setEditAddonActive(e.target.checked)}
                              aria-label={`وضعیت فعال ${addon.title}`}
                            />
                            فعال
                          </label>
                        ) : addon.is_active ? (
                          "فعال"
                        ) : (
                          "غیرفعال"
                        )}
                      </td>
                      <td className="py-3">
                        {isEditing ? (
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              disabled={savingAddon}
                              onClick={() => void handleSaveAddon(addon.id)}
                              className="rounded bg-stone-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-stone-800 disabled:opacity-50"
                            >
                              {savingAddon ? "در حال ذخیره..." : "ذخیره"}
                            </button>
                            <button
                              type="button"
                              onClick={() => setEditingAddonId(null)}
                              className="rounded border border-stone-300 px-3 py-1.5 text-xs text-stone-700"
                            >
                              انصراف
                            </button>
                          </div>
                        ) : isConfirmingDelete ? (
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="text-xs text-stone-700">حذف شود؟</span>
                            <button
                              type="button"
                              disabled={deletingAddonId === addon.id}
                              onClick={() => void handleDeleteAddon(addon)}
                              className="rounded bg-red-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
                            >
                              {deletingAddonId === addon.id ? "در حال حذف..." : "تایید حذف"}
                            </button>
                            <button
                              type="button"
                              onClick={() => setConfirmDeleteAddonId(null)}
                              className="rounded border border-stone-300 px-2.5 py-1 text-xs text-stone-700"
                            >
                              انصراف
                            </button>
                          </div>
                        ) : (
                          <div className="flex flex-wrap items-center gap-2">
                            <button
                              type="button"
                              onClick={() => startEditAddon(addon)}
                              className="rounded border border-stone-300 px-3 py-1.5 text-xs font-medium text-stone-800 hover:bg-stone-100"
                            >
                              ویرایش
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                setConfirmDeleteAddonId(addon.id);
                                setEditingAddonId(null);
                                setInUseAddonId(null);
                                setAddonError(null);
                                setAddonSuccess(null);
                              }}
                              className="rounded border border-red-200 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-50"
                            >
                              حذف
                            </button>
                            {isInUse && addon.is_active ? (
                              <button
                                type="button"
                                disabled={savingAddon}
                                onClick={() => void handleDeactivateAddon(addon)}
                                className="rounded border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-900 hover:bg-amber-100 disabled:opacity-50"
                              >
                                غیرفعال کردن افزودنی
                              </button>
                            ) : null}
                          </div>
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
