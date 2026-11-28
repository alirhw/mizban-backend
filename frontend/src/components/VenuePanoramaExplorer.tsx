"use client";

import dynamic from "next/dynamic";
import { useSearchParams } from "next/navigation";
import React, { useEffect, useMemo, useState } from "react";

import { BookingFlow } from "@/components/BookingFlow";
import {
  ApiError,
  getPublicSpacePanorama,
  listTableReviews,
  type DesignAddonOut,
  type PublicPanoramaOut,
  type PublicTablePinOut,
  type ReviewListOut,
  type SpaceOut,
} from "@/lib/api";
import { parseBookingResumeParams } from "@/lib/booking";
import { formatJalaliDate } from "@/lib/jalali";
import { formatToman, smokingStatusLabel } from "@/lib/panorama";

const PanoramaViewer = dynamic(() => import("@/components/PanoramaViewer"), {
  ssr: false,
  loading: () => (
    <div className="flex h-[380px] w-full items-center justify-center rounded-xl border border-stone-200 bg-stone-100 text-sm text-stone-600 sm:h-[480px]">
      در حال آماده‌سازی نمایشگر ۳۶۰ درجه...
    </div>
  ),
});

export interface VenuePanoramaExplorerProps {
  venueId: number;
  venueName: string;
  venueSlug: string;
  designAddons: DesignAddonOut[];
  spaces: SpaceOut[];
  initialSpaceId: number | null;
  initialPanorama: PublicPanoramaOut | null;
}

export function VenuePanoramaExplorer({
  venueId,
  venueName,
  venueSlug,
  designAddons,
  spaces,
  initialSpaceId,
  initialPanorama,
}: VenuePanoramaExplorerProps) {
  const searchParams = useSearchParams();
  const initialResume = useMemo(
    () =>
      parseBookingResumeParams(
        searchParams,
        (initialPanorama?.pins ?? []).map((p) => p.id),
        designAddons.filter((a) => a.is_active).map((a) => a.id)
      ),
    [searchParams, initialPanorama, designAddons]
  );
  const resumedPin = useMemo(
    () =>
      initialResume
        ? ((initialPanorama?.pins ?? []).find((p) => p.id === initialResume.pinId) ?? null)
        : null,
    [initialResume, initialPanorama]
  );

  const [selectedSpaceId, setSelectedSpaceId] = useState<number | null>(initialSpaceId);
  const [panorama, setPanorama] = useState<PublicPanoramaOut | null>(initialPanorama);
  const [loadingSpace, setLoadingSpace] = useState(false);
  const [spaceError, setSpaceError] = useState<string | null>(null);
  const [selectedPin, setSelectedPin] = useState<PublicTablePinOut | null>(resumedPin);
  const [bookingPin, setBookingPin] = useState<PublicTablePinOut | null>(resumedPin);
  const [bookingSelectionNonce, setBookingSelectionNonce] = useState(0);
  const [tableReviewsState, setTableReviewsState] = useState<{
    pinId: number | null;
    data: ReviewListOut | null;
    loading: boolean;
  }>({
    pinId: null,
    data: null,
    loading: false,
  });

  useEffect(() => {
    if (!selectedPin) return;
    const pinId = selectedPin.id;
    let active = true;
    setTableReviewsState({ pinId, data: null, loading: true });

    listTableReviews(pinId, { limit: 20, offset: 0 })
      .then((data) => {
        if (!active) return;
        setTableReviewsState({ pinId, data, loading: false });
      })
      .catch(() => {
        if (!active) return;
        setTableReviewsState({
          pinId,
          data: { average_rating: null, review_count: 0, reviews: [] },
          loading: false,
        });
      });

    return () => {
      active = false;
    };
  }, [selectedPin]);

  async function handleSelectSpace(spaceId: number) {
    if (spaceId === selectedSpaceId) return;
    setSelectedSpaceId(spaceId);
    setSelectedPin(null);
    setBookingPin(null);
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

  if (spaces.length === 0) {
    return (
      <div className="rounded-xl border border-stone-200 bg-white p-8 text-center text-sm text-stone-600">
        هنوز فضایی برای این مجموعه ثبت نشده است.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {spaces.length > 1 ? (
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="فضاهای مجموعه">
          {spaces.map((space) => {
            const active = space.id === selectedSpaceId;
            return (
              <button
                key={space.id}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => void handleSelectSpace(space.id)}
                className={`rounded-lg px-4 py-2 text-sm font-medium transition ${
                  active
                    ? "bg-stone-900 text-white"
                    : "border border-stone-300 bg-white text-stone-700 hover:bg-stone-100"
                }`}
              >
                {space.name}
              </button>
            );
          })}
        </div>
      ) : (
        <div className="text-sm font-medium text-stone-700">فضا: {spaces[0]?.name}</div>
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
            selectedPinId={selectedPin?.id ?? null}
            onSelectPin={(pin) => {
              setSelectedPin(pin);
            }}
          />

          <p className="text-xs text-stone-500">
            برای مشاهده جزئیات و هزینه رزرو، روی نشانگر میز داخل تصویر ۳۶۰ درجه بزنید.
          </p>

          {selectedPin ? (
            <div
              role="region"
              aria-label="جزئیات میز انتخاب‌شده"
              className="rounded-xl border border-stone-300 bg-white p-5 shadow-sm"
            >
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="space-y-1.5">
                  <h2 className="text-lg font-bold text-stone-900">{selectedPin.table_number}</h2>
                  <p className="text-sm text-stone-600">ظرفیت: {selectedPin.capacity} نفر</p>
                  <p className="text-sm font-medium text-stone-900">
                    هزینه رزرو آنلاین: {formatToman(selectedPin.reservation_fee_toman)}
                  </p>
                  <p className="text-sm text-stone-700">
                    وضعیت دخانیات: {smokingStatusLabel(selectedPin.is_smoking)}
                  </p>
                  {selectedPin.description ? (
                    <p className="text-xs text-stone-500">{selectedPin.description}</p>
                  ) : null}
                </div>

                <div className="flex flex-col items-end gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setBookingPin(selectedPin);
                      setBookingSelectionNonce((prev) => prev + 1);
                    }}
                    className="min-h-[44px] rounded-lg bg-stone-900 px-5 py-2.5 text-sm font-medium text-white hover:bg-stone-800"
                  >
                    انتخاب این میز
                  </button>
                  <button
                    type="button"
                    onClick={() => setSelectedPin(null)}
                    className="text-xs text-stone-500 underline"
                  >
                    بستن
                  </button>
                </div>
              </div>

              <div className="mt-4 border-t border-stone-200 pt-3 space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="text-sm font-bold text-stone-900">نظرات این میز</h3>
                  {tableReviewsState.pinId === selectedPin.id &&
                  tableReviewsState.data?.average_rating !== null &&
                  tableReviewsState.data?.average_rating !== undefined ? (
                    <span className="text-xs font-bold text-amber-600">
                      ★ {tableReviewsState.data.average_rating.toFixed(1)} (
                      {tableReviewsState.data.review_count} نظر)
                    </span>
                  ) : null}
                </div>
                {tableReviewsState.loading && tableReviewsState.pinId === selectedPin.id ? (
                  <p className="text-xs text-stone-500">در حال بارگذاری نظرات...</p>
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
                initialResume &&
                initialResume.pinId === bookingPin.id &&
                bookingSelectionNonce === 0
                  ? initialResume
                  : null
              }
              onChangeTable={() => setBookingPin(null)}
            />
          ) : null}
        </div>
      )}
    </div>
  );
}
