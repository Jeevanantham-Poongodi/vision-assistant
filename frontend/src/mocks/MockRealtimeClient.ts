/**
 * MockRealtimeClient (contract 9.2): replays src/mocks fixtures on a timer.
 * Same interface as WebSocketRealtimeClient — no other code needs to know mocks are on.
 * This is NOT a backend: it does no detection or risk logic, it only replays fixed payloads.
 */
import type {
  AckAlertPayload,
  Alert,
  EmergencyAckPayload,
  Envelope,
  FramePayload,
  FrameResult,
  GuardianMessageOutPayload,
  GuardianWelcomePayload,
  Location,
  MessageDeliveredPayload,
  SnapshotPayload,
  UserWelcomePayload,
} from "@/types/contracts";
import type {
  Channel,
  ConnectionStatus,
  ManagedRealtimeClient,
  RealtimeClientOptions,
} from "@/services/ws";
import { HandlerRegistry, makeEnvelope } from "@/services/ws";
import { currentScene, fixtures, mockId } from "./fixtures";

export class MockRealtimeClient implements ManagedRealtimeClient {
  private st: ConnectionStatus = "closed";
  private registry = new HandlerRegistry();
  private timers: Array<ReturnType<typeof setTimeout>> = [];
  private intervals: Array<ReturnType<typeof setInterval>> = [];
  private alerts = new Map<string, Alert>();

  constructor(
    private readonly channel: Channel,
    private readonly opts: RealtimeClientOptions,
  ) {}

  connect(_url: string) {
    this.cleanup();
    this.setStatus("connecting");
    this.later(120, () => {
      this.setStatus("open");
      this.send("hello", this.opts.hello());
    });
  }

  status() {
    return this.st;
  }

  on<T>(type: string, handler: (payload: T, env: Envelope<T>) => void) {
    return this.registry.on(type, handler);
  }

  close() {
    this.cleanup();
    this.setStatus("closed");
  }

  send<T>(type: string, payload: T, ts = Date.now()) {
    if (this.st !== "open") return;
    if (this.channel === "user") this.handleUser(type, payload, ts);
    else this.handleGuardian(type, payload);
  }

  /* ---------------- user channel ---------------- */
  private handleUser(type: string, payload: unknown, ts: number) {
    switch (type) {
      case "hello": {
        this.emit<UserWelcomePayload>("welcome", {
          session_id: fixtures.session.session_id,
          config: { target_fps: 5, max_width: 640, jpeg_quality: 0.65 },
        });
        // A guardian message every 25 s, contract 13.5.
        this.every(25000, () => this.emit("guardian_message", { ...fixtures.guardianMessage.payload, message_id: mockId() }));
        break;
      }
      case "frame": {
        const f = payload as FramePayload;
        this.later(140 + Math.random() * 80, () => {
          const now = Date.now();
          this.emit<FrameResult>("frame_result", {
            ...currentScene(now),
            frame_id: f.frame_id,
            ts_captured: ts,
            ts_processed: now,
            latency_ms: now - ts,
          });
        });
        break;
      }
      case "emergency":
        this.later(400, () =>
          this.emit<EmergencyAckPayload>("emergency_ack", {
            alert_id: mockId(),
            status: "open",
            spoken_text: "Your guardian has been notified.",
          }),
        );
        break;
      case "ping":
        this.emit("pong", {});
        break;
    }
  }

  /* ---------------- guardian channel ---------------- */
  private handleGuardian(type: string, payload: unknown) {
    switch (type) {
      case "hello": {
        const welcome: GuardianWelcomePayload = {
          session: fixtures.session,
          user: { user_id: fixtures.session.user_id, name: "Arun" },
          open_alerts: [],
        };
        this.emit("welcome", welcome);
        let frameId = 1;
        this.every(500, () => {
          const scene = currentScene();
          const id = frameId++;
          this.emit<SnapshotPayload>("snapshot", { frame_id: id, image: drawMockSnapshot(scene), width: 640, height: 480 });
          this.emit<FrameResult>("frame_result", { ...scene, frame_id: id });
        });
        this.every(2000, () => this.emit("user_status", { ...fixtures.userStatus.payload, last_seen: Date.now() }));
        const base = { lat: 11.0168, lng: 76.9558 };
        let step = 0;
        this.every(3000, () => {
          step++;
          this.emit<Location>("location", {
            lat: base.lat + step * 0.00006,
            lng: base.lng + Math.sin(step / 3) * 0.00005,
            accuracy_m: 12,
            heading_deg: 20 + (step % 8) * 5,
            speed_mps: 0.9,
            ts: Date.now(),
          });
        });
        this.later(8000, () => {
          const a: Alert = { ...fixtures.alertEmergency, alert_id: mockId(), created_at: new Date().toISOString() };
          this.alerts.set(a.alert_id, a);
          this.emit("alert", a);
        });
        break;
      }
      case "ack_alert": {
        const p = payload as AckAlertPayload;
        const a = this.alerts.get(p.alert_id);
        if (!a) break;
        const updated: Alert = {
          ...a,
          status: p.status,
          acknowledged_by: a.acknowledged_by ?? fixtures.alertEmergency.user_id,
          acknowledged_at: a.acknowledged_at ?? new Date().toISOString(),
        };
        this.alerts.set(a.alert_id, updated);
        this.later(200, () => this.emit("alert_updated", updated));
        break;
      }
      case "guardian_message": {
        const p = payload as GuardianMessageOutPayload;
        this.later(300, () => this.emit<MessageDeliveredPayload>("message_delivered", { message_id: mockId(), text: p.text }));
        break;
      }
      case "ping":
        this.emit("pong", {});
        break;
    }
  }

  private emit<T>(type: string, payload: T) {
    if (this.st !== "open") return;
    this.registry.dispatch(makeEnvelope(type, payload) as Envelope<unknown>);
  }
  private setStatus(s: ConnectionStatus) {
    this.st = s;
    this.opts.onStatusChange?.(s, { reconnecting: false });
  }
  private later(ms: number, fn: () => void) {
    this.timers.push(setTimeout(fn, ms));
  }
  private every(ms: number, fn: () => void) {
    this.intervals.push(setInterval(fn, ms));
  }
  private cleanup() {
    this.timers.forEach(clearTimeout);
    this.intervals.forEach(clearInterval);
    this.timers = [];
    this.intervals = [];
  }
}

let snapCanvas: HTMLCanvasElement | null = null;
/** Draws a placeholder "camera" image so the guardian live view has something to show in mock mode. */
function drawMockSnapshot(scene: FrameResult): string {
  if (typeof document === "undefined") return "";
  snapCanvas ??= document.createElement("canvas");
  const c = snapCanvas;
  c.width = 640;
  c.height = 480;
  const g = c.getContext("2d");
  if (!g) return "";
  const grad = g.createLinearGradient(0, 0, 0, 480);
  grad.addColorStop(0, "#3a4250");
  grad.addColorStop(0.55, "#59606b");
  grad.addColorStop(1, "#2a2d33");
  g.fillStyle = grad;
  g.fillRect(0, 0, 640, 480);
  g.fillStyle = "#7d828a";
  g.beginPath();
  g.moveTo(260, 260);
  g.lineTo(380, 260);
  g.lineTo(560, 480);
  g.lineTo(80, 480);
  g.fill();
  for (const d of scene.detections) {
    g.fillStyle = d.category === "vehicle" ? "#1f2a44" : d.category === "person" ? "#6b4f3a" : "#5a4632";
    g.fillRect(d.bbox.x1, d.bbox.y1, d.bbox.x2 - d.bbox.x1, d.bbox.y2 - d.bbox.y1);
  }
  g.fillStyle = "rgba(255,255,255,0.8)";
  g.font = "bold 16px monospace";
  g.fillText(`MOCK FEED · ${new Date().toLocaleTimeString()}`, 14, 26);
  return c.toDataURL("image/jpeg", 0.6).replace(/^data:image\/jpeg;base64,/, "");
}
