/**
 * Mock REST responses (VITE_USE_MOCKS=true only). Returns contract fixtures so the frontend can be
 * exercised without Coder 3's server. It performs no real AI, OCR, or persistence.
 */
import type { Api } from "@/services/api";
import type { Alert, Session } from "@/types/contracts";
import { fixtures, mockId } from "./fixtures";

const wait = <T,>(v: T, ms = 150) => new Promise<T>((r) => setTimeout(() => r(v), ms));
let active: Session | null = null;

export const mockRest: Api = {
  health: () => wait({ status: "ok", version: "mock", models: { yolo: "loaded" }, uptime_s: 0 }),
  getConfig: () => wait(fixtures.config),
  createSession: () => {
    active = { ...fixtures.session, started_at: new Date().toISOString(), status: "active" };
    return wait(active);
  },
  getSession: (id) => wait({ ...fixtures.session, session_id: id }),
  endSession: (id) => {
    active = null;
    return wait({ ...fixtures.session, session_id: id, status: "ended", ended_at: new Date().toISOString() });
  },
  ask: (b) =>
    wait(
      {
        answer_id: mockId(),
        question: b.question,
        answer: "Mock answer. Connect the backend for real answers.",
        spoken_text: "This is a mock answer. Connect the backend for real answers.",
        mode: b.mode,
        source: "fallback",
        grounded_on: { frame_id: 0, detection_count: 0 },
        latency_ms: 0,
      },
      900,
    ),
  ocr: () =>
    wait(
      {
        text: "",
        lines: [],
        spoken_text: "I could not find any readable text. Try holding the camera closer and steady.",
        interpreted: false,
        source: "tesseract",
        latency_ms: 0,
      },
      900,
    ),
  emergency: () => wait<Alert>({ ...fixtures.alertEmergency, alert_id: mockId(), created_at: new Date().toISOString() }),
  listAlerts: () => wait({ items: [], count: 0 }),
  patchAlert: (id, b) =>
    wait<Alert>({
      ...fixtures.alertEmergency,
      alert_id: id,
      status: b.status,
      acknowledged_by: b.guardian_id,
      acknowledged_at: new Date().toISOString(),
    }),
  guardianMessage: () => wait({ message_id: mockId(), delivered: true }),
  guardianUsers: () =>
    wait({
      items: [
        {
          user_id: fixtures.session.user_id,
          name: "Arun",
          relation: "brother",
          active_session_id: fixtures.session.session_id,
          online: true,
          last_location: { lat: 11.0168, lng: 76.9558, accuracy_m: 12 },
        },
      ],
    }),
  navigate: (body) => wait({
    route_id: mockId(),
    destination_name: typeof body.destination === "string" ? body.destination : "Destination",
    total_distance_m: 240,
    duration_s: 190,
    steps: [
      {
        index: 0,
        maneuver: "depart",
        distance_m: 20,
        instruction: "Head north",
        spoken_text: "Start walking straight for about 20 meters.",
        location: body.origin,
      },
    ],
    geometry: {
      type: "LineString",
      coordinates: [[body.origin.lng, body.origin.lat], [body.origin.lng + 0.0002, body.origin.lat + 0.0002]],
    },
  }),
};
