/**
 * The ONLY module that reads import.meta.env (contract 9.3).
 * Backend secrets (SUPABASE_SERVICE_ROLE_KEY, GEMINI_API_KEY) never belong here.
 */
const env = import.meta.env;

function trimSlash(s: string): string {
  return s.replace(/\/+$/, "");
}

const apiBase = trimSlash(env.VITE_API_BASE ?? "http://localhost:8000/api/v1");

function deriveWsBase(api: string): string {
  try {
    const u = new URL(api);
    u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
    u.pathname = "/ws";
    return trimSlash(u.toString());
  } catch {
    return "ws://localhost:8000/ws";
  }
}

export const config = {
  apiBase,
  wsBase: trimSlash(env.VITE_WS_BASE || deriveWsBase(apiBase)),
  useMocks: String(env.VITE_USE_MOCKS ?? "false").toLowerCase() === "true",
  demoUserId: env.VITE_DEMO_USER_ID || "11111111-1111-1111-1111-111111111111",
  demoGuardianId: env.VITE_DEMO_GUARDIAN_ID || "22222222-2222-2222-2222-222222222222",
  mapboxToken: env.VITE_MAPBOX_TOKEN || "",
  isDev: Boolean(env.DEV),
} as const;

/**
 * Turn a server-provided ws path (e.g. "/ws/user/{id}") into a full URL using VITE_WS_BASE.
 * Absolute ws(s):// URLs are returned unchanged.
 */
export function resolveWsUrl(path: string): string {
  if (/^wss?:\/\//.test(path)) return path;
  const rel = path.replace(/^\/?ws(?=\/)/, "");
  return `${config.wsBase}${rel.startsWith("/") ? rel : `/${rel}`}`;
}

/** Frame defaults from contract 5.2 / 7.3. Replaced at runtime by GET /config and `welcome`. */
export const DEFAULT_FRAME_CONFIG = { target_fps: 5, max_width: 640, jpeg_quality: 0.65 };
