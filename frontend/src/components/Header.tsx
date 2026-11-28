"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth";

export function Header() {
  const { user, loading, logout } = useAuth();

  return (
    <header className="border-b border-stone-200 bg-white">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-4">
        <Link href="/" className="text-xl font-bold text-stone-900">
          میزبان
        </Link>
        <nav className="flex items-center gap-6 text-sm font-medium text-stone-700">
          <Link href="/" className="hover:text-stone-900">
            کافه‌ها
          </Link>
          {!loading && user?.role === "ADMIN" ? (
            <Link href="/admin/reviews" className="hover:text-stone-900">
              مدیریت نظرها
            </Link>
          ) : null}
          {loading ? (
            <span className="text-stone-400">...</span>
          ) : user ? (
            <div className="flex items-center gap-4">
              <span className="text-stone-600" dir="ltr">
                {user.phone}
              </span>
              <button
                type="button"
                onClick={() => void logout()}
                className="rounded-md border border-stone-300 px-3 py-1.5 text-stone-800 hover:bg-stone-100"
              >
                خروج
              </button>
            </div>
          ) : (
            <Link
              href="/login"
              className="rounded-md bg-stone-900 px-4 py-1.5 text-white hover:bg-stone-800"
            >
              ورود
            </Link>
          )}
        </nav>
      </div>
    </header>
  );
}
