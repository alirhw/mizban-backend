import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  createVenueAddon,
  deleteVenueAddon,
  getMe,
  listPublicVenues,
  listVenueAddons,
  logout,
  otpRequest,
  otpVerify,
  payBookingWithWallet,
  resetCsrfTokenCache,
  submitVenueForReview,
  updateVenueAddon,
  type DesignAddonOut,
  type PaymentTransactionOut,
  type VenueOwnerOut,
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

  it("listVenueAddons calls GET /api/v1/venues/owner/venues/{venueId}/addons/ with no-store", async () => {
    const addons: DesignAddonOut[] = [
      { id: 1, title: "گل‌آرایی", fee: 120_000, is_active: true },
    ];
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify(addons), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    const result = await listVenueAddons(9);

    expect(result).toEqual(addons);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(String(url)).toContain("/api/v1/venues/owner/venues/9/addons/");
    expect(init?.method).toBe("GET");
    expect(init?.cache).toBe("no-store");
  });

  it("createVenueAddon calls POST /api/v1/venues/owner/venues/{venueId}/addons/ with payload", async () => {
    const created: DesignAddonOut = {
      id: 12,
      title: "شمع‌آرایی",
      fee: 85_000,
      is_active: true,
    };
    fetchMock
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ csrf_token: "tok-addon-create" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(created), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        })
      );

    const result = await createVenueAddon(9, {
      title: "شمع‌آرایی",
      fee: 85_000,
      is_active: true,
    });

    expect(result).toEqual(created);
    const [postUrl, postInit] = fetchMock.mock.calls[1]!;
    expect(String(postUrl)).toContain("/api/v1/venues/owner/venues/9/addons/");
    expect(postInit?.method).toBe("POST");
    expect(postInit?.body).toBe(
      JSON.stringify({ title: "شمع‌آرایی", fee: 85_000, is_active: true })
    );
  });

  it("updateVenueAddon calls PUT /api/v1/venues/owner/venues/{venueId}/addons/{addonId}/ with full payload", async () => {
    const updated: DesignAddonOut = {
      id: 12,
      title: "شمع‌آرایی ویژه",
      fee: 110_000,
      is_active: false,
    };
    fetchMock
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ csrf_token: "tok-addon-put" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(updated), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      );

    const result = await updateVenueAddon(9, 12, {
      title: "شمع‌آرایی ویژه",
      fee: 110_000,
      is_active: false,
    });

    expect(result).toEqual(updated);
    const [putUrl, putInit] = fetchMock.mock.calls[1]!;
    expect(String(putUrl)).toContain("/api/v1/venues/owner/venues/9/addons/12/");
    expect(putInit?.method).toBe("PUT");
    expect(putInit?.body).toBe(
      JSON.stringify({ title: "شمع‌آرایی ویژه", fee: 110_000, is_active: false })
    );
  });

  it("deleteVenueAddon calls DELETE and handles 204 No Content empty body", async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ csrf_token: "tok-addon-del" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    await expect(deleteVenueAddon(9, 12)).resolves.toBeUndefined();
    const [delUrl, delInit] = fetchMock.mock.calls[1]!;
    expect(String(delUrl)).toContain("/api/v1/venues/owner/venues/9/addons/12/");
    expect(delInit?.method).toBe("DELETE");
  });

  it("deleteVenueAddon surfaces ApiError(409, ADDON_IN_USE) when add-on is referenced by bookings", async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ csrf_token: "tok-addon-409" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            error_code: "ADDON_IN_USE",
            message: "Design add-on is referenced by existing bookings.",
            details: {},
          }),
          {
            status: 409,
            headers: { "Content-Type": "application/json" },
          }
        )
      );

    await expect(deleteVenueAddon(9, 12)).rejects.toMatchObject({
      name: "ApiError",
      status: 409,
      errorCode: "ADDON_IN_USE",
      message: "Design add-on is referenced by existing bookings.",
    });
  });

  it("submitVenueForReview calls POST /api/v1/venues/owner/venues/{venueId}/submit with no body and returns VenueOwnerOut", async () => {
    const venueOut: VenueOwnerOut = {
      id: 9,
      name: "کافه تست",
      slug: "test-cafe",
      city: "تهران",
      venue_type: "CAFE",
      address: "خیابان ولیعصر",
      description: "",
      operating_hours: [],
      design_addons: [],
      is_approved: false,
      review_status: "PENDING_REVIEW",
      rejection_reason: "",
      submitted_for_review_at: "2026-11-28T08:00:00Z",
      subscription_status: "INACTIVE",
      is_publicly_visible: false,
      created_at: "2026-11-01T00:00:00Z",
      updated_at: "2026-11-28T08:00:00Z",
    };
    fetchMock
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ csrf_token: "tok-submit-venue" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(venueOut), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      );

    const result = await submitVenueForReview(9);

    expect(result).toEqual(venueOut);
    const [postUrl, postInit] = fetchMock.mock.calls[1]!;
    expect(String(postUrl)).toContain("/api/v1/venues/owner/venues/9/submit");
    expect(postInit?.method).toBe("POST");
    expect(postInit?.body).toBeUndefined();
  });

  it("submitVenueForReview surfaces ApiError(409, VENUE_NOT_SUBMITTABLE) when venue is not submittable", async () => {
    fetchMock
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ csrf_token: "tok-submit-409" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            error_code: "VENUE_NOT_SUBMITTABLE",
            message: "Venue cannot be submitted in its current state.",
            details: {},
          }),
          {
            status: 409,
            headers: { "Content-Type": "application/json" },
          }
        )
      );

    await expect(submitVenueForReview(9)).rejects.toMatchObject({
      name: "ApiError",
      status: 409,
      errorCode: "VENUE_NOT_SUBMITTABLE",
      message: "Venue cannot be submitted in its current state.",
    });
  });
});
