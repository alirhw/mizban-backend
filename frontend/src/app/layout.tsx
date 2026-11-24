import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth";
import { Header } from "@/components/Header";

export const metadata: Metadata = {
  title: "میزبان | رزرو آنلاین میز کافه و رستوران",
  description: "پلتفرم رزرو آنلاین میز کافه و رستوران با تور سه‌بعدی",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="fa" dir="rtl">
      <body className="flex min-h-screen flex-col bg-stone-50 text-stone-900 antialiased">
        <AuthProvider>
          <Header />
          <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8">{children}</main>
          <footer className="border-t border-stone-200 bg-white py-6 text-center text-xs text-stone-500">
            میزبان — رزرو آنلاین میز کافه و رستوران
          </footer>
        </AuthProvider>
      </body>
    </html>
  );
}
