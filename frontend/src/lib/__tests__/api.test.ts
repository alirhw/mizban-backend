import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  getMe,
  listPublicVenues,
  logout,
  otpRequest,
  otpVerify,
  payBookingWithWallet,
  resetCsrfTokenCache,
  type PaymentTransactionOut,
} from "../api";

describe("api client (TD-006 session + CSRF contract)", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    resetCsrfTokenCache();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it("GET sends credentials: include and NO X-CSRFToken header", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    const venues = await listPublicVenues();
    expect(venues).toEqual([]);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain("/venues/");
    expect(init?.method).toBe("GET");
    expect(init?.credentials).toBe("include");
    const headers = new Headers(init?.headers);
    expect(headers.has("X-CSRFToken")).toBe(false);
    expect(headers.has("Authorization")).toBe(false);
  });

  it("POST fetches /auth/csrf/ once and injects X-CSRFToken with credentials: include", async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ csrf_token: "csrf-test-token-123" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ sent: true, expires_in_seconds: 120 }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      );

    const res = await otpRequest("09123456789");
    expect(res).toEqual({ sent: true, expires_in_seconds: 120 });
    expect(fetchMock).toHaveBeenCalledTimes(2);

    const [csrfUrl, csrfInit] = fetchMock.mock.calls[0]!;
    expect(String(csrfUrl)).toContain("/auth/csrf/");
    expect(csrfInit?.method).toBe("GET");
    expect(csrfInit?.credentials).toBe("include");

    const [postUrl, postInit] = fetchMock.mock.calls[1]!;
    expect(String(postUrl)).toContain("/auth/otp/request/");
    expect(postInit?.method).toBe("POST");
    expect(postInit?.credentials).toBe("include");
    const postHeaders = new Headers(postInit?.headers);
    expect(postHeaders.get("X-CSRFToken")).toBe("csrf-test-token-123");
    expect(postHeaders.has("Authorization")).toBe(false);
  });

  it("otpVerify posts the exact OpenAPI body { phone, code }", async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ csrf_token: "tok-verify" }), { status: 200 })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ id: 7, phone: "09123456789", role: "CUSTOMER" }), {
          status: 200,
        })
      );

    const user = await otpVerify("09123456789", "54321");
    expect(user).toEqual({ id: 7, phone: "09123456789", role: "CUSTOMER" });

    const [, postInit] = fetchMock.mock.calls[1]!;
    expect(postInit?.body).toBe(JSON.stringify({ phone: "09123456789", code: "54321" }));
  });

  it("surfaces backend error_code and message on 4xx/5xx responses", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          error_code: "OTP_RATE_LIMITED",
          message: "Too many OTP requests.",
          details: {},
        }),
        { status: 429, headers: { "Content-Type": "application/json" } }
      )
    );

    // Prime CSRF cache via getMe? No, mock CSRF then 429 on POST
    fetchMock.mockReset();
    fetchMock
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ csrf_token: "tok-err" }), { status: 200 })
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            error_code: "OTP_RATE_LIMITED",
            message: "Too many OTP requests.",
            details: {},
          }),
          { status: 429, headers: { "Content-Type": "application/json" } }
        )
      );

    await expect(otpRequest("09123456789")).rejects.toMatchObject({
      name: "ApiError",
      status: 429,
      errorCode: "OTP_RATE_LIMITED",
      message: "Too many OTP requests.",
    });

    fetchMock.mockResolvedValueOnce(new Response("Internal Server Error", { status: 500 }));
    await expect(getMe()).rejects.toBeInstanceOf(ApiError);
  });

  it("logout resets cached CSRF token", async () => {
    fetchMock
      .mockResolvedValueOnce(new Response(JSON.stringify({ csrf_token: "tok-1" }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ logged_out: true }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ csrf_token: "tok-2" }), { status: 200 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ sent: true, expires_in_seconds: 120 }), { status: 200 })
      );

    await logout();
    await otpRequest("09123456789");

    const postHeaders = new Headers(fetchMock.mock.calls[3]![1]?.headers);
    expect(postHeaders.get("X-CSRFToken")).toBe("tok-2");
  });

  it("payBookingWithWallet calls POST /api/v1/billing/wallet-pay/ with { booking_id, idempotency_key } and returns PaymentTransactionOut", async () => {
    const mockTx: PaymentTransactionOut = {
      id: 901,
      booking_id: 42,
      amount_toman: 150_000,
      currency: "TOMAN",
      status: "SUCCESS",
      provider_name: "wallet",
      provider_reference: "wallet-ref-901",
      tracking_code: "TRK-901",
      card_pan_masked: "",
      created_at: "2026-11-27T12:00:00Z",
      verified_at: "2026-11-27T12:00:00Z",
    };

    fetchMock
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ csrf_token: "tok-wallet" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(mockTx), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      );

    const tx = await payBookingWithWallet({
      booking_id: 42,
      idempotency_key: "wallet-idem-42",
    });

    expect(tx).toEqual(mockTx);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    const [postUrl, postInit] = fetchMock.mock.calls[1]!;
    expect(String(postUrl)).toContain("/api/v1/billing/wallet-pay/");
    expect(postInit?.method).toBe("POST");
    expect(postInit?.credentials).toBe("include");
    expect(postInit?.body).toBe(
      JSON.stringify({ booking_id: 42, idempotency_key: "wallet-idem-42" })
    );
    const postHeaders = new Headers(postInit?.headers);
    expect(postHeaders.get("X-CSRFToken")).toBe("tok-wallet");
  });

  it("payBookingWithWallet surfaces ApiError(400, WALLET_INSUFFICIENT_BALANCE) on insufficient balance", async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ csrf_token: "tok-wallet-err" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            error_code: "WALLET_INSUFFICIENT_BALANCE",
            message: "Wallet balance is insufficient.",
            details: {},
          }),
          {
            status: 400,
            headers: { "Content-Type": "application/json" },
          }
        )
      );

    await expect(
      payBookingWithWallet({
        booking_id: 42,
        idempotency_key: "wallet-idem-42",
      })
    ).rejects.toMatchObject({
      name: "ApiError",
      status: 400,
      errorCode: "WALLET_INSUFFICIENT_BALANCE",
      message: "Wallet balance is insufficient.",
    });
  });
});
