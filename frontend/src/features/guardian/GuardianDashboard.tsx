import { useCallback, useEffect, useRef, useState } from "react";
import { DetectionOverlay } from "@/components/DetectionOverlay";
import { api, friendlyError } from "@/services/api";
import { config, resolveWsUrl } from "@/services/config";
import {
  createRealtimeClient,
  type ConnectionStatus,
  type ManagedRealtimeClient,
} from "@/services/ws";
import { speechInput } from "@/services/speech-bridge";
import { beep } from "@/lib/browser";
import type {
  Alert,
  FrameResult,
  GuardianUser,
  GuardianWelcomePayload,
  Location,
  MessageDeliveredPayload,
  SnapshotPayload,
  UserStatusPayload,
} from "@/types/contracts";

const QUICK_PHRASES = [
  "Stop",
  "Wait",
  "Move slightly left",
  "Move slightly right",
  "Continue straight",
  "I'm watching, you're safe",
];

type SnapshotState = SnapshotPayload & { receivedAt: number };
type LeafletApi = typeof import("leaflet");

function imageUrl(image: string): string {
  return `data:image/jpeg;base64,${image}`;
}

function relativeTime(ts: number | null | undefined): string {
  if (!ts) return "No status received";
  const seconds = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  return `Last seen ${seconds} second${seconds === 1 ? "" : "s"} ago`;
}

function AlertRow({
  alert,
  onUpdate,
}: {
  alert: Alert;
  onUpdate: (alert: Alert, status: "acknowledged" | "resolved") => void;
}) {
  return (
    <article className="guardian-alert-row">
      {alert.snapshot_b64 && (
        <img
          className="guardian-alert-thumb"
          src={imageUrl(alert.snapshot_b64)}
          alt="Camera view when this alert was created"
        />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`risk-chip risk-${alert.risk_level}`}>{alert.risk_level}</span>
          <strong>{alert.type.replaceAll("_", " ")}</strong>
          <span className="text-muted-foreground">
            {new Date(alert.created_at).toLocaleTimeString()}
          </span>
        </div>
        <p className="mt-1 font-bold">{alert.title}</p>
        <p className="text-muted-foreground">{alert.message}</p>
        <p className="mt-1 text-sm">Status: {alert.status}</p>
      </div>
      {alert.status === "open" && (
        <button
          type="button"
          className="guardian-action"
          onClick={() => onUpdate(alert, "acknowledged")}
          aria-label={`Acknowledge ${alert.title}`}
        >
          Acknowledge
        </button>
      )}
      {alert.status === "acknowledged" && (
        <button
          type="button"
          className="guardian-action"
          onClick={() => onUpdate(alert, "resolved")}
          aria-label={`Resolve ${alert.title}`}
        >
          Resolve
        </button>
      )}
    </article>
  );
}

function LocationMap({
  location,
  trail,
  alerts,
}: {
  location: Location | null;
  trail: Location[];
  alerts: Alert[];
}) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const initialLocationRef = useRef(location);
  const mapRef = useRef<import("leaflet").Map | null>(null);
  const layersRef = useRef<import("leaflet").LayerGroup | null>(null);
  const leafletRef = useRef<LeafletApi | null>(null);
  const [mapError, setMapError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([import("leaflet"), import("leaflet/dist/leaflet.css")])
      .then(([module]) => {
        if (cancelled || !hostRef.current) return;
        const L = module.default;
        const map = L.map(hostRef.current, { scrollWheelZoom: false }).setView(
          initialLocationRef.current
            ? [initialLocationRef.current.lat, initialLocationRef.current.lng]
            : [11.0168, 76.9558],
          initialLocationRef.current ? 16 : 13,
        );
        const tiles = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
          attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
          maxZoom: 19,
        }).addTo(map);
        tiles.on("tileerror", () => setMapError(true));
        mapRef.current = map;
        layersRef.current = L.layerGroup().addTo(map);
        leafletRef.current = L as LeafletApi;
      })
      .catch(() => setMapError(true));
    return () => {
      cancelled = true;
      mapRef.current?.remove();
      mapRef.current = null;
      layersRef.current = null;
    };
  }, []);

  useEffect(() => {
    const L = leafletRef.current;
    const layers = layersRef.current;
    if (!L || !layers) return;
    layers.clearLayers();
    if (trail.length > 1)
      L.polyline(
        trail.map((point) => [point.lat, point.lng]),
        { color: "#167d73", weight: 4, opacity: 0.8 },
      ).addTo(layers);
    if (location) {
      if (location.accuracy_m)
        L.circle([location.lat, location.lng], {
          radius: location.accuracy_m,
          color: "#075e54",
          fillColor: "#36b8a6",
          fillOpacity: 0.12,
          weight: 2,
        }).addTo(layers);
      L.circleMarker([location.lat, location.lng], {
        radius: 9,
        color: "#075e54",
        fillColor: "#24aa96",
        fillOpacity: 1,
        weight: 3,
      })
        .bindTooltip("Arun")
        .addTo(layers);
      if (location.heading_deg !== null)
        L.marker([location.lat, location.lng], {
          icon: L.divIcon({
            className: "guardian-heading-icon",
            html: `<span style="transform:rotate(${location.heading_deg}deg)">↑</span>`,
            iconSize: [26, 26],
            iconAnchor: [13, 32],
          }),
          interactive: false,
        }).addTo(layers);
      mapRef.current?.setView([location.lat, location.lng], Math.max(mapRef.current.getZoom(), 15));
    }
    alerts.forEach((alert) => {
      if (alert.type === "emergency" && alert.location)
        L.circleMarker([alert.location.lat, alert.location.lng], {
          radius: 10,
          color: "#991b1b",
          fillColor: "#dc2626",
          fillOpacity: 1,
          weight: 3,
        })
          .bindPopup(`Emergency: ${alert.message}`)
          .addTo(layers);
    });
  }, [alerts, location, trail]);

  return (
    <div className="guardian-map-wrap">
      <div
        ref={hostRef}
        className="guardian-map"
        aria-label="Map showing the user's recent locations"
      />
      {mapError && (
        <p className="guardian-map-message" role="status">
          Map tiles are unavailable. Location coordinates remain visible in the status panel.
        </p>
      )}
      {!location && (
        <p className="guardian-map-message" role="status">
          Waiting for location…
        </p>
      )}
    </div>
  );
}

export function GuardianDashboard() {
  const [users, setUsers] = useState<GuardianUser[]>([]);
  const [selectedUser, setSelectedUser] = useState<GuardianUser | null>(null);
  const [connection, setConnection] = useState<ConnectionStatus>("closed");
  const [snapshot, setSnapshot] = useState<SnapshotState | null>(null);
  const [frameResult, setFrameResult] = useState<FrameResult | null>(null);
  const [status, setStatus] = useState<UserStatusPayload | null>(null);
  const [location, setLocation] = useState<Location | null>(null);
  const [trail, setTrail] = useState<Location[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [message, setMessage] = useState("");
  const [messageState, setMessageState] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [listBusy, setListBusy] = useState(false);
  const [clock, setClock] = useState(Date.now());
  const clientRef = useRef<ManagedRealtimeClient | null>(null);
  const unsubsRef = useRef<Array<() => void>>([]);
  const deliveryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const awaitingDeliveryRef = useRef(false);

  const loadUsers = useCallback(async () => {
    try {
      const response = await api.guardianUsers(config.demoGuardianId);
      setUsers(response.items);
      setSelectedUser(
        (current) =>
          response.items.find((user) => user.user_id === current?.user_id) ??
          response.items[0] ??
          null,
      );
      setError("");
    } catch (cause) {
      setError(friendlyError(cause));
    }
  }, []);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);
  useEffect(() => {
    if (selectedUser?.active_session_id) return;
    const timer = setInterval(() => void loadUsers(), 1000);
    return () => clearInterval(timer);
  }, [loadUsers, selectedUser?.active_session_id]);

  useEffect(() => {
    const sessionId = selectedUser?.active_session_id;
    if (!sessionId) {
      clientRef.current?.close();
      clientRef.current = null;
      setConnection("closed");
      setSnapshot(null);
      setFrameResult(null);
      setStatus(null);
      setLocation(null);
      setTrail([]);
      setAlerts([]);
      return;
    }

    let mounted = true;
    const client = createRealtimeClient("guardian", {
      hello: () => ({ guardian_id: config.demoGuardianId }),
      onStatusChange: (next) => mounted && setConnection(next),
    });
    clientRef.current = client;
    const addAlert = (alert: Alert) =>
      setAlerts((current) =>
        [alert, ...current.filter((item) => item.alert_id !== alert.alert_id)].slice(0, 100),
      );
    unsubsRef.current = [
      client.on<GuardianWelcomePayload>("welcome", (payload) =>
        setAlerts((current) => {
          const merged = [...payload.open_alerts, ...current];
          return merged
            .filter(
              (item, index) =>
                merged.findIndex((other) => other.alert_id === item.alert_id) === index,
            )
            .slice(0, 100);
        }),
      ),
      client.on<SnapshotPayload>("snapshot", (payload) =>
        setSnapshot({ ...payload, receivedAt: Date.now() }),
      ),
      client.on<FrameResult>("frame_result", setFrameResult),
      client.on<Alert>("alert", addAlert),
      client.on<Alert>("alert_updated", (updated) =>
        setAlerts((current) =>
          current.map((item) => (item.alert_id === updated.alert_id ? updated : item)),
        ),
      ),
      client.on<Location>("location", (next) => {
        setLocation(next);
        setTrail((current) => [...current.slice(-19), next]);
      }),
      client.on<UserStatusPayload>("user_status", setStatus),
      client.on<MessageDeliveredPayload>("message_delivered", () => {
        awaitingDeliveryRef.current = false;
        if (deliveryTimerRef.current) clearTimeout(deliveryTimerRef.current);
        deliveryTimerRef.current = null;
        setMessageState("Delivered");
        setMessage("");
      }),
      client.on<{ code: string; message: string }>("error", (payload) =>
        setError(payload.message || payload.code),
      ),
    ];
    client.connect(
      resolveWsUrl(
        `/guardian/${encodeURIComponent(sessionId)}?guardian_id=${encodeURIComponent(config.demoGuardianId)}`,
      ),
    );
    void api
      .listAlerts({ session_id: sessionId, limit: 100 })
      .then((response) => {
        if (mounted)
          setAlerts((current) => {
            const merged = [...current, ...response.items];
            return merged
              .filter(
                (item, index) =>
                  merged.findIndex((other) => other.alert_id === item.alert_id) === index,
              )
              .slice(0, 100);
          });
      })
      .catch((cause: unknown) => mounted && setError(friendlyError(cause)));

    return () => {
      mounted = false;
      if (deliveryTimerRef.current) clearTimeout(deliveryTimerRef.current);
      deliveryTimerRef.current = null;
      awaitingDeliveryRef.current = false;
      unsubsRef.current.forEach((off) => off());
      unsubsRef.current = [];
      client.close();
      if (clientRef.current === client) clientRef.current = null;
    };
  }, [selectedUser?.active_session_id]);

  useEffect(() => {
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const emergency = alerts.find((alert) => alert.type === "emergency" && alert.status === "open");
  const emergencyId = emergency?.alert_id;
  useEffect(() => {
    if (!emergencyId) return;
    beep(540, 350, 0.07);
    const timer = setInterval(() => beep(540, 350, 0.07), 1300);
    return () => clearInterval(timer);
  }, [emergencyId]);

  const snapshotLost = !snapshot || clock - snapshot.receivedAt > 5000;
  const statusStale = Boolean(status && clock - status.last_seen > 10000);
  const userOnline = Boolean(status?.online && !statusStale);

  const updateAlert = async (alert: Alert, nextStatus: "acknowledged" | "resolved") => {
    const client = clientRef.current;
    if (client?.status() === "open") {
      client.send("ack_alert", { alert_id: alert.alert_id, status: nextStatus });
      if (config.useMocks) {
        try {
          const updated = await api.patchAlert(alert.alert_id, {
            status: nextStatus,
            guardian_id: config.demoGuardianId,
          });
          setAlerts((current) =>
            current.map((item) => (item.alert_id === updated.alert_id ? updated : item)),
          );
        } catch (cause) {
          setError(friendlyError(cause));
        }
      }
      return;
    }
    try {
      const updated = await api.patchAlert(alert.alert_id, {
        status: nextStatus,
        guardian_id: config.demoGuardianId,
      });
      setAlerts((current) =>
        current.map((item) => (item.alert_id === updated.alert_id ? updated : item)),
      );
    } catch (cause) {
      setError(friendlyError(cause));
    }
  };

  const sendMessage = async (text = message) => {
    const clean = text.trim().slice(0, 200);
    const sessionId = selectedUser?.active_session_id;
    if (!clean || !sessionId || busy || awaitingDeliveryRef.current) return;
    setBusy(true);
    setMessageState("Sending…");
    setError("");
    try {
      if (clientRef.current?.status() === "open") {
        if (!config.useMocks) {
          awaitingDeliveryRef.current = true;
          deliveryTimerRef.current = setTimeout(() => {
            awaitingDeliveryRef.current = false;
            deliveryTimerRef.current = null;
            setMessageState("User offline, not delivered");
          }, 5000);
        }
        clientRef.current.send("guardian_message", { text: clean });
        if (config.useMocks) {
          const response = await api.guardianMessage(sessionId, {
            guardian_id: config.demoGuardianId,
            text: clean,
          });
          setMessageState(response.delivered ? "Delivered" : "User offline, not delivered");
          if (response.delivered) setMessage("");
        }
      } else {
        const response = await api.guardianMessage(sessionId, {
          guardian_id: config.demoGuardianId,
          text: clean,
        });
        setMessageState(response.delivered ? "Delivered" : "User offline, not delivered");
        if (response.delivered) setMessage("");
      }
    } catch (cause) {
      setMessageState("User offline, not delivered");
      setError(friendlyError(cause));
    } finally {
      setBusy(false);
    }
  };

  const listenForMessage = async () => {
    if (!speechInput.isSupported())
      return setMessageState("Speech input is not available in this browser.");
    setMessageState("Listening…");
    try {
      const result = await speechInput.listenOnce({ timeoutMs: 7000 });
      setMessage(result.transcript.slice(0, 200));
      setMessageState("");
    } catch {
      setMessageState("Could not hear a message. Try again.");
    }
  };

  const loadOlderAlerts = async () => {
    if (listBusy || alerts.length === 0) return;
    setListBusy(true);
    try {
      const oldest = alerts[alerts.length - 1];
      if (!oldest) return;
      const response = await api.listAlerts({
        limit: 100,
        before: oldest.created_at,
        ...(selectedUser?.active_session_id ? { session_id: selectedUser.active_session_id } : {}),
      });
      setAlerts((current) =>
        [
          ...current,
          ...response.items.filter(
            (item) => !current.some((existing) => existing.alert_id === item.alert_id),
          ),
        ].slice(0, 100),
      );
    } catch (cause) {
      setError(friendlyError(cause));
    } finally {
      setListBusy(false);
    }
  };

  return (
    <main className="guardian-shell">
      <header className="guardian-header">
        <div>
          <p className="guardian-kicker">VISION ASSISTANT / GUARDIAN</p>
          <h1>{selectedUser ? `${selectedUser.name}'s safety view` : "Guardian dashboard"}</h1>
        </div>
        <div className="guardian-header-status" role="status" aria-live="polite">
          <span className={`status-dot ${userOnline ? "is-online" : "is-offline"}`} />
          {userOnline ? "User online" : "User offline"}
          <span className="guardian-connection"> · Socket {connection}</span>
          {config.useMocks && <span className="mock-label">MOCK</span>}
        </div>
      </header>
      {emergency && (
        <section className="guardian-emergency" role="alert" aria-live="assertive">
          <div>
            <p className="guardian-kicker">EMERGENCY ALERT</p>
            <h2>{emergency.title}</h2>
            <p>{emergency.message}</p>
          </div>
          <button
            type="button"
            className="guardian-emergency-button"
            onClick={() => void updateAlert(emergency, "acknowledged")}
          >
            Acknowledge
          </button>
        </section>
      )}
      {error && (
        <p className="guardian-error" role="alert">
          {error}
        </p>
      )}

      <section className="guardian-main-grid">
        <div className="guardian-left-column">
          <section className="guardian-section guardian-live-section" aria-label="Live camera view">
            <div className="guardian-section-heading">
              <h2>Live view</h2>
              <span className={snapshotLost ? "live-indicator is-lost" : "live-indicator"}>
                {snapshotLost
                  ? "Connection to user lost"
                  : `Live · ${status?.fps?.toFixed(1) ?? "—"} fps · ${status?.latency_ms ?? "—"} ms`}
              </span>
            </div>
            <div className={`guardian-video-frame ${snapshotLost ? "is-stale" : ""}`}>
              {snapshot && (
                <img src={imageUrl(snapshot.image)} alt="Latest camera snapshot from the user" />
              )}
              {frameResult && <DetectionOverlay frame={frameResult} />}
              {!snapshot && <p className="guardian-empty-view">Waiting for camera snapshots…</p>}
            </div>
            {frameResult && (
              <div className="guardian-frame-summary" role="status">
                <strong>
                  {frameResult.path_clear
                    ? "Path clear"
                    : frameResult.clear_distance_m !== null
                      ? `Nearest obstacle ${frameResult.clear_distance_m.toFixed(1)} m`
                      : "Path not clear"}
                </strong>
                <span>
                  {frameResult.detections.length} detections · frame {frameResult.frame_id}
                </span>
              </div>
            )}
          </section>
          <section
            className="guardian-section guardian-alert-section"
            aria-labelledby="alerts-heading"
          >
            <div className="guardian-section-heading">
              <h2 id="alerts-heading">Alert feed</h2>
              <span>{alerts.length} shown</span>
            </div>
            <div className="guardian-alert-list" aria-live="polite">
              {alerts.length === 0 ? (
                <p className="guardian-muted">No alerts for this session.</p>
              ) : (
                alerts.map((alert) => (
                  <AlertRow
                    key={alert.alert_id}
                    alert={alert}
                    onUpdate={(item, next) => void updateAlert(item, next)}
                  />
                ))
              )}
            </div>
            {alerts.length > 0 && (
              <button
                type="button"
                className="guardian-load-more"
                onClick={() => void loadOlderAlerts()}
                disabled={listBusy}
              >
                {listBusy ? "Loading…" : "Load older alerts"}
              </button>
            )}
          </section>
        </div>

        <aside className="guardian-right-column">
          <section
            className="guardian-section guardian-user-section"
            aria-labelledby="person-heading"
          >
            <div className="guardian-section-heading">
              <h2 id="person-heading">Person</h2>
              {users.length > 1 && (
                <label className="guardian-user-select-label">
                  <span className="sr-only">Select person</span>
                  <select
                    value={selectedUser?.user_id ?? ""}
                    onChange={(event) =>
                      setSelectedUser(
                        users.find((user) => user.user_id === event.target.value) ?? null,
                      )
                    }
                  >
                    {users.map((user) => (
                      <option key={user.user_id} value={user.user_id}>
                        {user.name}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </div>
            <h3>{selectedUser?.name ?? "No linked user"}</h3>
            {!selectedUser?.active_session_id ? (
              <p className="guardian-muted">
                {selectedUser
                  ? `${selectedUser.name} is not using the assistant right now`
                  : "No user is linked to this guardian."}
              </p>
            ) : (
              <>
                <p
                  className={`guardian-user-state ${userOnline && !statusStale ? "" : "is-offline"}`}
                >
                  {userOnline
                    ? "Online"
                    : statusStale
                      ? "Offline for more than 10 seconds"
                      : status
                        ? "Offline"
                        : "Waiting for status"}
                </p>
                <dl className="guardian-stats">
                  <div>
                    <dt>Frame rate</dt>
                    <dd>{status?.fps?.toFixed(1) ?? "—"} fps</dd>
                  </div>
                  <div>
                    <dt>Latency</dt>
                    <dd>{status?.latency_ms ?? "—"} ms</dd>
                  </div>
                  <div>
                    <dt>Battery</dt>
                    <dd>
                      {status?.battery_pct == null ? "Unavailable" : `${status.battery_pct}%`}
                    </dd>
                  </div>
                  <div>
                    <dt>Last seen</dt>
                    <dd>{relativeTime(status?.last_seen)}</dd>
                  </div>
                  {location && (
                    <div>
                      <dt>Coordinates</dt>
                      <dd>
                        {location.lat.toFixed(5)}, {location.lng.toFixed(5)} · ±
                        {location.accuracy_m ?? "?"} m
                      </dd>
                    </div>
                  )}
                </dl>
              </>
            )}
          </section>

          <section className="guardian-section guardian-map-section" aria-labelledby="map-heading">
            <div className="guardian-section-heading">
              <h2 id="map-heading">Location</h2>
            </div>
            <LocationMap location={location} trail={trail} alerts={alerts} />
          </section>

          <section
            className="guardian-section guardian-message-section"
            aria-labelledby="message-heading"
          >
            <div className="guardian-section-heading">
              <h2 id="message-heading">Talk to {selectedUser?.name ?? "the user"}</h2>
            </div>
            <div className="guardian-quick-phrases" aria-label="Quick messages">
              {QUICK_PHRASES.map((phrase) => (
                <button
                  key={phrase}
                  type="button"
                  onClick={() => void sendMessage(phrase)}
                  disabled={!selectedUser?.active_session_id || busy}
                >
                  {phrase}
                </button>
              ))}
            </div>
            <form
              className="guardian-message-form"
              onSubmit={(event) => {
                event.preventDefault();
                void sendMessage();
              }}
            >
              <label htmlFor="guardian-message">
                Message <span>{message.length}/200</span>
              </label>
              <textarea
                id="guardian-message"
                maxLength={200}
                rows={3}
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                disabled={!selectedUser?.active_session_id}
              />
              <div className="guardian-message-actions">
                <button
                  type="button"
                  className="guardian-action"
                  onClick={() => void listenForMessage()}
                  disabled={!speechInput.isSupported()}
                  aria-label="Speak a message to fill the text box"
                >
                  Push to talk
                </button>
                <button
                  type="submit"
                  className="guardian-send-button"
                  disabled={!message.trim() || busy || !selectedUser?.active_session_id}
                >
                  {busy ? "Sending…" : "Send message"}
                </button>
              </div>
              {messageState && (
                <p className="guardian-message-status" role="status" aria-live="polite">
                  {messageState}
                </p>
              )}
            </form>
          </section>
        </aside>
      </section>
    </main>
  );
}
