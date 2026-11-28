"use client";

import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import React, { useEffect, useMemo, useState } from "react";

import { BookingFlow } from "@/components/BookingFlow";
import {
  ApiError,
  getPublicSpacePanorama,
  listPublicVenueSpaces,
  listTableReviews,
  type DesignAddonOut,
  type PublicPanoramaOut,
  type PublicTablePinOut,
  type ReviewListOut,
  type SpaceOut,
} from "@/lib/api";
import {
  parseBookingResumeParams,
  parseRawResumePinId,
  type BookingResumeParams,
  type BookingStep,
} from "@/lib/booking";
import { formatJalaliDate } from "@/lib/jalali";
import { formatToman, getPinsWithoutCoordinates, smokingStatusLabel } from "@/lib/panorama";

const PanoramaViewer = dynamic(() => import("@/components/PanoramaViewer"), {
  ssr: false,
  loading: () => (
    <div className="flex h-[380px] w-full items-center justify-center rounded-xl border border-stone-200 bg-stone-100 text-sm text-stone-600 sm:h-[480px]">
      در حال آماده‌سازی نمایشگر ۳۶۰ درجه...
    </div>
  ),
});

const TABLE_REVIEWS_PAGE_SIZE = 20;

export interface VenuePanoramaExplorerProps {
  venueId: number;
  venueName: string;
  venueSlug: string;
  designAddons: DesignAddonOut[];
  spaces: SpaceOut[];
  initialSpaceId: number | null;
  initialPanorama: PublicPanoramaOut | null;
  spacesError?: boolean;
  initialPanoramaError?: boolean;
}

export function VenuePanoramaExplorer({
  venueId,
  venueName,
  venueSlug,
  designAddons,
  spaces,
  initialSpaceId,
  initialPanorama,
  spacesError = false,
  initialPanoramaError = false,
}: VenuePanoramaExplorerProps) {
  const searchParams = useSearchParams();
  const activeAddonIds = useMemo(
    () => designAddons.filter((a) => a.is_active).map((a) => a.id),
    [designAddons]
  );
  const rawResumePinId = useMemo(() => parseRawResumePinId(searchParams), [searchParams]);
  const initialResume = useMemo(
    () =>
      parseBookingResumeParams(
        searchParams,
        (initialPanorama?.pins ?? []).map((p) => p.id),
        activeAddonIds
      ),
    [searchParams, initialPanorama, activeAddonIds]
  );
  const resumedPin = useMemo(
    () =>
      initialResume
        ? ((initialPanorama?.pins ?? []).find((p) => p.id === initialResume.pinId) ?? null)
        : null,
    [initialResume, initialPanorama]
  );

  const [spacesList, setSpacesList] = useState<SpaceOut[]>(spaces);
  const [spacesLoadError, setSpacesLoadError] = useState<boolean>(spacesError);
  const [retryingSpaces, setRetryingSpaces] = useState(false);

  const [selectedSpaceId, setSelectedSpaceId] = useState<number | null>(initialSpaceId);
  const [panorama, setPanorama] = useState<PublicPanoramaOut | null>(initialPanorama);
  const [loadingSpace, setLoadingSpace] = useState(false);
  const [spaceError, setSpaceError] = useState<string | null>(
    initialPanoramaError ? "دریافت تصویر ۳۶۰ درجه این فضا با خطا مواجه شد." : null
  );
  const [selectedPin, setSelectedPin] = useState<PublicTablePinOut | null>(resumedPin);
  const [bookingPin, setBookingPin] = useState<PublicTablePinOut | null>(resumedPin);
  const [bookingStep, setBookingStep] = useState<BookingStep | null>(null);
  const [bookingSelectionNonce, setBookingSelectionNonce] = useState(0);
  const [pinSwitchNotice, setPinSwitchNotice] = useState<string | null>(null);
  const [resolvedResume, setResolvedResume] = useState<BookingResumeParams | null>(null);
  const [resumeNotFoundError, setResumeNotFoundError] = useState<string | null>(null);
  const [tableReviewsState, setTableReviewsState] = useState<{
    pinId: number | null;
    data: ReviewListOut | null;
    loading: boolean;
    loadingMore: boolean;
    error: string | null;
  }>({
    pinId: null,
    data: null,
    loading: false,
    loadingMore: false,
    error: null,
  });

  const isBookingLocked =
    bookingStep === "locked" || bookingStep === "paying" || bookingStep === "failed";
  const activeDetailsPin = bookingPin ?? selectedPin;
  const effectiveResume = initialResume ?? resolvedResume;

  useEffect(() => {
    if (rawResumePinId === null || initialResume !== null) {
      setResolvedResume(null);
      setResumeNotFoundError(null);
      return;
    }
    if (spacesLoadError) {
      return;
    }

    let active = true;
    const otherSpaces = spacesList.filter((s) => s.id !== initialSpaceId);

    async function searchSpacesForResumePin() {
      for (const space of otherSpaces) {
        try {
          const nextPanorama = await getPublicSpacePanorama(space.id);
          if (!active) return;
          const foundPin = nextPanorama.pins.find((p) => p.id === rawResumePinId) ?? null;
          if (!foundPin) continue;
          const parsed = parseBookingResumeParams(
            searchParams,
            nextPanorama.pins.map((p) => p.id),
            activeAddonIds
          );
          if (parsed) {
            setSelectedSpaceId(space.id);
            setPanorama(nextPanorama);
            setSpaceError(null);
            setSelectedPin(foundPin);
            setBookingPin(foundPin);
            setResolvedResume(parsed);
            setResumeNotFoundError(null);
            return;
          }
        } catch {
          // Skip failing spaces and continue searching remaining spaces.
        }
      }
      if (active) {
        setResolvedResume(null);
        setResumeNotFoundError("رزرو موردنظر یافت نشد؛ لطفاً دوباره میز را انتخاب کنید.");
      }
    }

    void searchSpacesForResumePin();
    return () => {
      active = false;
    };
  }, [rawResumePinId, initialResume, spacesList, initialSpaceId, spacesLoadError, searchParams, activeAddonIds]);

  function loadTableReviews(pinId: number) {
    setTableReviewsState({
      pinId,
      data: null,
      loading: true,
      loadingMore: false,
      error: null,
    });

    return listTableReviews(pinId, { limit: TABLE_REVIEWS_PAGE_SIZE, offset: 0 })
      .then((data) => {
        setTableReviewsState((prev) =>
          prev.pinId === pinId
            ? { pinId, data, loading: false, loadingMore: false, error: null }
            : prev
        );
      })
      .catch(() => {
        setTableReviewsState((prev) =>
          prev.pinId === pinId
            ? {
                pinId,
                data: null,
                loading: false,
                loadingMore: false,
                error: "دریافت نظرات این میز با خطا مواجه شد.",
              }
            : prev
        );
      });
  }

  useEffect(() => {
    if (!activeDetailsPin) return;
    const pinId = activeDetailsPin.id;
    let active = true;
    setTableReviewsState({
      pinId,
      data: null,
      loading: true,
      loadingMore: false,
      error: null,
    });

    listTableReviews(pinId, { limit: TABLE_REVIEWS_PAGE_SIZE, offset: 0 })
      .then((data) => {
        if (!active) return;
        setTableReviewsState({
          pinId,
          data,
          loading: false,
          loadingMore: false,
          error: null,
        });
      })
      .catch(() => {
        if (!active) return;
        setTableReviewsState({
          pinId,
          data: null,
          loading: false,
          loadingMore: false,
          error: "دریافت نظرات این میز با خطا مواجه شد.",
        });
      });

    return () => {
      active = false;
    };
  }, [activeDetailsPin?.id]);

  async function handleLoadMoreTableReviews() {
    if (!activeDetailsPin || !tableReviewsState.data || tableReviewsState.loadingMore) return;
    const pinId = activeDetailsPin.id;
    const offset = tableReviewsState.data.reviews.length;
    setTableReviewsState((prev) => ({ ...prev, loadingMore: true }));
    try {
      const nextPage = await listTableReviews(pinId, {
        limit: TABLE_REVIEWS_PAGE_SIZE,
        offset,
      });
      setTableReviewsState((prev) => {
        if (prev.pinId !== pinId || !prev.data) return prev;
        return {
          ...prev,
          loadingMore: false,
          data: {
            ...nextPage,
            reviews: [...prev.data.reviews, ...nextPage.reviews],
          },
        };
      });
    } catch {
      setTableReviewsState((prev) =>
        prev.pinId === pinId
          ? {
              ...prev,
              loadingMore: false,
              error: "دریافت نظرات بیشتر با خطا مواجه شد.",
            }
          : prev
      );
    }
  }

  async function handleRetrySpaces() {
    if (retryingSpaces) return;
    setRetryingSpaces(true);
    try {
      const nextSpaces = await listPublicVenueSpaces(venueSlug);
      setSpacesList(nextSpaces);
      setSpacesLoadError(false);
      const firstId = nextSpaces[0]?.id ?? null;
      setSelectedSpaceId(firstId);
      if (firstId !== null) {
        setLoadingSpace(true);
        try {
          const nextPanorama = await getPublicSpacePanorama(firstId);
          setPanorama(nextPanorama);
          setSpaceError(null);
        } catch (err) {
          setPanorama(null);
          if (!(err instanceof ApiError && err.status === 404)) {
            setSpaceError("دریافت تصویر ۳۶۰ درجه این فضا با خطا مواجه شد.");
          }
        } finally {
          setLoadingSpace(false);
        }
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setSpacesList([]);
        setSpacesLoadError(false);
      } else {
        setSpacesLoadError(true);
      }
    } finally {
      setRetryingSpaces(false);
    }
  }

  async function handleSelectSpace(spaceId: number) {
    if (isBookingLocked) return;
    if (spaceId === selectedSpaceId) return;
    setSelectedSpaceId(spaceId);
    setSelectedPin(null);
    setBookingPin(null);
    setBookingStep(null);
    setPinSwitchNotice(null);
    setSpaceError(null);
    setLoadingSpace(true);

    try {
      const nextPanorama = await getPublicSpacePanorama(spaceId);
      setPanorama(nextPanorama);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setPanorama(null);
      } else {
        setPanorama(null);
        setSpaceError("دریافت تصویر ۳۶۰ درجه این فضا با خطا مواجه شد.");
      }
    } finally {
      setLoadingSpace(false);
    }
  }

  const unmappedPins = useMemo(
    () => (panorama ? getPinsWithoutCoordinates(panorama.pins) : []),
    [panorama]
  );

  if (spacesLoadError) {
    return (
      <div
        role="alert"
        className="rounded-xl border border-red-200 bg-red-50 p-6 text-center text-sm text-red-900 space-y-3"
      >
        <p>دریافت فهرست فضاهای مجموعه با خطا مواجه شد.</p>
        <button
          type="button"
          disabled={retryingSpaces}
          onClick={() => void handleRetrySpaces()}
          className="min-h-[40px] rounded-lg bg-red-800 px-4 py-2 text-xs font-semibold text-white hover:bg-red-900 disabled:opacity-50"
        >
          {retryingSpaces ? "در حال تلاش مجدد..." : "تلاش مجدد"}
        </button>
      </div>
    );
  }

  if (spacesList.length === 0) {
    return (
      <div className="rounded-xl border border-stone-200 bg-white p-8 text-center text-sm text-stone-600">
        هنوز فضایی برای این مجموعه ثبت نشده است.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {resumeNotFoundError ? (
        <div
          role="alert"
          className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900"
        >
          {resumeNotFoundError}
        </div>
      ) : null}

      {spacesList.length > 1 ? (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2" role="tablist" aria-label="فضاهای مجموعه">
            {spacesList.map((space) => {
              const active = space.id === selectedSpaceId;
              return (
                <button
                  key={space.id}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  aria-disabled={isBookingLocked}
                  disabled={isBookingLocked}
                  onClick={() => void handleSelectSpace(space.id)}
                  className={`rounded-lg px-4 py-2 text-sm font-medium transition ${
                    active
                      ? "bg-stone-900 text-white"
                      : "border border-stone-300 bg-white text-stone-700 hover:bg-stone-100"
                  } disabled:cursor-not-allowed disabled:opacity-50`}
                >
                  {space.name}
                </button>
              );
            })}
          </div>
          {isBookingLocked ? (
            <p className="text-xs text-amber-800">
              در زمان قفل رزرو یا پرداخت امکان تغییر فضا وجود ندارد.
            </p>
          ) : null}
        </div>
      ) : (
        <div className="text-sm font-medium text-stone-700">فضا: {spacesList[0]?.name}</div>
      )}

      {loadingSpace ? (
        <div className="flex h-[380px] w-full items-center justify-center rounded-xl border border-stone-200 bg-stone-100 text-sm text-stone-600 sm:h-[480px]">
          در حال دریافت تصویر ۳۶۰ درجه...
        </div>
      ) : spaceError ? (
        <div
          role="alert"
          className="rounded-xl border border-red-200 bg-red-50 p-6 text-center text-sm text-red-800"
        >
          {spaceError}
        </div>
      ) : !panorama ? (
        <div className="rounded-xl border border-stone-200 bg-white p-8 text-center text-sm text-stone-600">
          برای این فضا هنوز تصویر ۳۶۰ درجه ثبت نشده است.
        </div>
      ) : (
        <div className="space-y-4">
          <PanoramaViewer
            imageUrl={panorama.image_url}
            pins={panorama.pins}
            selectedPinId={activeDetailsPin?.id ?? null}
            onSelectPin={(pin) => {
              if (!pin) {
                if (!bookingPin) {
                  setSelectedPin(null);
                  setPinSwitchNotice(null);
                }
                return;
              }
              if (bookingPin) {
                if (bookingPin.id === pin.id) {
                  setPinSwitchNotice(null);
                  return;
                }
                if (isBookingLocked) {
                  setPinSwitchNotice(
                    "برای انتخاب میز دیگر، ابتدا فرآیند رزرو یا پرداخت فعلی را تکمیل یا لغو کنید."
                  );
                  return;
                }
                setSelectedPin(pin);
                setBookingPin(pin);
                setBookingSelectionNonce((prev) => prev + 1);
                setPinSwitchNotice(null);
                return;
              }
              setSelectedPin(pin);
              setPinSwitchNotice(null);
            }}
          />

          <p className="text-xs text-stone-500">
            برای مشاهده جزئیات و هزینه رزرو، روی نشانگر میز داخل تصویر ۳۶۰ درجه بزنید.
          </p>

          {unmappedPins.length > 0 ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 text-xs text-amber-900">
              میزهای {unmappedPins.map((p) => p.table_number).join("، ")} روی تصویر ۳۶۰ درجه نمایش
              داده نمی‌شوند چون مختصات ندارند.
            </div>
          ) : null}

          {pinSwitchNotice ? (
            <div
              role="alert"
              className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-2.5 text-xs text-amber-900"
            >
              {pinSwitchNotice}
            </div>
          ) : null}

          {activeDetailsPin ? (
            <div
              role="region"
              aria-label="جزئیات میز انتخاب‌شده"
              className="rounded-xl border border-stone-300 bg-white p-5 shadow-sm"
            >
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="space-y-1.5">
                  <h2 className="text-lg font-bold text-stone-900">
                    {activeDetailsPin.table_number}
                  </h2>
                  <p className="text-sm text-stone-600">ظرفیت: {activeDetailsPin.capacity} نفر</p>
                  <p className="text-sm font-medium text-stone-900">
                    هزینه رزرو آنلاین: {formatToman(activeDetailsPin.reservation_fee_toman)}
                  </p>
                  <p className="text-sm text-stone-700">
                    وضعیت دخانیات: {smokingStatusLabel(activeDetailsPin.is_smoking)}
                  </p>
                  {activeDetailsPin.description ? (
                    <p className="text-xs text-stone-500">{activeDetailsPin.description}</p>
                  ) : null}
                </div>

                <div className="flex flex-col items-end gap-2">
                  {!bookingPin || bookingPin.id !== activeDetailsPin.id ? (
                    <button
                      type="button"
                      onClick={() => {
                        setBookingPin(activeDetailsPin);
                        setBookingSelectionNonce((prev) => prev + 1);
                      }}
                      className="min-h-[44px] rounded-lg bg-stone-900 px-5 py-2.5 text-sm font-medium text-white hover:bg-stone-800"
                    >
                      انتخاب این میز
                    </button>
                  ) : null}
                  {!isBookingLocked ? (
                    <button
                      type="button"
                      onClick={() => {
                        setSelectedPin(null);
                        setBookingPin(null);
                        setBookingStep(null);
                        setPinSwitchNotice(null);
                      }}
                      className="text-xs text-stone-500 underline"
                    >
                      بستن
                    </button>
                  ) : null}
                </div>
              </div>

              <div className="mt-4 border-t border-stone-200 pt-3 space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-sm font-bold text-stone-900">نظرات این میز</h3>
                  {tableReviewsState.pinId === activeDetailsPin.id &&
                  tableReviewsState.data?.average_rating !== null &&
                  tableReviewsState.data?.average_rating !== undefined ? (
                    <span className="text-xs font-bold text-amber-600">
                      ★ {tableReviewsState.data.average_rating.toFixed(1)} (
                      {tableReviewsState.data.review_count} نظر)
                    </span>
                  ) : null}
                </div>
                {tableReviewsState.loading && tableReviewsState.pinId === activeDetailsPin.id ? (
                  <p className="text-xs text-stone-500">در حال بارگذاری نظرات...</p>
                ) : tableReviewsState.error && tableReviewsState.pinId === activeDetailsPin.id ? (
                  <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-800">
                    <span>{tableReviewsState.error}</span>
                    <button
                      type="button"
                      onClick={() => void loadTableReviews(activeDetailsPin.id)}
                      className="rounded border border-red-300 bg-white px-2.5 py-1 font-medium text-red-900 hover:bg-red-100"
                    >
                      تلاش مجدد
                    </button>
                  </div>
                ) : !tableReviewsState.data || tableReviewsState.data.review_count === 0 ? (
                  <p className="text-xs text-stone-500">هنوز نظری برای این میز ثبت نشده است.</p>
                ) : (
                  <div className="space-y-2">
                    {tableReviewsState.data.reviews.map((review) => (
                      <div
                        key={review.id}
                        className="rounded-lg border border-stone-200 bg-stone-50 p-3 text-xs space-y-1"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-semibold text-stone-900">
                            {review.reviewer_name}
                          </span>
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-amber-600">★ {review.rating} از ۵</span>
                            <span className="text-stone-500">
                              {formatJalaliDate(review.created_at)}
                            </span>
                          </div>
                        </div>
                        <p className="text-stone-700">{review.text}</p>
                      </div>
                    ))}
                    <div className="flex flex-wrap items-center justify-between gap-2 pt-1 text-xs text-stone-600">
                      <span>
                        نمایش {tableReviewsState.data.reviews.length} از{" "}
                        {tableReviewsState.data.review_count} نظر
                      </span>
                      {tableReviewsState.data.reviews.length <
                      tableReviewsState.data.review_count ? (
                        <button
                          type="button"
                          disabled={tableReviewsState.loadingMore}
                          onClick={() => void handleLoadMoreTableReviews()}
                          className="rounded-lg border border-stone-300 bg-white px-3 py-1.5 font-medium text-stone-800 hover:bg-stone-100 disabled:opacity-50"
                        >
                          {tableReviewsState.loadingMore ? "در حال بارگذاری..." : "نمایش بیشتر"}
                        </button>
                      ) : null}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : null}

          {bookingPin ? (
            <BookingFlow
              key={`${bookingPin.id}-${bookingSelectionNonce}`}
              venueId={venueId}
              venueName={venueName}
              venueSlug={venueSlug}
              designAddons={designAddons}
              selectedPin={bookingPin}
              initialResume={
                effectiveResume &&
                effectiveResume.pinId === bookingPin.id &&
                bookingSelectionNonce === 0
                  ? effectiveResume
                  : null
              }
              onStepChange={setBookingStep}
              onChangeTable={() => {
                setBookingPin(null);
                setBookingStep(null);
                setPinSwitchNotice(null);
              }}
            />
          ) : null}
        </div>
      )}
    </div>
  );
}
