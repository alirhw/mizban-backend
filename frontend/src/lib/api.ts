export interface OperatingHoursOut {
  id: number;
  weekday: number;
  open_time: string;
  close_time: string;
  crosses_midnight: boolean;
}

export interface DesignAddonOut {
  id: number;
  title: string;
  fee: number;
  is_active: boolean;
}

export interface VenuePublicItemOut {
  id: number;
  name: string;
  slug: string;
  city: string;
  venue_type: string;
  address: string;
  description: string;
}

export interface VenuePublicDetailOut extends VenuePublicItemOut {
  operating_hours: OperatingHoursOut[];
  design_addons: DesignAddonOut[];
}

export interface SpaceOut {
  id: number;
  venue_id: number;
  name: string;
  description: string;
  display_order: number;
  is_active: boolean;
  active_panorama_id: string | null;
  panorama_status: string | null;
  created_at: string;
  updated_at: string;
}

export interface VenueOwnerOut extends VenuePublicDetailOut {
  is_approved: boolean;
  subscription_status: string;
  is_publicly_visible: boolean;
  created_at: string;
  updated_at: string;
}

export interface VenueSubscriptionOut {
  is_active: boolean;
  plan_name: string | null;
  starts_at: string | null;
  expires_at: string | null;
  jalali_expires_at: string | null;
  days_remaining: number;
  has_ever_subscribed: boolean;
}

export interface TablePinOut {
  id: number;
  venue_id: number;
  space_id: number | null;
  panorama_image_id: string | null;
  table_number: string;
  capacity: number;
  pitch: number | null;
  yaw: number | null;
  description: string;
  reservation_fee_toman: number;
  is_smoking: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface TablePinUpdateIn {
  table_number?: string | null;
  capacity?: number | null;
  pitch?: number | null;
  yaw?: number | null;
  panorama_image_id?: string | null;
  description?: string | null;
  reservation_fee_toman?: number | null;
  is_smoking?: boolean | null;
  is_active?: boolean | null;
}

export interface BlockedSlotCreateIn {
  start_at: string;
  reason?: string;
}

export interface BlockedSlotOut {
  id: number;
  pin_id: number;
  start_at: string;
  end_at: string;
  jalali_start_at: string;
  reason: string;
}

export interface OwnerBookingOut {
  booking_id: number;
  status: string;
  table_number: string;
  slot_date: string;
  jalali_date: string;
  slot_start_time: string;
  start_at: string;
  end_at: string;
  start_jalali: string;
  end_jalali: string;
  amount_online_toman: number;
  amount_in_person_toman: number;
  customer_phone_masked: string;
  created_at: string;
}

export interface PublicTablePinOut {
  id: number;
  table_number: string;
  capacity: number;
  pitch: number | null;
  yaw: number | null;
  description: string;
  reservation_fee_toman: number;
  is_smoking: boolean;
}

export interface PublicPanoramaOut {
  space_id: number;
  space_name: string;
  venue_id: number;
  venue_name: string;
  panorama_image_id: string;
  image_url: string;
  thumbnail_url: string | null;
  width: number | null;
  height: number | null;
  pins: PublicTablePinOut[];
}

export interface OtpRequestOut {
  sent: boolean;
  expires_in_seconds: number;
}

export interface OtpVerifyOut {
  id: number;
  phone: string;
  role: string;
}

export interface CsrfOut {
  csrf_token: string;
}

export interface LogoutOut {
  logged_out: boolean;
}

export interface SlotOut {
  start: string;
  end: string;
  is_bookable: boolean;
  disabled_reason: string | null;
  start_jalali: string;
  end_jalali: string;
}

export interface BookingInitiateIn {
  table_pin_id: number;
  slot_date: string;
  slot_start_time: string;
  venue_id?: number | null;
  addon_ids?: number[];
}

export interface BookingInitiateOut {
  booking_id: number;
  id: number;
  status: string;
  venue_id: number;
  table_pin_id: number;
  start_at: string;
  end_at: string;
  slot_date: string;
  slot_start_time: string;
  locked_at: string | null;
  lock_expires_at: string | null;
  amount_online_toman: number;
  amount_in_person_toman: number;
  start_jalali: string;
  end_jalali: string;
  jalali_start_datetime: string;
  jalali_end_datetime: string;
  jalali_date: string;
}

export interface PaymentInitiateIn {
  booking_id: number;
  idempotency_key: string;
  callback_url: string;
}

export interface PaymentInitiateOut {
  transaction_id: number;
  booking_id: number;
  amount_toman: number;
  currency: string;
  status: string;
  provider_name: string;
  provider_reference: string | null;
  redirect_url: string;
}

export interface SplitReceiptOnlineSectionOut {
  label: string;
  description: string;
  amount_online_toman: number;
  provider_name?: string | null;
  card_pan_masked?: string | null;
}

export interface SplitReceiptAddonLineOut {
  addon_id: number;
  title: string;
  unit_fee_toman: number;
  line_total_toman: number;
}

export interface SplitReceiptInPersonSectionOut {
  label: string;
  items: SplitReceiptAddonLineOut[];
  total_in_person_toman: number;
}

export interface SplitReceiptOut {
  booking_id: number;
  status: string;
  venue_name: string;
  venue_slug: string;
  table_number: string;
  start_at: string;
  end_at: string;
  slot_date: string;
  slot_start_time: string;
  jalali_date: string;
  jalali_start_datetime: string;
  jalali_end_datetime: string;
  paid_online: SplitReceiptOnlineSectionOut;
  payable_in_person: SplitReceiptInPersonSectionOut;
  total_online_toman: number;
  total_in_person_toman: number;
  grand_total_toman: number;
}

export interface ApiErrorEnvelope {
  error_code: string;
  message: string;
  details: Record<string, unknown>;
}

export class ApiError extends Error {
  readonly status: number;
  readonly errorCode: string;
  readonly details: Record<string, unknown>;

  constructor(
    status: number,
    errorCode: string,
    message: string,
    details: Record<string, unknown> = {}
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.errorCode = errorCode;
    this.details = details;
  }
}

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

let cachedCsrfToken: string | null = null;

export function resetCsrfTokenCache(): void {
  cachedCsrfToken = null;
}

export function getApiBaseUrl(): string {
  if (typeof window === "undefined") {
    return (
      process.env.API_INTERNAL_URL ||
      process.env.NEXT_PUBLIC_API_URL ||
      "http://127.0.0.1:8000/api/v1"
    ).replace(/\/+$/, "");
  }
  return (process.env.NEXT_PUBLIC_API_URL || "/api/v1").replace(/\/+$/, "");
}

export async function ensureCsrfToken(forceRefresh = false): Promise<string> {
  if (cachedCsrfToken && !forceRefresh) {
    return cachedCsrfToken;
  }
  const response = await fetch(`${getApiBaseUrl()}/auth/csrf/`, {
    method: "GET",
    credentials: "include",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw await buildApiError(response);
  }
  const data = (await response.json()) as CsrfOut;
  cachedCsrfToken = data.csrf_token;
  return data.csrf_token;
}

async function buildApiError(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as Partial<ApiErrorEnvelope>;
    const errorCode = typeof body.error_code === "string" ? body.error_code : "HTTP_ERROR";
    const message =
      typeof body.message === "string" ? body.message : "خطایی در ارتباط با سرور رخ داد.";
    const details =
      body.details && typeof body.details === "object"
        ? (body.details as Record<string, unknown>)
        : {};
    return new ApiError(response.status, errorCode, message, details);
  } catch {
    return new ApiError(response.status, "HTTP_ERROR", "خطایی در ارتباط با سرور رخ داد.");
  }
}

export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method || "GET").toUpperCase();
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");

  if (init.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  if (UNSAFE_METHODS.has(method)) {
    const csrfToken = await ensureCsrfToken();
    headers.set("X-CSRFToken", csrfToken);
  }

  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const response = await fetch(`${getApiBaseUrl()}${normalizedPath}`, {
    ...init,
    method,
    headers,
    credentials: "include",
  });

  if (!response.ok) {
    throw await buildApiError(response);
  }

  return (await response.json()) as T;
}

export async function listPublicVenues(params?: {
  city?: string;
  venue_type?: string;
}): Promise<VenuePublicItemOut[]> {
  const search = new URLSearchParams();
  if (params?.city) search.set("city", params.city);
  if (params?.venue_type) search.set("venue_type", params.venue_type);
  const qs = search.toString();
  return apiFetch<VenuePublicItemOut[]>(`/venues/${qs ? `?${qs}` : ""}`, {
    method: "GET",
    cache: "no-store",
  });
}

export async function getPublicVenueBySlug(slug: string): Promise<VenuePublicDetailOut> {
  return apiFetch<VenuePublicDetailOut>(`/venues/${encodeURIComponent(slug)}`, {
    method: "GET",
    cache: "no-store",
  });
}

export async function listPublicVenueSpaces(slug: string): Promise<SpaceOut[]> {
  return apiFetch<SpaceOut[]>(`/venues/${encodeURIComponent(slug)}/spaces`, {
    method: "GET",
    cache: "no-store",
  });
}

export async function getPublicSpacePanorama(spaceId: number): Promise<PublicPanoramaOut> {
  return apiFetch<PublicPanoramaOut>(`/spaces/${spaceId}/panorama`, {
    method: "GET",
    cache: "no-store",
  });
}

export async function otpRequest(phone: string): Promise<OtpRequestOut> {
  return apiFetch<OtpRequestOut>("/auth/otp/request/", {
    method: "POST",
    body: JSON.stringify({ phone }),
  });
}

export async function otpVerify(phone: string, code: string): Promise<OtpVerifyOut> {
  return apiFetch<OtpVerifyOut>("/auth/otp/verify/", {
    method: "POST",
    body: JSON.stringify({ phone, code }),
  });
}

export async function getMe(): Promise<OtpVerifyOut> {
  return apiFetch<OtpVerifyOut>("/auth/me/", {
    method: "GET",
    cache: "no-store",
  });
}

export async function logout(): Promise<LogoutOut> {
  const result = await apiFetch<LogoutOut>("/auth/logout/", {
    method: "POST",
  });
  resetCsrfTokenCache();
  return result;
}

export async function listVenueSlots(
  venueId: number,
  params: { date: string; table_pin_id?: number | null }
): Promise<SlotOut[]> {
  const search = new URLSearchParams({ date: params.date });
  if (params.table_pin_id !== undefined && params.table_pin_id !== null) {
    search.set("table_pin_id", String(params.table_pin_id));
  }
  return apiFetch<SlotOut[]>(`/scheduling/venues/${venueId}/slots?${search.toString()}`, {
    method: "GET",
    cache: "no-store",
  });
}

export async function initiateBooking(payload: BookingInitiateIn): Promise<BookingInitiateOut> {
  return apiFetch<BookingInitiateOut>("/bookings/initiate/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function initiatePayment(payload: PaymentInitiateIn): Promise<PaymentInitiateOut> {
  return apiFetch<PaymentInitiateOut>("/billing/initiate/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getBookingReceipt(bookingId: number): Promise<SplitReceiptOut> {
  return apiFetch<SplitReceiptOut>(`/bookings/${bookingId}/receipt/`, {
    method: "GET",
    cache: "no-store",
  });
}

export async function listOwnerVenues(): Promise<VenueOwnerOut[]> {
  return apiFetch<VenueOwnerOut[]>("/venues/owner/venues", {
    method: "GET",
    cache: "no-store",
  });
}

export async function getOwnerVenue(venueId: number): Promise<VenueOwnerOut> {
  return apiFetch<VenueOwnerOut>(`/venues/owner/venues/${venueId}`, {
    method: "GET",
    cache: "no-store",
  });
}

export async function getOwnerVenueSubscription(venueId: number): Promise<VenueSubscriptionOut> {
  return apiFetch<VenueSubscriptionOut>(`/venues/owner/venues/${venueId}/subscription/`, {
    method: "GET",
    cache: "no-store",
  });
}

export async function listOwnerVenueSpaces(venueId: number): Promise<SpaceOut[]> {
  return apiFetch<SpaceOut[]>(`/venues/${venueId}/spaces`, {
    method: "GET",
    cache: "no-store",
  });
}

export async function listSpaceTablePins(spaceId: number): Promise<TablePinOut[]> {
  return apiFetch<TablePinOut[]>(`/panoramas/spaces/${spaceId}/pins`, {
    method: "GET",
    cache: "no-store",
  });
}

export async function updateTablePin(
  pinId: number,
  payload: TablePinUpdateIn
): Promise<TablePinOut> {
  return apiFetch<TablePinOut>(`/panoramas/pins/${pinId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function listPinBlockedSlots(pinId: number): Promise<BlockedSlotOut[]> {
  return apiFetch<BlockedSlotOut[]>(`/scheduling/pins/${pinId}/blocked-slots/`, {
    method: "GET",
    cache: "no-store",
  });
}

export async function createPinBlockedSlot(
  pinId: number,
  payload: BlockedSlotCreateIn
): Promise<BlockedSlotOut> {
  return apiFetch<BlockedSlotOut>(`/scheduling/pins/${pinId}/blocked-slots/`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function deleteBlockedSlot(blockId: number): Promise<void> {
  await apiFetch<void>(`/scheduling/blocked-slots/${blockId}/`, {
    method: "DELETE",
  });
}

export async function listOwnerVenueBookings(
  venueId: number,
  params: { limit?: number; offset?: number } = {}
): Promise<OwnerBookingOut[]> {
  const search = new URLSearchParams();
  if (params.limit !== undefined) search.set("limit", String(params.limit));
  if (params.offset !== undefined) search.set("offset", String(params.offset));
  const qs = search.toString();
  return apiFetch<OwnerBookingOut[]>(
    `/venues/owner/venues/${venueId}/bookings/${qs ? `?${qs}` : ""}`,
    {
      method: "GET",
      cache: "no-store",
    }
  );
}
