/**
 * User app orchestration (FE-03, FE-05, FE-11, FE-12, FE-13, FE-14).
 * Camera → JPEG → WS frame (max 1 in flight) → frame_result → Coder 4 speech.
 * No detection, risk, or speech-queue logic lives here.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, b64ToJpegBlob, deviceInfo, friendlyError } from "@/services/api";
import { config, DEFAULT_FRAME_CONFIG, resolveWsUrl } from "@/services/config";
import { createRealtimeClient, type ConnectionStatus, type ManagedRealtimeClient } from "@/services/ws";
import { speech, speechInput } from "@/services/speech-bridge";
import { PRIORITY } from "@/types/speech";
import { batteryPct, beep, metersBetween, requestWakeLock } from "@/lib/browser";
import type {
  AskMode,
  EmergencyAckPayload,
  FramePayload,
  FrameResult,
  GuardianMessageToUserPayload,
  Location,
  NavigationRoute,
  Session,
  UserWelcomePayload,
  VoiceIntent,
  WsErrorPayload,
} from "@/types/contracts";

export type Phase = "idle" | "starting" | "running" | "stopping";
export type EmergencyState = "idle" | "sending" | "waiting_ack" | "retrying" | "acknowledged" | "failed";
export type WarningVerbosity = "hazards" | "everything";
export type VoiceLanguage = "en-IN" | "ta-IN";

const FRAME_TIMEOUT_MS = 1000;
const LOCATION_INTERVAL_MS = 1000;
const LOCATION_MOVE_M = 10;
const STATUS_INTERVAL_MS = 1000;
const EMERGENCY_ACK_TIMEOUT_MS = 3000;

const sys = (text: string, interrupt = false) =>
  speech.speak({ text, priority: PRIORITY.system, source: "system", interrupt });

export function useUserAssistant() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [conn, setConn] = useState<ConnectionStatus>("closed");
  const [cameraDenied, setCameraDenied] = useState(false);
  const [cameraIssue, setCameraIssue] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [frameResult, setFrameResult] = useState<FrameResult | null>(null);
  const [fps, setFps] = useState(0);
  const [encodeMs, setEncodeMs] = useState(0);
  const [lastFrameId, setLastFrameId] = useState(0);
  const [emergency, setEmergency] = useState<EmergencyState>("idle");
  const [busy, setBusy] = useState<null | "listening" | "thinking">(null);
  const [facing, setFacing] = useState<"environment" | "user" | "unknown">("unknown");
  const [currentLocation, setCurrentLocation] = useState<Location | null>(null);
  const [navigation, setNavigation] = useState<NavigationRoute | null>(null);
  const [warningVerbosity, setWarningVerbosityState] = useState<WarningVerbosity>(() => {
    try {
      return localStorage.getItem("vision-guardian-verbosity") === "hazards" ? "hazards" : "everything";
    } catch { return "everything"; }
  });
  const [voiceLanguage, setVoiceLanguageState] = useState<VoiceLanguage>(() => {
    try {
      return localStorage.getItem("vision-guardian-language") === "ta-IN" ? "ta-IN" : "en-IN";
    } catch { return "en-IN"; }
  });
  const [voiceRate, setVoiceRateState] = useState(() => {
    try {
      const rate = Number(localStorage.getItem("vision-guardian-rate"));
      return Number.isFinite(rate) && rate >= 0.7 && rate <= 1.4 ? rate : 1.05;
    } catch { return 1.05; }
  });

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const clientRef = useRef<ManagedRealtimeClient | null>(null);
  const sessionRef = useRef<Session | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const frameCfg = useRef({ ...DEFAULT_FRAME_CONFIG });
  const frameIdRef = useRef(0);
  const inFlight = useRef<{ id: number; at: number } | null>(null);
  const resultTimes = useRef<number[]>([]);
  const lastFrameB64 = useRef<string | null>(null);
  const loopTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const statusTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const geoWatch = useRef<number | null>(null);
  const latestLoc = useRef<Location | null>(null);
  const lastSentLoc = useRef<{ loc: Location; at: number } | null>(null);
  const wakeLock = useRef<{ release(): Promise<void> } | null>(null);
  const emergencyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const emergencyStateRef = useRef<EmergencyState>("idle");
  const warningVerbosityRef = useRef(warningVerbosity);
  const nextNavigationStepRef = useRef(0);
  const unsubs = useRef<Array<() => void>>([]);
  const announcedLost = useRef(false);
  const fpsRef = useRef(0);
  const phaseRef = useRef<Phase>("idle");
  phaseRef.current = phase;
  warningVerbosityRef.current = warningVerbosity;
  const updateEmergency = useCallback((next: EmergencyState) => {
    emergencyStateRef.current = next;
    setEmergency(next);
  }, []);

  useEffect(() => {
    speech.setVoice({ lang: voiceLanguage, rate: voiceRate });
  }, [voiceLanguage, voiceRate]);

  /* ---------- frame encoding ---------- */
  const encodeFrame = useCallback((): FramePayload | null => {
    const v = videoRef.current;
    if (!v || v.readyState < 2 || !v.videoWidth) return null;
    const t0 = performance.now();
    const max = frameCfg.current.max_width;
    const scale = Math.min(1, max / Math.max(v.videoWidth, v.videoHeight));
    const w = Math.round(v.videoWidth * scale);
    const h = Math.round(v.videoHeight * scale);
    canvasRef.current ??= document.createElement("canvas");
    const c = canvasRef.current;
    if (c.width !== w) c.width = w;
    if (c.height !== h) c.height = h;
    const g = c.getContext("2d");
    if (!g) return null;
    g.drawImage(v, 0, 0, w, h);
    const image = c.toDataURL("image/jpeg", frameCfg.current.jpeg_quality).replace(/^data:image\/jpeg;base64,/, "");
    setEncodeMs(Math.round(performance.now() - t0));
    lastFrameB64.current = image;
    return { frame_id: 0, image, width: w, height: h };
  }, []);

  /* ---------- backpressure loop: never more than one frame in flight ---------- */
  const tick = useCallback(() => {
    const c = clientRef.current;
    if (!c || c.status() !== "open") return;
    const now = performance.now();
    if (inFlight.current && now - inFlight.current.at < FRAME_TIMEOUT_MS) return;
    const capturedAt = Date.now();
    const f = encodeFrame();
    if (!f) return;
    const id = ++frameIdRef.current;
    c.send<FramePayload>("frame", { ...f, frame_id: id }, capturedAt);
    inFlight.current = { id, at: now };
    setLastFrameId(id);
  }, [encodeFrame]);

  const startLoop = useCallback(() => {
    if (loopTimer.current) clearInterval(loopTimer.current);
    loopTimer.current = setInterval(tick, Math.max(50, 1000 / frameCfg.current.target_fps));
  }, [tick]);

  /* ---------- message handlers ---------- */
  const attachHandlers = useCallback(
    (c: ManagedRealtimeClient) => {
      unsubs.current.forEach((u) => u());
      unsubs.current = [
        c.on<UserWelcomePayload>("welcome", (p) => {
          frameCfg.current = { ...frameCfg.current, ...p.config };
          startLoop();
        }),
        c.on<FrameResult>("frame_result", (p) => {
          if (inFlight.current && p.frame_id >= inFlight.current.id) inFlight.current = null;
          const now = performance.now();
          resultTimes.current = [...resultTimes.current.filter((t) => now - t < 2000), now];
          fpsRef.current = resultTimes.current.length / 2;
          setFps(fpsRef.current);
          setFrameResult(p);
          speech.speakWarnings(warningVerbosityRef.current === "hazards"
            ? p.warnings.filter((warning) => warning.risk_level === "critical" || warning.risk_level === "high")
            : p.warnings);
        }),
        c.on<GuardianMessageToUserPayload>("guardian_message", (p) =>
          speech.speak({ text: p.spoken_text, priority: PRIORITY.guardian, source: "guardian" }),
        ),
        c.on<EmergencyAckPayload>("emergency_ack", (p) => {
          if (emergencyTimer.current) clearTimeout(emergencyTimer.current);
          emergencyTimer.current = null;
          const alreadyConfirmed = emergencyStateRef.current === "acknowledged";
          updateEmergency("acknowledged");
          if (!alreadyConfirmed) sys(p.spoken_text);
        }),
        c.on<WsErrorPayload>("error", (p) => {
          if (p.frame_id && inFlight.current?.id === p.frame_id) inFlight.current = null;
          console.warn("[ws error]", p.code, p.message);
        }),
      ];
    },
    [startLoop, updateEmergency],
  );

  const newSession = useCallback(async () => {
    const s = await api.createSession({ user_id: config.demoUserId, device_info: deviceInfo() });
    sessionRef.current = s;
    frameIdRef.current = 0;
    inFlight.current = null;
    return s;
  }, []);

  const makeClient = useCallback(() => {
    const c = createRealtimeClient("user", {
      hello: () => ({ user_id: config.demoUserId, device_info: deviceInfo() }),
      onSessionNotFound: async () => {
        if (phaseRef.current !== "running") return null;
        try {
          return resolveWsUrl((await newSession()).ws_url);
        } catch {
          return null;
        }
      },
      onStatusChange: (s, info) => {
        setConn(s);
        if (phaseRef.current !== "running") return;
        if (s === "closed" && info.reconnecting && !announcedLost.current) {
          announcedLost.current = true;
          sys("Connection lost, reconnecting");
        } else if (s === "open" && announcedLost.current) {
          announcedLost.current = false;
          sys("Connected");
        }
      },
    });
    attachHandlers(c);
    return c;
  }, [attachHandlers, newSession]);

  /* ---------- camera ---------- */
  const openCamera = useCallback(async (): Promise<MediaStream> => {
    try {
      const s = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment", width: 640, height: 480 },
        audio: false,
      });
      setFacing("environment");
      return s;
    } catch (e) {
      if (e instanceof DOMException && (e.name === "NotAllowedError" || e.name === "SecurityError")) throw e;
      // Laptop fallback: any camera.
      const s = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      setFacing("user");
      return s;
    }
  }, []);

  /* ---------- location + status ---------- */
  const startLocation = useCallback(() => {
    if (!("geolocation" in navigator)) return;
    geoWatch.current = navigator.geolocation.watchPosition(
      (pos) => {
        const loc: Location = {
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          accuracy_m: Math.round(pos.coords.accuracy * 10) / 10,
          heading_deg: pos.coords.heading ?? null,
          speed_mps: pos.coords.speed ?? null,
          ts: pos.timestamp,
        };
        latestLoc.current = loc;
        setCurrentLocation(loc);
        const last = lastSentLoc.current;
        const now = Date.now();
        if (!last || now - last.at >= LOCATION_INTERVAL_MS || metersBetween(last.loc, loc) >= LOCATION_MOVE_M) {
          const c = clientRef.current;
          if (c?.status() === "open") {
            c.send<Location>("location", loc);
            lastSentLoc.current = { loc, at: now };
          }
        }
      },
      () => {},
      { enableHighAccuracy: true, maximumAge: 1000, timeout: 15000 },
    );
  }, []);

  useEffect(() => {
    const step = navigation?.steps[nextNavigationStepRef.current];
    const loc = currentLocation;
    if (!step || !loc || metersBetween(loc, step.location) > (loc.accuracy_m ?? 0)) return;
    nextNavigationStepRef.current += 1;
    speech.speak({ text: step.spoken_text, priority: PRIORITY.answer, source: "answer" });
  }, [currentLocation, navigation]);

  const startStatus = useCallback((cam: string) => {
    const send = async () => {
      const c = clientRef.current;
      if (c?.status() !== "open") return;
      c.send("status", { battery_pct: await batteryPct(), fps: Math.round(fpsRef.current * 10) / 10, camera: cam });
    };
    statusTimer.current = setInterval(() => void send(), STATUS_INTERVAL_MS);
  }, []);

  /* ---------- teardown ---------- */
  const teardown = useCallback(() => {
    if (loopTimer.current) clearInterval(loopTimer.current);
    if (statusTimer.current) clearInterval(statusTimer.current);
    loopTimer.current = statusTimer.current = null;
    if (geoWatch.current !== null) navigator.geolocation?.clearWatch(geoWatch.current);
    geoWatch.current = null;
    latestLoc.current = null;
    lastSentLoc.current = null;
    nextNavigationStepRef.current = 0;
    if (emergencyTimer.current) clearTimeout(emergencyTimer.current);
    emergencyTimer.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    unsubs.current.forEach((u) => u());
    unsubs.current = [];
    clientRef.current?.close();
    clientRef.current = null;
    inFlight.current = null;
    void wakeLock.current?.release().catch(() => {});
    wakeLock.current = null;
  }, []);

  /* ---------- start / stop ---------- */
  const start = useCallback(async () => {
    if (phaseRef.current !== "idle") return;
    speech.unlock();
    setPhase("starting");
    setError(null);
    setCameraDenied(false);
    setCameraIssue(null);
    try {
      api
        .getConfig()
        .then((cfg) => {
          frameCfg.current = { ...frameCfg.current, ...cfg.frame };
        })
        .catch(() => {});
      const s = await newSession();
      const c = makeClient();
      clientRef.current = c;
      c.connect(resolveWsUrl(s.ws_url));

      let stream: MediaStream;
      try {
        stream = await openCamera();
      } catch (cameraError) {
        const denied = cameraError instanceof DOMException && (cameraError.name === "NotAllowedError" || cameraError.name === "SecurityError");
        const issue = denied
          ? "Allow camera access in your browser settings, then tap Start again."
          : "No usable camera is available. Connect or enable a camera, then try again.";
        setCameraDenied(denied);
        setCameraIssue(issue);
        setError(issue);
        if (denied) sys("I need camera permission to help you", true);
        else sys("I could not find a usable camera", true);
        teardown();
        await api.endSession(s.session_id).catch(() => {});
        sessionRef.current = null;
        setPhase("idle");
        return;
      }
      streamRef.current = stream;
      const v = videoRef.current;
      if (v) {
        v.srcObject = stream;
        await v.play().catch(() => {});
      }
      const cam = stream.getVideoTracks()[0]?.getSettings().facingMode ?? "environment";
      startLoop();
      startLocation();
      startStatus(cam);
      wakeLock.current = await requestWakeLock();
      setPhase("running");
      phaseRef.current = "running";
      sys("Vision assistant started");
    } catch (e) {
      teardown();
      setError(friendlyError(e));
      sys(`Could not start. ${friendlyError(e)}`);
      setPhase("idle");
    }
  }, [makeClient, newSession, openCamera, startLocation, startLoop, startStatus, teardown]);

  const stop = useCallback(async () => {
    if (phaseRef.current !== "running") return;
    setPhase("stopping");
    teardown();
    const s = sessionRef.current;
    sessionRef.current = null;
    if (s) await api.endSession(s.session_id).catch(() => {});
    setFrameResult(null);
    setFps(0);
    setCurrentLocation(null);
    setNavigation(null);
    setPhase("idle");
    sys("Vision assistant stopped");
  }, [teardown]);

  // Re-acquire wake lock after tab becomes visible again.
  useEffect(() => {
    const onVis = async () => {
      if (document.visibilityState === "visible" && phaseRef.current === "running" && !wakeLock.current) {
        wakeLock.current = await requestWakeLock();
      }
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  useEffect(() => () => teardown(), [teardown]);

  /* ---------- emergency (FE-11) ---------- */
  const restEmergency = useCallback(async (trigger: "button" | "voice") => {
    try {
      const s = sessionRef.current ?? (await newSession());
      const l = latestLoc.current;
      await api.emergency({
        session_id: s.session_id,
        trigger,
        location: l ? { lat: l.lat, lng: l.lng, ...(l.accuracy_m !== undefined ? { accuracy_m: l.accuracy_m } : {}) } : null,
        note: null,
      });
      if (emergencyStateRef.current !== "acknowledged") {
        updateEmergency("acknowledged");
        sys("Your emergency alert was sent.");
      }
    } catch {
      updateEmergency("failed");
      sys("I could not reach your guardian. Please call for help.", true);
    }
  }, [newSession, updateEmergency]);

  const triggerEmergency = useCallback(
    async (trigger: "button" | "voice") => {
      speech.unlock();
      if (["sending", "waiting_ack", "retrying"].includes(emergencyStateRef.current)) return;
      updateEmergency("sending");
      const c = clientRef.current;
      if (c && c.status() === "open") {
        c.send("emergency", { trigger });
        updateEmergency("waiting_ack");
        if (emergencyTimer.current) clearTimeout(emergencyTimer.current);
        emergencyTimer.current = setTimeout(() => {
          emergencyTimer.current = null;
          updateEmergency("retrying");
          sys("Trying to reach your guardian");
          void restEmergency(trigger);
        }, EMERGENCY_ACK_TIMEOUT_MS);
      } else {
        await restEmergency(trigger);
      }
    },
    [restEmergency, updateEmergency],
  );

  /* ---------- Ask AI / Read text (FE-12) ---------- */
  const askAI = useCallback(async (mode: AskMode, question: string) => {
    const s = sessionRef.current;
    if (!s) return sys("Start the assistant first.");
    setBusy("thinking");
    sys("Let me look");
    try {
      const r = await api.ask({ session_id: s.session_id, question, mode, image: null });
      speech.speak({ text: r.spoken_text, priority: PRIORITY.answer, source: "answer" });
    } catch (e) {
      speech.speak({ text: friendlyError(e), priority: PRIORITY.answer, source: "answer" });
    } finally {
      setBusy(null);
    }
  }, []);

  const readText = useCallback(async () => {
    const s = sessionRef.current;
    if (!s) return sys("Start the assistant first.");
    const b64 = encodeFrame()?.image ?? lastFrameB64.current;
    if (!b64) return sys("I don't have a camera view yet.");
    setBusy("thinking");
    sys("Let me look");
    try {
      const r = await api.ocr(b64ToJpegBlob(b64), s.session_id);
      speech.speak({ text: r.spoken_text, priority: PRIORITY.answer, source: "answer" });
    } catch (e) {
      speech.speak({ text: e instanceof ApiError ? friendlyError(e) : "I could not read that.", priority: PRIORITY.answer, source: "answer" });
    } finally {
      setBusy(null);
    }
  }, [encodeFrame]);

  const navigateTo = useCallback(async (destination: string) => {
    const session = sessionRef.current;
    const origin = latestLoc.current;
    if (!session) return sys("Start the assistant before choosing a destination.");
    if (!origin) return sys("I need your location before I can plan a route.");
    setBusy("thinking");
    sys("Planning your walking route.");
    try {
      const route = await api.navigate({
        session_id: session.session_id,
        origin: { lat: origin.lat, lng: origin.lng },
        destination: destination.trim(),
        profile: "walking",
      });
      nextNavigationStepRef.current = 0;
      setNavigation(route);
      const firstStep = route.steps[0];
      if (firstStep) {
        nextNavigationStepRef.current = 1;
        speech.speak({ text: firstStep.spoken_text, priority: PRIORITY.answer, source: "answer" });
      }
    } catch (cause) {
      speech.speak({ text: friendlyError(cause), priority: PRIORITY.answer, source: "answer" });
    } finally { setBusy(null); }
  }, []);

  const setWarningVerbosity = useCallback((value: WarningVerbosity) => {
    warningVerbosityRef.current = value;
    setWarningVerbosityState(value);
    try { localStorage.setItem("vision-guardian-verbosity", value); } catch { /* Storage is optional. */ }
  }, []);

  const setVoiceLanguage = useCallback((value: VoiceLanguage) => {
    setVoiceLanguageState(value);
    speech.setVoice({ lang: value, rate: voiceRate });
    try { localStorage.setItem("vision-guardian-language", value); } catch { /* Storage is optional. */ }
  }, [voiceRate]);

  const setVoiceRate = useCallback((value: number) => {
    const rate = Math.min(1.4, Math.max(0.7, value));
    setVoiceRateState(rate);
    speech.setVoice({ lang: voiceLanguage, rate });
    try { localStorage.setItem("vision-guardian-rate", String(rate)); } catch { /* Storage is optional. */ }
  }, [voiceLanguage]);

  const routeIntent = useCallback(
    (intent: VoiceIntent, transcript: string) => {
      switch (intent) {
        case "emergency":
          return triggerEmergency("voice");
        case "read_text":
          return readText();
        case "describe":
          return askAI("describe", transcript);
        case "path_check":
          return askAI("path_check", transcript);
        case "ask":
          return askAI("question", transcript);
        case "stop_speaking":
          return speech.stop();
        case "repeat":
          return speech.repeatLast();
      }
    },
    [askAI, readText, triggerEmergency],
  );

  const pushToTalk = useCallback(async () => {
    speech.unlock();
    if (!speechInput.isSupported()) return false;
    beep(880, 110);
    setBusy("listening");
    try {
      const r = await speechInput.listenOnce({ timeoutMs: 7000 });
      setBusy(null);
      await routeIntent(r.intent, r.transcript);
    } catch {
      setBusy(null);
      sys("I didn't catch that.");
    }
    return true;
  }, [routeIntent]);

  return {
    phase,
    conn,
    cameraDenied,
    cameraIssue,
    error,
    frameResult,
    fps,
    encodeMs,
    lastFrameId,
    emergency,
    busy,
    facing,
    videoRef,
    start,
    stop,
    triggerEmergency,
    pushToTalk,
    askAI,
    readText,
    navigateTo,
    navigation,
    currentLocation,
    warningVerbosity,
    setWarningVerbosity,
    voiceLanguage,
    setVoiceLanguage,
    voiceRate,
    setVoiceRate,
    recognitionSupported: speechInput.isSupported(),
    mockMode: config.useMocks,
  };
}
