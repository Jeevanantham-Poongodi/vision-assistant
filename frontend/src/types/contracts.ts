/**
 * Mirrors API_CONTRACTS.md section 9 one-to-one (owned by Coder 1, reviewed by Coder 3).
 * The block between "SECTION 9" markers is copied verbatim from the contract.
 * Everything below it types the message payloads and REST bodies from sections 5, 6, 7 and 11.
 * JSON keys stay snake_case exactly as the contract specifies.
 */

// ---- SECTION 9 (verbatim) ---------------------------------------------------
export type Direction = "left" | "slight_left" | "center" | "slight_right" | "right";
export type DistanceZone = "very_close" | "near" | "medium" | "far" | "unknown";
export type Motion = "approaching" | "receding" | "stationary" | "unknown";
export type RiskLevel = "critical" | "high" | "medium" | "low";
export type Category = "person" | "vehicle" | "obstacle" | "animal" | "signal" | "other";
export type AlertType = "hazard" | "emergency" | "assistance_request" | "system";
export type AlertStatus = "open" | "acknowledged" | "resolved";
export type VoiceIntent =
  | "emergency"
  | "read_text"
  | "path_check"
  | "describe"
  | "ask"
  | "stop_speaking"
  | "repeat";

export interface BBox {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}
export interface Detection {
  track_id: number | null;
  class_name: string;
  spoken_name: string;
  category: Category;
  confidence: number;
  bbox: BBox;
  cx_norm: number;
  direction: Direction;
  distance_m: number | null;
  distance_zone: DistanceZone;
  distance_method: "pinhole" | "depth_model" | "edge_clipped" | "none";
  motion: Motion;
  approach_speed_mps: number | null;
  risk_level: RiskLevel;
  risk_score: number;
}
export interface Warning {
  warning_id: string;
  track_id: number | null;
  class_name: string;
  risk_level: RiskLevel;
  priority: number;
  message: string;
  short_text: string;
  speak: boolean;
  interrupt: boolean;
  rule: string;
}
export interface FrameResult {
  frame_id: number;
  frame_size: { width: number; height: number };
  ts_captured: number;
  ts_processed: number;
  latency_ms: number;
  inference_ms: number;
  detections: Detection[];
  warnings: Warning[];
  path_clear: boolean;
  clear_distance_m: number | null;
  low_confidence_scene: boolean;
}
export interface GeoPoint {
  lat: number;
  lng: number;
  accuracy_m?: number;
}
export interface Location extends GeoPoint {
  heading_deg: number | null;
  speed_mps: number | null;
  ts: number;
}
export interface Alert {
  alert_id: string;
  session_id: string;
  user_id: string;
  type: AlertType;
  risk_level: RiskLevel;
  title: string;
  message: string;
  location: GeoPoint | null;
  snapshot_b64: string | null;
  status: AlertStatus;
  created_at: string;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
}
export interface Envelope<T = unknown> {
  v: 1;
  type: string;
  ts: number;
  payload: T;
}
// ---- END SECTION 9 ----------------------------------------------------------

/** 4.7 Session */
export interface DeviceInfo {
  user_agent: string;
  platform: string;
}
export interface Session {
  session_id: string;
  user_id: string;
  status: "active" | "ended";
  started_at: string;
  ended_at: string | null;
  device_info: DeviceInfo;
  user_online: boolean;
  ws_url: string;
  guardian_ws_url: string;
}

/* ---------- 5. User channel payloads ---------- */
export interface UserHelloPayload {
  user_id: string;
  device_info: DeviceInfo;
}
export interface FramePayload {
  frame_id: number;
  image: string;
  width: number;
  height: number;
}
export interface UserStatusOutPayload {
  battery_pct: number | null;
  fps: number;
  camera: string;
}
export interface EmergencyPayload {
  trigger: "button" | "voice";
  note?: string;
}
export type PingPayload = Record<string, never>;
export interface UserWelcomePayload {
  session_id: string;
  config: { target_fps: number; max_width: number; jpeg_quality: number };
}
export interface GuardianMessageToUserPayload {
  message_id: string;
  guardian_name: string;
  text: string;
  spoken_text: string;
}
export interface EmergencyAckPayload {
  alert_id: string;
  status: "open" | "acknowledged";
  spoken_text: string;
}
export interface WsErrorPayload {
  code: ErrorCode;
  message: string;
  frame_id?: number;
}

/* ---------- 6. Guardian channel payloads ---------- */
export interface GuardianHelloPayload {
  guardian_id: string;
}
export interface GuardianMessageOutPayload {
  text: string;
}
export interface AckAlertPayload {
  alert_id: string;
  status: "acknowledged" | "resolved";
}
export interface GuardianWelcomePayload {
  session: Session;
  user: { user_id: string; name: string };
  open_alerts: Alert[];
}
export type SnapshotPayload = FramePayload;
export interface UserStatusPayload {
  online: boolean;
  fps: number;
  latency_ms: number;
  battery_pct: number | null;
  last_seen: number;
}
export interface MessageDeliveredPayload {
  message_id: string;
  text: string;
}

/* ---------- 7. REST ---------- */
export interface HealthResponse {
  status: "ok" | "degraded";
  version: string;
  models: Record<string, "loaded" | "available" | "configured" | "missing">;
  uptime_s: number;
}
export interface AppConfig {
  frame: { target_fps: number; max_width: number; jpeg_quality: number; max_in_flight: number };
  direction_zones: Record<Direction, [number, number]>;
  distance_zones_m: { very_close: number; near: number; medium: number };
  speech: {
    cooldown_ms: { critical: number; high: number; medium: number };
    max_queue: number;
    stale_ms: number;
    dedupe_ms: number;
  };
  detector: { model: string; confidence: number; classes: string[] };
}
export interface CreateSessionRequest {
  user_id: string;
  device_info: DeviceInfo;
}
export interface ListResponse<T> {
  items: T[];
  count: number;
}
export type AskMode = "question" | "describe" | "path_check";
export interface AskRequest {
  session_id: string;
  question: string;
  mode: AskMode;
  image: string | null;
}
export interface AskResponse {
  answer_id: string;
  question: string;
  answer: string;
  spoken_text: string;
  mode: AskMode;
  source: "gemini" | "fallback";
  grounded_on: { frame_id: number; detection_count: number };
  latency_ms: number;
}
export interface OcrLine {
  text: string;
  confidence: number;
  bbox: BBox;
}
export interface OcrResponse {
  text: string;
  lines: OcrLine[];
  spoken_text: string;
  interpreted: boolean;
  source: string;
  latency_ms: number;
}
export interface EmergencyRequest {
  session_id: string;
  trigger: "button" | "voice";
  location: GeoPoint | null;
  note: string | null;
}
export interface AlertsQuery {
  session_id?: string;
  user_id?: string;
  type?: AlertType;
  status?: AlertStatus;
  limit?: number;
  before?: string;
}
export interface PatchAlertRequest {
  status: "acknowledged" | "resolved";
  guardian_id: string;
}
export interface GuardianMessageRequest {
  guardian_id: string;
  text: string;
}
export interface GuardianMessageResponse {
  message_id: string;
  delivered: boolean;
}
export interface GuardianUser {
  user_id: string;
  name: string;
  relation: string;
  active_session_id: string | null;
  online: boolean;
  last_location: GeoPoint | null;
}
export interface GuardianUsersResponse {
  items: GuardianUser[];
}

export interface NavigateRequest {
  session_id: string;
  origin: GeoPoint;
  destination: string | GeoPoint;
  profile: "walking";
}
export interface NavigationStep {
  index: number;
  maneuver: string;
  distance_m: number;
  instruction: string;
  spoken_text: string;
  location: GeoPoint;
}
export interface NavigationRoute {
  route_id: string;
  destination_name: string;
  total_distance_m: number;
  duration_s: number;
  steps: NavigationStep[];
  geometry: { type: "LineString"; coordinates: Array<[number, number]> };
}

/* ---------- 11. Errors ---------- */
export type ErrorCode =
  | "VALIDATION_ERROR"
  | "INVALID_FRAME"
  | "USER_NOT_FOUND"
  | "SESSION_NOT_FOUND"
  | "ALERT_NOT_FOUND"
  | "INVALID_STATUS_TRANSITION"
  | "NO_RECENT_FRAME"
  | "DESTINATION_NOT_FOUND"
  | "MODEL_NOT_READY"
  | "UNSUPPORTED_MESSAGE"
  | "PIPELINE_ERROR"
  | "INTERNAL";
export interface ApiErrorBody {
  error: { code: ErrorCode; message: string; details: Record<string, unknown> };
}
