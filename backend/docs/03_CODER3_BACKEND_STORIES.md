# Coder 3 — Backend (FastAPI + WebSockets + Supabase)

**Mission:** Build the spine everything plugs into: the FastAPI app, the two WebSocket channels, the session hub that connects a user to their guardians, the Supabase layer, and the HTTPS setup that makes the phone demo possible. You are also the **owner of `API_CONTRACTS.md`**.

**You own:** `backend/main.py`, `config.py`, `schemas.py`, `realtime/`, `db/`, `tools/`, deployment and tunnel setup. Your branch: `backend-api`. You are also the **Integration Captain** at every checkpoint (roadmap §6).
**Contract sections you implement:** all of 5, 6, 7, 10, 11; you enforce 1 and 12.
**You depend on:** Coder 2 (`VisionPipeline`), Coder 4 (`phrases`, `reader`, `gemini`).
**You unblock:** Coder 1 (the socket is the first thing they need), Member 5 (Postman).

> **Rule:** ship a working **echo/stub** version of each endpoint first, returning the contract's mock JSON. Real logic comes second. Coder 1 should never wait on you.

---

## P0 — MVP

### BE-01 · FastAPI skeleton, config and schemas
**As a** backend developer, **I want** a clean app structure with typed schemas, **so that** every teammate's module plugs in the same way.

**Acceptance criteria**
- [ ] Folder layout exactly as contract 8.1.
- [ ] `config.py` uses `pydantic-settings`, reads `backend/.env` (contract 9.3) and holds every threshold in contract section 3.
- [ ] `schemas.py` has Pydantic v2 models for every model in contract section 4 plus the request/response bodies in section 7, using `Literal[...]` for the enums.
- [ ] CORS from `ALLOWED_ORIGINS`.
- [ ] Lifespan handler loads YOLO once (through Coder 2's `Detector`) and warms it up; sets `app.state.models`.
- [ ] `GET /health` and `GET /config` per contract 7.2–7.3.
- [ ] `/docs` (Swagger) renders, and the paths match contract 7.1.

### BE-02 · Uniform error handling
**As a** frontend developer, **I want** every error in one shape, **so that** I handle failures in one place.

**Acceptance criteria**
- [ ] Custom `AppError(code, message, status, details)` exception, plus handlers for it, `RequestValidationError` (→ 422 `VALIDATION_ERROR`) and unhandled exceptions (→ 500 `INTERNAL`). All produce the body in contract 11.1.
- [ ] Stack traces go to logs, never to the response.

### BE-03 · Sessions REST
**As a** visually impaired user, **I want** a session to start when I open the app, **so that** my guardian can find and follow me.

**Acceptance criteria**
- [ ] `POST /sessions`, `GET /sessions`, `GET /sessions/{id}`, `POST /sessions/{id}/end` per contract 7.4–7.7, including "return the existing active session with 200".
- [ ] `user_online` comes from the in-memory hub, not the database.
- [ ] Ending a session closes its sockets with code 1000 and drops its `VisionPipeline`.

### BE-04 · User WebSocket with stub pipeline
**As a** frontend developer, **I want** a socket that accepts frames and answers with `frame_result`, **so that** I can build the live loop before the AI is ready.

**Acceptance criteria**
- [ ] `/ws/user/{session_id}` per contract 5: validates the session (else close 4001), requires `hello` within 5 s (else 4003), replies `welcome` with the frame config.
- [ ] A new connection for the same session replaces the old one (old closed with 4002).
- [ ] **Stub mode** (`PIPELINE=stub` in `.env`): every `frame` returns `frame_result.vehicle_right.json` with `frame_id` and timestamps filled in. Deliver this **first**.
- [ ] Handles `ping` → `pong`, and unknown types → `error UNSUPPORTED_MESSAGE` without closing.
- [ ] Bad base64 or an undecodable JPEG → `error INVALID_FRAME` with the `frame_id`; the socket stays open.

### BE-05 · Real vision pipeline in the socket loop
**As a** visually impaired user, **I want** my frames analysed fast enough to warn me in time, **so that** warnings arrive before I reach the hazard.

**Acceptance criteria**
- [ ] One `VisionPipeline` per session, created on `hello`, stored in the hub.
- [ ] Decode: base64 → `np.frombuffer` → `cv2.imdecode`. Reject > 5 MB.
- [ ] Run `pipeline.process()` with `await asyncio.to_thread(...)` so the event loop never blocks.
- [ ] **Latest-frame-wins:** if a new frame arrives while one is processing, keep only the newest pending frame and drop the rest. Drop any frame older than 1000 ms (from the envelope `ts`).
- [ ] Cache the latest frame (JPEG bytes) and `FrameResult` per session for `/ask` and `/ocr` (the 3 s freshness rule in contract 7.9).
- [ ] Log per-frame `decode_ms`, `pipeline_ms`, `total_ms`. Print a rolling fps/latency line every 5 s.
- [ ] Load test: a script sends 640×480 frames at 5 fps for 5 minutes. Server memory stays flat, p95 total ≤ 250 ms on the demo laptop.
- [ ] The load-test script is `tools/replay_ws.py --clip <video>`: it streams a recorded clip into `/ws/user` as if it were the phone. QA and Coder 2 reuse it for regression tests (roadmap §15).
- [ ] `DEBUG_SAVE_FRAMES=1` writes every 10th received frame to `backend/debug_frames/` (git-ignored), so Coder 2 can calibrate distance on the phone's real frames (roadmap §9.2).

### BE-06 · `POST /detect` for Postman and QA
**As the** QA member, **I want** to upload a single image and get a `FrameResult`, **so that** I can test detection without the frontend.

**Acceptance criteria**
- [ ] Multipart per contract 7.8. Optional `session_id` uses that session's pipeline; without it, a shared stateless pipeline is used (`motion: "unknown"`).
- [ ] 503 `MODEL_NOT_READY` before warm-up finishes.

### BE-07 · HTTPS for the phone demo
**As a** team, **we want** the app reachable over HTTPS from a phone, **so that** the browser allows camera and microphone access.

**Acceptance criteria**
- [ ] A documented one-command setup (`cloudflared tunnel --url http://localhost:8000` and one for Vite on 5173, or a single tunnel behind a reverse proxy).
- [ ] WebSockets work over `wss://` through the tunnel (test from mobile data, not only Wi-Fi).
- [ ] Fallback plan written down: laptop hotspot + `mkcert` certificates, in case venue Wi-Fi blocks tunnels.
- [ ] The README has a "demo day" checklist: start backend → start tunnel → update `.env` → open on phone → calibrate camera.

---

## P1 — Demo features

### BE-08 · Session hub and guardian WebSocket
**As a** guardian, **I want** to receive the user's live view, alerts, location and status in one stream, **so that** I can monitor them remotely.

**Acceptance criteria**
- [ ] `realtime/hub.py`: per session, one user socket plus a set of guardian sockets, and the latest frame/result/location/status. All sends are wrapped so one dead guardian socket never breaks the user loop.
- [ ] `/ws/guardian/{session_id}?guardian_id=` per contract 6: checks the guardian is linked to the session's user (`guardian_links`); replies `welcome` with session, user and `open_alerts`.
- [ ] Relays `snapshot` and `frame_result` (without the image) at max 2 per second, `location` as received, `user_status` every 2 s and immediately on online/offline change.
- [ ] User socket closes or goes silent for 10 s → `user_status.online = false` and a `system` alert.

### BE-09 · Supabase setup and repository layer
**As a** team, **we want** users, sessions and alerts stored in Postgres, **so that** the guardian sees history and the demo survives a page refresh.

**Acceptance criteria**
- [ ] Migration `db/migrations/001_init.sql` exactly as contract 10, including seed data with the fixed demo IDs.
- [ ] `db/repo.py` with typed functions: `get_user`, `get_linked_users`, `create_session`, `get_active_session`, `end_session`, `create_alert`, `list_alerts`, `update_alert_status`, `insert_location` (throttled to one per 10 s per session).
- [ ] Uses the service-role key from env. The key never appears in logs, responses or the frontend.
- [ ] Database calls run off the event loop (`asyncio.to_thread` around the sync `supabase` client, or use the async client).
- [ ] If Supabase is unreachable, the live warning loop **keeps working**; only persistence degrades, with a log warning.

### BE-10 · Hazard alerts and emergency flow
**As a** guardian, **I want** to be notified of dangerous situations and emergencies immediately, **so that** I can step in.

**Acceptance criteria**
- [ ] For each `critical`/`high` warning, create a `hazard` alert at most once per 10 s per cooldown key (contract 3.3). Store the triggering `Detection` in `payload`. Push `alert` with `snapshot_b64` (Coder 2's `make_thumbnail`).
- [ ] WS `emergency` and `POST /emergency` (contract 7.11) both: create the alert with the last known location, push `alert` to all guardians, send `emergency_ack` (`status: "open"`, `spoken_text: "Your guardian has been notified."`) to the user.
- [ ] `ack_alert` (WS) and `PATCH /alerts/{id}` both enforce allowed transitions (contract 7.13), then push `alert_updated` to guardians and, for an emergency, `emergency_ack` with `status: "acknowledged"` and `spoken_text: "Your guardian has seen your emergency and is responding."` to the user.
- [ ] `GET /alerts` with filters and paging (contract 7.12).

### BE-11 · Guardian messages to the user
**As a** guardian, **I want** my instructions spoken on the user's phone, **so that** I can guide them like I am beside them.

**Acceptance criteria**
- [ ] WS `guardian_message` and `POST /sessions/{id}/guardian-message` both validate 1–200 chars, then send `guardian_message` to the user with `spoken_text = "Your guardian says: " + text` and `guardian_name` from the database.
- [ ] Reply `message_delivered` to the sending guardian, or `delivered: false` if the user is offline.

### BE-12 · Wire Ask AI and OCR
**As a** visually impaired user, **I want** to ask questions and have text read, **so that** I can understand my surroundings beyond hazards.

**Acceptance criteria**
- [ ] `POST /ask` (contract 7.9): gets the image from the body or the session cache (409 `NO_RECENT_FRAME` if older than 3 s), gets detections from the cached `FrameResult` via Coder 2's `summarize_for_llm`, calls Coder 4's `answer_question()`. Never returns 5xx for a Gemini failure.
- [ ] `POST /ocr` (contract 7.10): decode → Coder 4's `read_text()` in a thread → `interpret_ocr()` when `interpret=true` → response.
- [ ] Both log `latency_ms` and `source`.

### BE-13 · Guardian lookup
**Acceptance criteria**
- [ ] `GET /guardians/{guardian_id}/users` per contract 7.15, combining `guardian_links`, the active session and the hub's online state and last location.

---

## P2 — Stretch
- **BE-14** `assistance_request` alerts when `FrameResult.low_confidence_scene` stays true for 3 s; the user hears "I need assistance to determine the safest direction. I have asked your guardian."
- **BE-15** WebRTC signalling relay (`webrtc_offer` / `webrtc_answer` / `webrtc_ice`) between the two sockets.
- **BE-16** Wire `/navigate`, `/tts`, `/stt` to Coder 4's modules.
- **BE-17** Simple token auth (signed demo tokens per role) replacing raw IDs.

---

## Definition of done (every story)
- Endpoint visible in `/docs` and matching the contract.
- Request and response saved in Member 5's Postman collection, with at least one error case.
- Works through the HTTPS tunnel, not just `localhost`.
- No blocking call (CV, OCR, DB, HTTP) on the event loop.
