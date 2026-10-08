/**
 * Typed REST client for the Coder 1 endpoints in contract section 7.
 * Paths are exactly as documented; base URL comes from config.apiBase.
 */
import { config } from "./config";
import { mockRest } from "@/mocks/rest";
import type {
  Alert,
  AlertsQuery,
  ApiErrorBody,
  AppConfig,
  AskRequest,
  AskResponse,
  CreateSessionRequest,
  EmergencyRequest,
  ErrorCode,
  GuardianMessageRequest,
  GuardianMessageResponse,
  GuardianUsersResponse,
  HealthResponse,
  ListResponse,
  NavigateRequest,
  NavigationRoute,
  OcrResponse,
  PatchAlertRequest,
  Session,
} from "@/types/contracts";

/** Contract 11.1 error, surfaced to the UI with a friendly message (never a stack trace). */
export class ApiError extends Error {
  constructor(
    public readonly code: ErrorCode | "NETWORK",
    message: string,
    public readonly status: number,
    public readonly details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const FRIENDLY: Partial<Record<ApiError["code"], string>> = {
  NETWORK: "Can't reach the assistant server.",
  SESSION_NOT_FOUND: "That session has ended.",
  USER_NOT_FOUND: "Demo user is not set up on the server.",
  NO_RECENT_FRAME: "I don't have a recent camera view yet.",
  MODEL_NOT_READY: "The vision model is still loading.",
  INVALID_STATUS_TRANSITION: "That alert was already updated.",
  ALERT_NOT_FOUND: "That alert no longer exists.",
};
const REQUEST_TIMEOUT_MS = 10000;

export function friendlyError(e: unknown): string {
  if (e instanceof ApiError) return FRIENDLY[e.code] ?? e.message;
  return "Something went wrong.";
}

function isErrorBody(x: unknown): x is ApiErrorBody {
  return (
    typeof x === "object" &&
    x !== null &&
    "error" in x &&
    typeof (x as ApiErrorBody).error?.code === "string"
  );
}

async function request<T>(method: string, path: string, body?: unknown, form?: FormData): Promise<T> {
  let res: Response;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    res = await fetch(`${config.apiBase}${path}`, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : {},
      body: form ?? (body !== undefined ? JSON.stringify(body) : null),
      signal: controller.signal,
    });
  } catch (cause) {
    const message = cause instanceof DOMException && cause.name === "AbortError"
      ? "Network request timed out"
      : "Network request failed";
    throw new ApiError("NETWORK", message, 0);
  } finally {
    clearTimeout(timeout);
  }
  const text = await res.text();
  let json: unknown = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    json = null;
  }
  if (!res.ok) {
    if (isErrorBody(json)) {
      throw new ApiError(json.error.code, json.error.message, res.status, json.error.details ?? {});
    }
    throw new ApiError("INTERNAL", `HTTP ${res.status}`, res.status);
  }
  if (json === null) throw new ApiError("INTERNAL", "Server returned an invalid response", res.status);
  return json as T;
}

function qs(q: object): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== null) p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

const realApi = {
  health: () => request<HealthResponse>("GET", "/health"),
  getConfig: () => request<AppConfig>("GET", "/config"),
  createSession: (body: CreateSessionRequest) => request<Session>("POST", "/sessions", body),
  getSession: (id: string) => request<Session>("GET", `/sessions/${encodeURIComponent(id)}`),
  endSession: (id: string) => request<Session>("POST", `/sessions/${encodeURIComponent(id)}/end`),
  ask: (body: AskRequest) => request<AskResponse>("POST", "/ask", body),
  ocr: (image: Blob, sessionId?: string, interpret = true) => {
    const f = new FormData();
    f.append("image", image, "frame.jpg");
    if (sessionId) f.append("session_id", sessionId);
    f.append("interpret", String(interpret));
    return request<OcrResponse>("POST", "/ocr", undefined, f);
  },
  emergency: (body: EmergencyRequest) => request<Alert>("POST", "/emergency", body),
  listAlerts: (q: AlertsQuery) => request<ListResponse<Alert>>("GET", `/alerts${qs(q)}`),
  patchAlert: (id: string, body: PatchAlertRequest) =>
    request<Alert>("PATCH", `/alerts/${encodeURIComponent(id)}`, body),
  guardianMessage: (sessionId: string, body: GuardianMessageRequest) =>
    request<GuardianMessageResponse>(
      "POST",
      `/sessions/${encodeURIComponent(sessionId)}/guardian-message`,
      body,
    ),
  guardianUsers: (guardianId: string) =>
    request<GuardianUsersResponse>("GET", `/guardians/${encodeURIComponent(guardianId)}/users`),
  navigate: (body: NavigateRequest) => request<NavigationRoute>("POST", "/navigate", body),
};

export type Api = typeof realApi;

/** In mock mode the REST layer returns contract fixtures so the UI is usable without a backend. */
export const api: Api = config.useMocks ? mockRest : realApi;

export function b64ToJpegBlob(b64: string): Blob {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Blob([bytes], { type: "image/jpeg" });
}

export function deviceInfo() {
  const ua = typeof navigator === "undefined" ? "" : navigator.userAgent;
  const platform = /android/i.test(ua) ? "android" : /iphone|ipad|ipod/i.test(ua) ? "ios" : "desktop";
  return { user_agent: ua, platform };
}
