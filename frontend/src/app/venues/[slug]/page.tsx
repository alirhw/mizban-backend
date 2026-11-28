import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";

import { VenuePanoramaExplorer } from "@/components/VenuePanoramaExplorer";
import {
  ApiError,
  getPublicSpacePanorama,
  getPublicVenueBySlug,
  listPublicVenueSpaces,
  listVenueReviews,
  type PublicPanoramaOut,
  type ReviewListOut,
  type SpaceOut,
} from "@/lib/api";
import { formatJalaliDate } from "@/lib/jalali";

export const dynamic = "force-dynamic";

const VENUE_TYPE_LABELS: Record<string, string> = {
  CAFE: "کافه",
  RESTAURANT: "رستوران",
};

export default async function VenueDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ slug: string }>;
  searchParams?: Promise<{ reviews_limit?: string }>;
}) {
  const { slug } = await params;
  const resolvedSearchParams = searchParams ? await searchParams : {};
  const parsedLimit = Number(resolvedSearchParams.reviews_limit ?? "20");
  const reviewsLimit = Number.isInteger(parsedLimit)
    ? Math.min(100, Math.max(20, parsedLimit))
    : 20;

  let venue;
  try {
    venue = await getPublicVenueBySlug(slug);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      notFound();
    }
    throw err;
  }

  let spaces: SpaceOut[] = [];
  let spacesError = false;
  try {
    spaces = await listPublicVenueSpaces(slug);
  } catch (err) {
    if (!(err instanceof ApiError && err.status === 404)) {
      spacesError = true;
    }
  }

  const firstSpaceId = spaces[0]?.id ?? null;
  let initialPanorama: PublicPanoramaOut | null = null;
  let initialPanoramaError = false;
  if (firstSpaceId !== null) {
    try {
      initialPanorama = await getPublicSpacePanorama(firstSpaceId);
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 404)) {
        initialPanoramaError = true;
      }
    }
  }

  let venueReviews: ReviewListOut = {
    average_rating: null,
    review_count: 0,
    reviews: [],
  };
  let venueReviewsError = false;
  try {
    venueReviews = await listVenueReviews(venue.id, { limit: reviewsLimit, offset: 0 });
  } catch (err) {
    if (!(err instanceof ApiError && err.status === 404)) {
      venueReviewsError = true;
    }
  }

  return (
    <section className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4 rounded-xl border border-stone-200 bg-white p-5">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold text-stone-900">{venue.name}</h1>
            <span className="rounded-full bg-stone-100 px-3 py-0.5 text-xs text-stone-700">
              {VENUE_TYPE_LABELS[venue.venue_type] ?? venue.venue_type}
            </span>
          </div>
          <p className="text-sm text-stone-600">
            {venue.city} — {venue.address}
          </p>
          {venue.description ? (
            <p className="pt-1 text-sm text-stone-600">{venue.description}</p>
          ) : null}
        </div>

        <Link
          href="/"
          className="text-sm font-medium text-stone-700 underline hover:text-stone-900"
        >
          بازگشت به فهرست کافه‌ها
        </Link>
      </div>

      <Suspense
        fallback={
          <div className="flex h-[380px] w-full items-center justify-center rounded-xl border border-stone-200 bg-stone-100 text-sm text-stone-600 sm:h-[480px]">
            در حال بارگذاری...
          </div>
        }
      >
        <VenuePanoramaExplorer
          venueId={venue.id}
          venueName={venue.name}
          venueSlug={venue.slug}
          designAddons={venue.design_addons}
          spaces={spaces}
          initialSpaceId={firstSpaceId}
          initialPanorama={initialPanorama}
          spacesError={spacesError}
          initialPanoramaError={initialPanoramaError}
        />
      </Suspense>

      <div className="rounded-xl border border-stone-200 bg-white p-5 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-bold text-stone-900">نظرات مشتریان</h2>
          {venueReviews.average_rating !== null ? (
            <div className="flex items-center gap-2 text-sm">
              <span className="font-bold text-amber-600">
                ★ {venueReviews.average_rating.toFixed(1)}
              </span>
              <span className="text-stone-600">({venueReviews.review_count} نظر)</span>
            </div>
          ) : (
            <span className="text-xs text-stone-500">({venueReviews.review_count} نظر)</span>
          )}
        </div>

        {venueReviewsError ? (
          <p role="alert" className="text-sm text-red-700">
            دریافت نظرات مشتریان با خطا مواجه شد.
          </p>
        ) : venueReviews.review_count === 0 ? (
          <p className="text-sm text-stone-500">هنوز نظری ثبت نشده است.</p>
        ) : (
          <div className="space-y-3">
            {venueReviews.reviews.map((review) => (
              <div
                key={review.id}
                className="rounded-lg border border-stone-200 bg-stone-50 p-4 space-y-1.5 text-sm"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-stone-900">{review.reviewer_name}</span>
                    <span className="text-xs text-stone-500">میز {review.table_number}</span>
                  </div>
                  <div className="flex items-center gap-3 text-xs">
                    <span className="font-bold text-amber-600">★ {review.rating} از ۵</span>
                    <span className="text-stone-500">{formatJalaliDate(review.created_at)}</span>
                  </div>
                </div>
                <p className="text-stone-700">{review.text}</p>
              </div>
            ))}

            {venueReviews.reviews.length < venueReviews.review_count && reviewsLimit < 100 ? (
              <div>
                <Link
                  href={`/venues/${encodeURIComponent(venue.slug)}?reviews_limit=${Math.min(100, reviewsLimit + 20)}`}
                  scroll={false}
                  className="inline-block rounded-lg border border-stone-300 px-4 py-2 text-xs font-medium text-stone-800 hover:bg-stone-100"
                >
                  نمایش نظرات بیشتر
                </Link>
              </div>
            ) : null}
          </div>
        )}
      </div>
    </section>
  );
}
