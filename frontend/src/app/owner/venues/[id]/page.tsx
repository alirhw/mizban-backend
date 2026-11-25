import React from "react";

import { OwnerVenueDashboard } from "@/components/OwnerVenueDashboard";

export default async function OwnerVenueDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const venueId = Number(id);

  if (!Number.isInteger(venueId) || venueId <= 0) {
    return (
      <div className="mx-auto max-w-lg rounded-xl border border-red-200 bg-white p-6 text-sm text-red-800">
        شناسه مجموعه معتبر نیست.
      </div>
    );
  }

  return <OwnerVenueDashboard venueId={venueId} />;
}
