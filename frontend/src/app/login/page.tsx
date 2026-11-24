"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiError, otpRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const IRANIAN_MOBILE_REGEX = /^09\d{9}$/;

export default function LoginPage() {
  const router = useRouter();
  const { login } = useAuth();

  const [step, setStep] = useState<"phone" | "code">("phone");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [secondsLeft, setSecondsLeft] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (step !== "code" || secondsLeft <= 0) {
      return;
    }
    const timer = window.setInterval(() => {
      setSecondsLeft((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [step, secondsLeft]);

  async function handleRequestOtp(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setErrorMessage(null);

    const trimmed = phone.trim();
    if (!IRANIAN_MOBILE_REGEX.test(trimmed)) {
      setErrorMessage("لطفاً شماره موبایل معتبر ایرانی (مانند 09123456789) وارد کنید.");
      return;
    }

    setSubmitting(true);
    try {
      const res = await otpRequest(trimmed);
      setSecondsLeft(res.expires_in_seconds || 120);
      setStep("code");
    } catch (err) {
      if (err instanceof ApiError && err.errorCode === "OTP_RATE_LIMITED") {
        setErrorMessage("تعداد درخواست‌ها بیش از حد مجاز است. لطفاً چند دقیقه دیگر تلاش کنید.");
      } else {
        setErrorMessage("ارسال کد تایید انجام نشد. لطفاً دوباره تلاش کنید.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function handleVerifyOtp(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setErrorMessage(null);

    const trimmedCode = code.trim();
    if (!/^\d{5}$/.test(trimmedCode)) {
      setErrorMessage("کد تایید باید ۵ رقم باشد.");
      return;
    }

    setSubmitting(true);
    try {
      await login(phone.trim(), trimmedCode);
      router.push("/");
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorMessage("کد وارد شده نامعتبر یا منقضی شده است.");
      } else {
        setErrorMessage("خطایی در ورود رخ داد. لطفاً دوباره تلاش کنید.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-md rounded-xl border border-stone-200 bg-white p-6">
      <h1 className="mb-2 text-xl font-bold text-stone-900">ورود با شماره موبایل</h1>
      <p className="mb-6 text-sm text-stone-600">
        کد تایید یک‌بارمصرف به شماره موبایل شما ارسال می‌شود.
      </p>

      {errorMessage ? (
        <div
          role="alert"
          className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
        >
          {errorMessage}
        </div>
      ) : null}

      {step === "phone" ? (
        <form onSubmit={handleRequestOtp} className="space-y-4">
          <div>
            <label htmlFor="phone" className="mb-1.5 block text-sm font-medium text-stone-700">
              شماره موبایل
            </label>
            <input
              id="phone"
              name="phone"
              type="tel"
              dir="ltr"
              placeholder="09123456789"
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              className="w-full rounded-lg border border-stone-300 px-3 py-2 text-left text-sm focus:border-stone-900 focus:outline-none"
              required
            />
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-lg bg-stone-900 py-2.5 text-sm font-medium text-white hover:bg-stone-800 disabled:opacity-50"
          >
            {submitting ? "در حال ارسال..." : "دریافت کد تایید"}
          </button>
        </form>
      ) : (
        <form onSubmit={handleVerifyOtp} className="space-y-4">
          <div className="text-xs text-stone-600">
            کد به شماره <span dir="ltr">{phone}</span> ارسال شد.{" "}
            {secondsLeft > 0 ? (
              <span>اعتبار کد: {secondsLeft} ثانیه</span>
            ) : (
              <span className="text-red-700">زمان کد به پایان رسید.</span>
            )}
          </div>
          <div>
            <label htmlFor="code" className="mb-1.5 block text-sm font-medium text-stone-700">
              کد تایید ۵ رقمی
            </label>
            <input
              id="code"
              name="code"
              type="text"
              inputMode="numeric"
              dir="ltr"
              maxLength={5}
              placeholder="12345"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className="w-full rounded-lg border border-stone-300 px-3 py-2 text-center text-base tracking-widest focus:border-stone-900 focus:outline-none"
              required
            />
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-lg bg-stone-900 py-2.5 text-sm font-medium text-white hover:bg-stone-800 disabled:opacity-50"
          >
            {submitting ? "در حال بررسی..." : "ورود"}
          </button>
          <button
            type="button"
            onClick={() => {
              setStep("phone");
              setCode("");
              setErrorMessage(null);
            }}
            className="w-full text-center text-xs text-stone-600 underline"
          >
            تغییر شماره موبایل
          </button>
        </form>
      )}
    </div>
  );
}
