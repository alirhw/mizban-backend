import Link from "next/link";
import { ApiError, listPublicVenues, type VenuePublicItemOut } from "@/lib/api";

export const dynamic = "force-dynamic";

const VENUE_TYPE_LABELS: Record<string, string> = {
  CAFE: "کافه",
  RESTAURANT: "رستوران",
};

export default async function HomePage() {
  let venues: VenuePublicItemOut[] = [];
  let loadError: string | null = null;

  try {
    venues = await listPublicVenues();
  } catch (err) {
    loadError =
      err instanceof ApiError
        ? err.message
        : "دریافت فهرست کافه‌ها با خطا مواجه شد. لطفاً دوباره تلاش کنید.";
  }

  return (
    <section className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-bold text-stone-900">کافه‌ها و رستوران‌ها</h1>
        <p className="text-sm text-stone-600">
          میز مورد نظر خود را انتخاب و به صورت آنلاین رزرو کنید.
        </p>
      </div>

      {loadError ? (
        <div
          role="alert"
          className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800"
        >
          {loadError}
        </div>
      ) : venues.length === 0 ? (
        <div className="rounded-xl border border-stone-200 bg-white p-8 text-center text-sm text-stone-600">
          هنوز کافه‌ای ثبت نشده است
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {venues.map((venue) => (
            <Link
              key={venue.id}
              href={`/venues/${venue.slug}`}
              className="block rounded-xl border border-stone-200 bg-white p-5 transition hover:border-stone-400 hover:shadow-sm"
            >
              <div className="mb-2 flex items-center justify-between gap-2">
                <h2 className="text-base font-bold text-stone-900">{venue.name}</h2>
                <span className="rounded-full bg-stone-100 px-2.5 py-0.5 text-xs text-stone-700">
                  {VENUE_TYPE_LABELS[venue.venue_type] ?? venue.venue_type}
                </span>
              </div>
              <p className="text-xs text-stone-500">
                {venue.city} — {venue.address}
              </p>
              {venue.description ? (
                <p className="mt-2 line-clamp-2 text-sm text-stone-600">{venue.description}</p>
              ) : null}
            </Link>
          ))}
        </div>
      )}
    </section>
  );
}
