/** FE-04 accessible user screen: 70% Start/Stop area, 30% Emergency (1 s long press). */
import { useEffect, useRef, useState } from "react";
import { Settings2 } from "lucide-react";
import { DetectionOverlay } from "@/components/DetectionOverlay";
import { pathBadgeText } from "@/components/detection-text";
import { onSpoken, speech, speechInput, speechInstalled } from "@/services/speech-bridge";
import { vibrate } from "@/lib/browser";
import { useUserAssistant } from "./useUserAssistant";

const HOLD_MS = 1000;

export function UserApp() {
  const a = useUserAssistant();
  const { recognitionSupported, voiceLanguage, currentLocation, navigateTo, navigation, busy } = a;
  const [caption, setCaption] = useState("");
  const [destinationStatus, setDestinationStatus] = useState("");
  const [pendingDestination, setPendingDestination] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [holding, setHolding] = useState(false);
  const destinationAsked = useRef(false);
  const holdTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const off = onSpoken((t) => setCaption(t));
    return () => {
      off();
    };
  }, []);

  const running = a.phase === "running";

  useEffect(() => {
    if (!running) {
      destinationAsked.current = false;
      setDestinationStatus("");
      setPendingDestination(null);
      return;
    }
    if (destinationAsked.current) return;
    destinationAsked.current = true;

    if (!recognitionSupported) {
      setDestinationStatus("Voice input is unavailable in this browser.");
      speech.speak({
        text: "Voice input is unavailable. Please enable speech recognition to plan a route by voice.",
        priority: 60,
        source: "system",
      });
      return;
    }

    let cancelled = false;
    setDestinationStatus("Listening for your destination…");
    speech.speak({
      text: "Where would you like to go? Please say your destination.",
      priority: 60,
      source: "system",
      interrupt: true,
    });
    void speechInput
      .listenOnce({ lang: voiceLanguage, timeoutMs: 15000 })
      .then(({ transcript }) => {
        if (cancelled) return;
        const destination = transcript.trim();
        if (!destination) {
          setDestinationStatus("No destination heard. Stop and restart the camera to try again.");
          return;
        }
        setPendingDestination(destination);
        setDestinationStatus(`Waiting for location to plan a route to ${destination}…`);
      })
      .catch(() => {
        if (cancelled) return;
        setDestinationStatus(
          "Microphone unavailable. Allow speech access, then restart the camera.",
        );
      });

    return () => {
      cancelled = true;
      destinationAsked.current = false;
    };
  }, [running, recognitionSupported, voiceLanguage]);

  useEffect(() => {
    if (!pendingDestination || !currentLocation) return;
    const destination = pendingDestination;
    setPendingDestination(null);
    setDestinationStatus(`Planning route to ${destination}…`);
    void navigateTo(destination);
  }, [pendingDestination, currentLocation, navigateTo]);

  useEffect(() => {
    if (navigation) setDestinationStatus(`Route guidance active: ${navigation.destination_name}`);
  }, [navigation]);

  useEffect(() => {
    if (!navigation || !caption || busy) return;
    const timer = setInterval(() => {
      speech.speak({ text: caption, priority: 40, source: "answer" });
    }, 1000);
    return () => clearInterval(timer);
  }, [navigation, caption, busy]);

  const onMainTap = () => {
    speech.unlock();
    if (running) void a.stop();
    else if (a.phase === "idle") void a.start();
  };

  const holdStart = () => {
    if (holdTimer.current) return;
    speech.unlock();
    vibrate(40);
    setHolding(true);
    holdTimer.current = setTimeout(() => {
      holdTimer.current = null;
      setHolding(false);
      vibrate([120, 60, 120]);
      void a.triggerEmergency("button");
    }, HOLD_MS);
  };
  const holdEnd = () => {
    if (holdTimer.current) clearTimeout(holdTimer.current);
    holdTimer.current = null;
    setHolding(false);
  };

  const mainLabel = running
    ? "Stop vision assistant"
    : a.phase === "starting"
      ? "Starting vision assistant"
      : "Start vision assistant";

  const emergencyText: Record<typeof a.emergency, string> = {
    idle: "Hold 1 second for help",
    sending: "Sending…",
    waiting_ack: "Alert sent · waiting for guardian",
    retrying: "Trying to reach your guardian…",
    acknowledged: "Guardian notified",
    failed: "Could not reach guardian",
  };

  return (
    <main className="user-app-shell flex min-h-dvh flex-col overflow-y-auto bg-background text-foreground">
      <div aria-live="assertive" aria-atomic="true" className="sr-only">
        {caption}
      </div>

      <header className="user-app-header flex items-center justify-between gap-2 px-4 py-2 text-base">
        <span className="flex items-center gap-2 font-bold">
          <span
            className={`inline-block h-3 w-3 rounded-full ${a.conn === "open" ? "bg-success" : a.conn === "connecting" ? "bg-risk-medium" : "bg-risk-low"}`}
          />
          {a.conn === "open" ? "Connected" : a.conn === "connecting" ? "Connecting" : "Offline"}
          {a.mockMode && <span className="rounded bg-secondary px-2 text-sm">MOCK</span>}
          {!speechInstalled && (
            <span role="status" className="text-destructive">
              Voice service unavailable
            </span>
          )}
        </span>
        <button
          type="button"
          onClick={() => {
            speech.unlock();
            const opening = !settingsOpen;
            setSettingsOpen(opening);
            if (opening)
              speech.speak({ text: "Voice settings opened.", priority: 60, source: "system" });
          }}
          aria-label={settingsOpen ? "Close voice settings" : "Open voice settings"}
          aria-expanded={settingsOpen}
          className="inline-flex min-h-11 min-w-11 items-center justify-center rounded-lg border-2 border-border"
        >
          <Settings2 aria-hidden="true" />
        </button>
      </header>

      {settingsOpen && (
        <section className="user-settings" aria-label="Voice settings">
          <label htmlFor="voice-language">Voice language</label>
          <select
            id="voice-language"
            value={a.voiceLanguage}
            onChange={(event) => {
              const language = event.target.value === "ta-IN" ? "ta-IN" : "en-IN";
              a.setVoiceLanguage(language);
              speech.speak({
                text: language === "ta-IN" ? "Tamil voice selected." : "English voice selected.",
                priority: 60,
                source: "system",
              });
            }}
          >
            <option value="en-IN">English (India)</option>
            <option value="ta-IN">Tamil (India)</option>
          </select>
          <label htmlFor="voice-rate">
            Voice speed <span>{a.voiceRate.toFixed(2)}×</span>
          </label>
          <input
            id="voice-rate"
            type="range"
            min="0.7"
            max="1.4"
            step="0.05"
            value={a.voiceRate}
            onChange={(event) => a.setVoiceRate(Number(event.target.value))}
          />
          <fieldset>
            <legend>Warning detail</legend>
            <label>
              <input
                type="radio"
                name="warning-verbosity"
                checked={a.warningVerbosity === "hazards"}
                onChange={() => a.setWarningVerbosity("hazards")}
              />{" "}
              Hazards only
            </label>
            <label>
              <input
                type="radio"
                name="warning-verbosity"
                checked={a.warningVerbosity === "everything"}
                onChange={() => a.setWarningVerbosity("everything")}
              />{" "}
              Everything
            </label>
          </fieldset>
        </section>
      )}

      {/* 70% Start/Stop */}
      <section className="user-camera-section relative flex-[7] p-3">
        <div className="user-camera-layout flex h-full min-h-0 w-full gap-3 rounded-[28px] border-2 border-border bg-background/50 p-2 shadow-[0_10px_30px_rgba(15,23,42,0.06)]">
          <button
            type="button"
            onClick={onMainTap}
            aria-label={mainLabel}
            disabled={a.phase === "starting" || a.phase === "stopping"}
            className={`user-camera-view relative flex h-full min-h-0 flex-1 flex-col items-center justify-center overflow-hidden rounded-[24px] border-4 ${running ? "border-foreground bg-card" : "border-primary bg-primary text-primary-foreground"}`}
          >
            <video
              ref={a.videoRef}
              muted
              playsInline
              aria-hidden="true"
              className={`absolute inset-0 h-full w-full object-contain ${running ? "opacity-100" : "hidden"}`}
            />
            {running && <DetectionOverlay frame={a.frameResult} />}

            {a.cameraDenied && !running && (
              <span className="relative z-10 flex flex-col items-center gap-3 px-6 text-center">
                <span className="text-4xl font-bold">Camera blocked</span>
                <span className="max-w-md text-xl">{a.cameraIssue}</span>
              </span>
            )}
            {!running && !a.cameraDenied && (
              <span className="relative z-10 px-6 text-center text-3xl font-bold">
                {a.phase === "starting" ? "Turning on camera…" : "Tap here to turn on the camera"}
              </span>
            )}
          </button>

          <aside className="user-instructions flex min-h-[300px] w-[32%] min-w-[220px] flex-col justify-between rounded-[24px] border-2 border-border bg-card p-4 text-left shadow-inner shadow-slate-200/50">
            <div className="space-y-3">
              <div className="rounded-2xl bg-primary/10 px-3 py-2 text-sm font-semibold text-primary">
                Instructions
              </div>
              {destinationStatus && (
                <div className="rounded-2xl bg-background/80 px-3 py-3 text-lg font-semibold text-foreground">
                  {destinationStatus}
                </div>
              )}
              {running && caption ? (
                <div className="rounded-2xl bg-background/80 px-3 py-3 text-lg font-semibold text-foreground">
                  {caption}
                </div>
              ) : (
                !destinationStatus && (
                  <div className="rounded-2xl bg-background/70 px-3 py-3 text-lg font-medium text-muted-foreground">
                    {running ? "Waiting for live guidance…" : "Tap start to begin the session."}
                  </div>
                )
              )}
              {a.error && (
                <div className="rounded-2xl bg-destructive/10 px-3 py-2 text-base font-medium text-destructive">
                  {a.error}
                </div>
              )}
              {running && a.busy && (
                <div className="rounded-2xl bg-background/80 px-3 py-2 text-base font-medium text-foreground">
                  {a.busy === "listening" ? "🎙 Listening…" : "Thinking…"}
                </div>
              )}
            </div>

            {running && a.frameResult && (
              <div
                className={`rounded-2xl px-3 py-3 text-base font-bold ${a.frameResult.path_clear ? "bg-success/10 text-success-foreground" : "bg-risk-high/15 text-risk-high"}`}
              >
                {pathBadgeText(a.frameResult)}
              </div>
            )}
          </aside>
        </div>
      </section>

      {/* 30% Emergency */}
      <section className="user-emergency-section flex-[3] p-3">
        <button
          type="button"
          aria-label="Emergency. Press and hold for one second to alert your guardian."
          onPointerDown={holdStart}
          onPointerUp={holdEnd}
          onPointerLeave={holdEnd}
          onPointerCancel={holdEnd}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && !e.repeat && holdStart()}
          onKeyUp={holdEnd}
          onContextMenu={(e) => e.preventDefault()}
          className="user-emergency-button relative flex h-full w-full select-none flex-col items-center justify-center overflow-hidden rounded-3xl bg-destructive text-destructive-foreground"
        >
          <span
            data-holding={holding}
            className="hold-fill absolute inset-0 bg-foreground/25"
            aria-hidden="true"
          />
          <span className="relative text-5xl font-bold">⚠ EMERGENCY</span>
          <span className="relative mt-1 text-xl font-semibold">{emergencyText[a.emergency]}</span>
          <span className="sr-only" aria-live="assertive">
            {emergencyText[a.emergency]}
          </span>
        </button>
      </section>
    </main>
  );
}
