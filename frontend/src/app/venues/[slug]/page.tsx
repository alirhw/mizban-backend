import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError, getPublicVenueBySlug } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function VenueDetailPlaceholderPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;

  let venueName = "";
  let venueCity = "";
  try {
    const venue = await getPublicVenueBySlug(slug);
    venueName = venue.name;
    venueCity = venue.city;
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      notFound();
    }
    throw err;
  }

  return (
    <section className="space-y-4 rounded-xl border border-stone-200 bg-white p-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-bold text-stone-900">{venueName}</h1>
        <p className="text-sm text-stone-600">{venueCity}</p>
      </div>
      <p className="text-sm text-stone-600">
        نمای سه‌بعدی و انتخاب میز در تسک‌های بعدی این فاز اضافه می‌شود.
      </p>
      <Link href="/" className="inline-block text-sm font-medium text-stone-900 underline">
        بازگشت به فهرست کافه‌ها
      </Link>
    </section>
  );
}
