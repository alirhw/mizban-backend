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
  created_at: string;
  updated_at: string;
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
