import Link from "next/link";
import React from "react";

import { OWNER_FORBIDDEN_TEXT } from "@/lib/owner";

export function OwnerForbidden() {
  return (
    <div
      role="alert"
      className="mx-auto max-w-lg space-y-4 rounded-xl border border-red-200 bg-white p-6 shadow-sm"
    >
      <h1 className="text-xl font-bold text-red-900">{OWNER_FORBIDDEN_TEXT}</h1>
      <p className="text-sm text-stone-700">
        این بخش فقط برای مالک مجموعه در دسترس است و امکان مشاهده اطلاعات دیگران وجود ندارد.
      </p>
      <Link
        href="/"
        className="inline-block rounded-lg bg-stone-900 px-4 py-2 text-sm font-medium text-white hover:bg-stone-800"
      >
        بازگشت به صفحه اصلی
      </Link>
    </div>
  );
}
