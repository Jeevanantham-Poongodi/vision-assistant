# Coder 1 — Frontend (React + TypeScript + Vite + Tailwind)

**Mission:** Build the two screens people actually touch: the **user app** (camera and voice, used by someone who cannot see the screen) and the **guardian dashboard** (used by a sighted helper). Start against mocks and swap to the real socket as soon as Coder 3's echo server is up.

**You own:** `frontend/` (everything except `src/services/speech.ts` and `src/features/voice/`, which Coder 4 owns and you consume). Your branch: `frontend-ui`.
**Contract sections you implement:** 4, 5, 6, 9, 13.
**You depend on:** Coder 3 (WebSocket and REST), Coder 4 (`speech.ts`).
**You unblock:** the whole live demo. Nothing is demoable without your camera page.

> **Design principle for the user app:** the screen is for the judges and the guardian, not for the user. Every user action must work with **zero visual feedback**: big targets, voice confirmation for every action, and screen-reader compatibility.

---

## P0 — MVP

### FE-01 · Project scaffold, routing and mock mode
**As a** frontend developer, **I want** a Vite + React + TS + Tailwind app with two routes and a mock switch, **so that** I can build every screen before the backend exists.

**Acceptance criteria**
- [ ] Routes: `/user` (user app) and `/guardian` (guardian dashboard). `/` redirects to `/user`. Also a dev-only `/dev/speech` route that hosts Coder 4's speech test page.
- [ ] `src/types/contracts.ts` matches contract section 9 exactly.
- [ ] `.env` variables from contract 9.3 are read through one `config.ts`.
- [ ] `VITE_USE_MOCKS=true` swaps in `MockRealtimeClient`, which replays the files in `src/mocks/` (contract 13) on a timer. No other code knows whether mocks are on.
- [ ] `npm run dev -- --host` serves the app on the LAN. `vite --https` (or the tunnel) is documented in the README for phone testing.

### FE-02 · Realtime client service
**As a** frontend developer, **I want** one typed WebSocket client, **so that** both screens share connection, reconnect and message handling.

**Acceptance criteria**
- [ ] Implements `RealtimeClient` (contract 9.2): `connect`, `send`, `on` (returns unsubscribe), `status`.
- [ ] Wraps every outgoing message in the envelope `{ v: 1, type, ts, payload }`.
- [ ] Reconnects with backoff 0.5 s → 1 s → 2 s → 4 s → every 5 s. Sends `hello` again after every reconnect.
- [ ] Sends `ping` every 15 s while idle.
- [ ] Handles close codes 4001/4002/4003 (contract 5.4): on 4001, create a new session via REST.

### FE-03 · Camera capture and frame streaming
**As a** visually impaired user, **I want** my phone's rear camera to stream to the AI as soon as I start, **so that** the system can watch the path for me.

**Acceptance criteria**
- [ ] On start: `POST /sessions` with the demo user ID, then connect to `ws_url` and send `hello`.
- [ ] Uses `getUserMedia({ video: { facingMode: "environment", width: 640, height: 480 } })`. Falls back to any camera on a laptop.
- [ ] Draws the video to an off-screen canvas, encodes JPEG at quality 0.65, longest side ≤ 640 px, strips the `data:` prefix, and sends a `frame` message.
- [ ] **Backpressure:** max one frame in flight. Send the next frame when its `frame_result` arrives, or after 1000 ms with no reply. Never build a queue.
- [ ] Shows the measured fps and `latency_ms` (from `frame_result`) in a small debug strip.
- [ ] Camera permission denied → speaks "I need camera permission to help you" and shows instructions.
- [ ] Stops the camera tracks and calls `POST /sessions/{id}/end` when the user taps Stop.

### FE-04 · Accessible user screen
**As a** visually impaired user, **I want** a screen I can operate without seeing it, **so that** I can start, stop and get help with simple gestures.

**Acceptance criteria**
- [ ] Layout: the top ~70% of the screen is one giant Start/Stop toggle. The bottom ~30% is a red **Emergency** button (Emergency is wired in FE-11).
- [ ] Every button has an `aria-label`. Tapping Start says "Vision assistant started". Tapping Stop says "Vision assistant stopped".
- [ ] A visually hidden `aria-live="assertive"` region mirrors each spoken warning, so screen-reader users get it too.
- [ ] High-contrast theme (WCAG AA contrast at least), text ≥ 20 px, no information carried by color alone.
- [ ] The first tap calls `speech.unlock()` (required for TTS on iOS and Chrome).
- [ ] Screen wake lock (`navigator.wakeLock`) is held while running, so the phone does not sleep mid-walk.
- [ ] Tested with TalkBack (Android) or VoiceOver (iOS): a tester with eyes closed can start, stop and trigger emergency.

### FE-05 · Speak warnings from frame results
**As a** visually impaired user, **I want** to hear important hazards as soon as they are detected, **so that** I can react in time.

**Acceptance criteria**
- [ ] On each `frame_result`, calls `speech.speakWarnings(payload.warnings)`. All queue, interrupt and dedupe rules live in `speech.ts`; do not duplicate them.
- [ ] A `critical` warning (`interrupt: true`) is heard within 1 s of the frame being captured, cutting off anything currently speaking.
- [ ] `guardian_message` payloads are spoken as `spoken_text` with priority 70.
- [ ] With mocks on, replaying `frame_result.vehicle_right.json` produces exactly the sentence in contract 13.1.

### FE-06 · Detection overlay (demo and debug view)
**As a** judge watching the demo, **I want** to see boxes, labels, distance and direction drawn on the video, **so that** I can see what the AI is thinking.

**Acceptance criteria**
- [ ] An SVG/canvas overlay on the video draws each `bbox`, scaled from `frame_size` to the displayed video size.
- [ ] Label format: `car · right · 4.2 m · ↗ approaching`.
- [ ] Colour by `risk_level` (critical red, high orange, medium yellow, low grey), **plus** a text or icon marker so color is never the only signal.
- [ ] Faint vertical lines at `cx_norm` 0.2 / 0.4 / 0.6 / 0.8 show the 5 direction zones, and the walking corridor is shaded.
- [ ] A toggle hides the overlay (the user does not need it; the judges do).
- [ ] A "Path clear" or "Nearest obstacle 2.1 m" badge uses `path_clear` and `clear_distance_m`.

---

## P1 — Demo features

### FE-07 · Guardian dashboard layout and session pick-up
**As a** guardian, **I want** to open one page and see the person I look after, **so that** I can watch over them remotely.

**Acceptance criteria**
- [ ] On load: `GET /guardians/{id}/users`. If the user has an `active_session_id`, connect to `/ws/guardian/{session_id}?guardian_id=...` and send `hello`. If not, show "Arun is not using the assistant right now" and poll every 5 s.
- [ ] Layout (desktop first, also usable on a tablet): live view (left, large) · map (right) · alert feed (bottom left) · user status and message box (bottom right).
- [ ] `welcome.open_alerts` populate the feed on connect.

### FE-08 · Live view from snapshots
**As a** guardian, **I want** to see what the user's camera sees, **so that** I can judge situations the AI is unsure about.

**Acceptance criteria**
- [ ] Renders `snapshot` images (≈ 2 fps) with the same detection overlay component from FE-06, driven by the guardian `frame_result` stream.
- [ ] Shows "Live · 2 fps · 190 ms" from `user_status`. If no snapshot arrives for 5 s, greys the image out and shows "Connection to user lost".

### FE-09 · Alert feed and emergency banner
**As a** guardian, **I want** hazards and emergencies to stand out and be acknowledgeable, **so that** I never miss a real problem.

**Acceptance criteria**
- [ ] New `alert` messages are prepended to the feed with time, type, risk badge, message and a thumbnail when `snapshot_b64` is set.
- [ ] `type: "emergency"` opens a full-width red banner with a repeating sound until the guardian clicks **Acknowledge**, which sends `ack_alert` (or `PATCH /alerts/{id}`). The banner closes on `alert_updated`.
- [ ] **Resolve** action for acknowledged alerts.
- [ ] The feed keeps the last 100 alerts. Older ones load via `GET /alerts?before=`.

### FE-10 · Talk to the user
**As a** guardian, **I want** to send short instructions that the user hears as speech, **so that** I can guide them through difficult spots.

**Acceptance criteria**
- [ ] A text box (max 200 chars) plus quick-phrase buttons: "Stop", "Wait", "Move slightly left", "Move slightly right", "Continue straight", "I'm watching, you're safe".
- [ ] Push-to-talk mic button uses `speechInput.listenOnce()` (Coder 4) to fill the text box, so the guardian can speak instead of type.
- [ ] Sends `guardian_message`. Shows "Delivered" on `message_delivered`, or "User offline, not delivered".

### FE-11 · Emergency from the user app
**As a** visually impaired user, **I want** to call for help with one press or one word, **so that** my guardian is alerted immediately.

**Acceptance criteria**
- [ ] The Emergency button needs a **long press of 1 s** (prevents pocket triggers), with a vibration (`navigator.vibrate`) at start and at confirm.
- [ ] Sends a WS `emergency` with `trigger: "button"` (the backend attaches the last `location` it received). If the socket is down, falls back to `POST /emergency` with the latest location in the body.
- [ ] Speaks `emergency_ack.spoken_text` when it arrives. If no ack within 3 s, says "Trying to reach your guardian" and retries once via REST.
- [ ] Voice trigger: when `listenOnce()` returns `intent: "emergency"`, the same flow runs with `trigger: "voice"`.

### FE-12 · Ask AI and Read Text controls *(built by Coder 4 in `frontend/src/features/voice/`; Coder 1 mounts it, see roadmap §1.2)*
**As a** visually impaired user, **I want** to ask questions and have signs read aloud, **so that** I understand more than just hazards.

**Acceptance criteria**
- [ ] Gesture: **double-tap anywhere** on the Start area = push-to-talk (`listenOnce()`), with a short beep at start. Document the gesture in the README and the pitch.
- [ ] Routes by intent (contract 2.9): `read_text` → `POST /ocr` with the current frame; `describe` / `path_check` / `ask` → `POST /ask`; `stop_speaking` / `repeat` → local `speech.ts` calls.
- [ ] While waiting, says "Let me look" once. Speaks `spoken_text` from the response with priority 40, so live hazard warnings still interrupt it.
- [ ] Browser without speech recognition (e.g. Firefox) → shows two big buttons, "Ask" (opens a text field) and "Read text", instead.

### FE-13 · Location sharing and guardian map
**As a** guardian, **I want** to see where the user is on a map, **so that** I can help them navigate or find them.

**Acceptance criteria**
- [ ] User app: `navigator.geolocation.watchPosition` with high accuracy. Sends `location` every 5 s or on 10 m movement.
- [ ] Guardian: map (Leaflet + OpenStreetMap needs no token; Mapbox if the token is set) with the user marker, an accuracy circle and a heading arrow. A trail of the last 20 points.
- [ ] Emergency alerts with a location drop a red pin.

### FE-14 · User status panel
**As a** guardian, **I want** to see if the user's device is online and healthy, **so that** I know whether the system is actually protecting them.

**Acceptance criteria**
- [ ] From `user_status`: online/offline dot plus text, fps, latency, battery, "last seen 3 s ago".
- [ ] Offline for > 10 s → the panel turns red and a `system` alert appears in the feed (sent by the backend).
- [ ] User app sends `status` every 10 s (battery from `navigator.getBattery()` where available, otherwise `null`).

---

## P2 — Stretch
- **FE-15** Navigation screen: destination by voice → `POST /navigate`, speak `steps[].spoken_text` as the user approaches each step location; route line on the guardian map.
- **FE-16** WebRTC live video and two-way audio between guardian and user, signalled over the existing sockets (contract 6 note).
- **FE-17** Settings: voice speed, language (`en-IN` / `ta-IN`), verbosity (hazards only vs. everything), with a spoken settings menu.

---

## Definition of done (every story)
- Types come from `contracts.ts`. No `any` on message payloads.
- Works in mock mode **and** against the real backend.
- Tested on at least one real Android phone (Chrome) over HTTPS.
- User-app stories: tested with eyes closed / screen reader on.
- Member 5 has the steps to reproduce it in the demo script.
