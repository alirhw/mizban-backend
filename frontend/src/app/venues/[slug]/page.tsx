import Link from "next/link";
import { notFound } from "next/navigation";

import { VenuePanoramaExplorer } from "@/components/VenuePanoramaExplorer";
import {
  ApiError,
  getPublicSpacePanorama,
  getPublicVenueBySlug,
  listPublicVenueSpaces,
  type PublicPanoramaOut,
  type SpaceOut,
} from "@/lib/api";

export const dynamic = "force-dynamic";

const VENUE_TYPE_LABELS: Record<string, string> = {
  CAFE: "کافه",
  RESTAURANT: "رستوران",
};

export default async function VenueDetailPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;

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
  try {
    spaces = await listPublicVenueSpaces(slug);
  } catch (err) {
    if (!(err instanceof ApiError && err.status === 404)) {
      throw err;
    }
  }

  const firstSpaceId = spaces[0]?.id ?? null;
  let initialPanorama: PublicPanoramaOut | null = null;
  if (firstSpaceId !== null) {
    try {
      initialPanorama = await getPublicSpacePanorama(firstSpaceId);
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 404)) {
        throw err;
      }
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

      <VenuePanoramaExplorer
        spaces={spaces}
        initialSpaceId={firstSpaceId}
        initialPanorama={initialPanorama}
      />
    </section>
  );
}
