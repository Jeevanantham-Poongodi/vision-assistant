# API Contracts — AI-Powered Vision & Guardian Navigation Assistant

**Version:** 1.0 (hackathon)  ·  **Contract owner:** Coder 3 (Backend)  ·  **Status:** Frozen for MVP. Changes go through the owner and are announced to the whole team.

This file is the single source of truth that lets all five of us work in parallel. If your code and this file disagree, this file wins. Change the file first, then the code.

---

## Table of contents

1. Conventions
2. Shared enums
3. Thresholds and rules (risk, distance, direction, speech)
4. Core data models (JSON)
5. WebSocket API: user device channel
6. WebSocket API: guardian channel
7. REST API
8. Internal Python module contracts (how isolated scripts plug into FastAPI)
9. Frontend service contracts (TypeScript)
10. Supabase schema and seed data
11. Error model
12. Performance budgets
13. Mock data fixtures
14. Priority map (what is MVP)

---

## 1. Conventions

| Item | Rule |
|---|---|
| Base URL (dev) | `http://localhost:8000` (or the HTTPS tunnel URL, see note below) |
| REST prefix | `/api/v1` |
| WebSocket prefix | `/ws` |
| JSON keys | `snake_case` everywhere, including in TypeScript types |
| IDs | UUID v4 strings, except `frame_id` and `track_id`, which are integers |
| REST timestamps | ISO 8601 UTC strings, e.g. `"2026-10-08T10:15:30.120Z"` |
| Real-time timestamps (`ts`) | Unix epoch **milliseconds** (integer) |
| Distances | meters, float, rounded to 1 decimal place. `null` when unknown |
| Coordinates | Image: pixels in the frame as it was sent (origin top-left). Geo: WGS84 `lat`/`lng` |
| Images over JSON | Base64-encoded JPEG **without** the `data:image/jpeg;base64,` prefix |
| Auth (MVP) | None. The seeded demo user and guardian IDs (section 10) are passed explicitly. Do not ship this beyond the demo |
| CORS | Backend allows the Vite dev origin and the tunnel origin |
| Supabase access | **Backend only.** The frontend never talks to Supabase directly; the service-role key stays on the server |

> **HTTPS note.** Browsers only allow camera and microphone access (`getUserMedia`, Web Speech) in a secure context. `localhost` counts as secure. A phone on your Wi-Fi hitting `http://192.168.x.x` does **not**. For the phone demo, put both frontend and backend behind HTTPS (a `cloudflared`/`ngrok` tunnel, or `mkcert` + `vite --https`). WebSockets then use `wss://`. `python -m tools.tunnels` starts both Cloudflare tunnels and prints the frontend `.env` values; set `ALLOWED_ORIGIN_REGEX` so new tunnel URLs pass CORS. Guide: `docs/07_HTTPS_DEMO.md`.

---

## 2. Shared enums

### 2.1 `ObjectClass` (MVP = YOLOv8 COCO subset)

`class_name` is the YOLO COCO label in `snake_case`. `spoken_name` is what the voice says. Classes not in this table are dropped by the detector.

| `class_name` | `spoken_name` | `category` |
|---|---|---|
| `person` | person | `person` |
| `bicycle` | bicycle | `vehicle` |
| `car` | car | `vehicle` |
| `motorcycle` | motorcycle | `vehicle` |
| `bus` | bus | `vehicle` |
| `truck` | truck | `vehicle` |
| `traffic_light` | traffic light | `signal` |
| `stop_sign` | stop sign | `signal` |
| `fire_hydrant` | fire hydrant | `obstacle` |
| `bench` | bench | `obstacle` |
| `chair` | chair | `obstacle` |
| `dining_table` | table | `obstacle` |
| `potted_plant` | plant pot | `obstacle` |
| `backpack` | bag | `obstacle` |
| `suitcase` | suitcase | `obstacle` |
| `dog` | dog | `animal` |
| `cow` | cow | `animal` |
| `bottle` | bottle | `other` |

> Door, staircase, pole, tree and road obstacle are **not** COCO classes. They need a custom-trained model and are P2 (see section 14). Do not promise them in the demo unless that model exists.

### 2.2 `Category`
`person` · `vehicle` · `obstacle` · `animal` · `signal` · `other`

### 2.3 `Direction` (5 zones on normalised horizontal centre `cx_norm = center_x / frame_width`)

| Value | `cx_norm` range | Spoken (position) | Spoken (motion "from …") |
|---|---|---|---|
| `left` | `[0.00, 0.20)` | "on your left" | "from your left" |
| `slight_left` | `[0.20, 0.40)` | "slightly to your left" | "from your left" |
| `center` | `[0.40, 0.60]` | "directly ahead" | "from ahead" |
| `slight_right` | `(0.60, 0.80]` | "slightly to your right" | "from your right" |
| `right` | `(0.80, 1.00]` | "on your right" | "from your right" |

`center`, `slight_left` and `slight_right` together form the **walking corridor**.

### 2.4 `DistanceZone`

| Value | Range (m) | Meaning |
|---|---|---|
| `very_close` | `< 1.0` | Very close |
| `near` | `1.0 – < 2.0` | Near |
| `medium` | `2.0 – < 5.0` | Medium |
| `far` | `>= 5.0` | Far |
| `unknown` | `distance_m` is `null` | Could not estimate |

### 2.5 `Motion`
`approaching` · `receding` · `stationary` · `unknown` (fewer than 3 frames of history for this track)

### 2.6 `RiskLevel` (ordered high → low)
`critical` · `high` · `medium` · `low`

### 2.7 `AlertType`
`hazard` (auto-created from critical/high warnings) · `emergency` (user-triggered) · `assistance_request` (AI low confidence, P2) · `system` (e.g. user device went offline)

### 2.8 `AlertStatus`
`open` · `acknowledged` · `resolved`

### 2.9 `VoiceIntent` (resolved on the client by `speech.ts`, section 9)

| Intent | Example phrases | Action |
|---|---|---|
| `emergency` | "emergency", "help me", "SOS" | Send `emergency` over WS immediately. Never waits on the network for an AI call |
| `read_text` | "read this", "read the sign", "what does it say" | `POST /api/v1/ocr` with the current frame |
| `path_check` | "is the path clear", "can I walk" | `POST /api/v1/ask` with `mode: "path_check"` |
| `describe` | "describe my surroundings", "what is around me" | `POST /api/v1/ask` with `mode: "describe"` |
| `ask` | anything else | `POST /api/v1/ask` with `mode: "question"` |
| `stop_speaking` | "stop", "quiet", "silence" | Cancel the TTS queue (local only) |
| `repeat` | "repeat", "say again" | Re-speak the last utterance (local only) |

---

## 3. Thresholds and rules

These values live in the backend config and are exposed by `GET /api/v1/config` so the frontend, QA and the pitch deck all use the same numbers.

### 3.1 Risk rules (evaluated top to bottom; first match wins)

| # | Condition | `risk_level` | `priority` |
|---|---|---|---|
| R1 | Any object in the walking corridor with `distance_m < 1.0` | `critical` | 100 |
| R2 | `category == vehicle` and `motion == approaching` and `distance_m < 3.0` (any direction) | `critical` | 100 |
| R3 | `category == vehicle` and `motion == approaching` and `distance_m < 5.0` | `high` | 80 |
| R4 | Any object in the walking corridor with `1.0 <= distance_m < 2.0` | `high` | 80 |
| R5 | `category in (vehicle, animal)` and `distance_m < 5.0` | `medium` | 50 |
| R6 | Any object in the walking corridor with `2.0 <= distance_m < 5.0` | `medium` | 50 |
| R7 | Everything else, including `distance_m == null` | `low` | 20 |

`risk_score` (0.0–1.0) is a continuous companion value for sorting and UI only: `priority / 100`, plus up to `+0.1` for higher confidence or faster approach, capped at 1.0.

### 3.2 Speech and warning policy (applied by the backend risk engine)

| Rule | Value |
|---|---|
| Max warnings returned per `frame_result` | 2, sorted by `priority` descending |
| `low` risk | Never auto-spoken (`speak: false`). Available to Q&A only |
| Cooldown key | `track_id` if present, otherwise `class_name + direction` |
| Cooldown per key | `critical` 1500 ms · `high` 3000 ms · `medium` 6000 ms |
| Escalation | If the risk level of a key goes up, speak immediately and ignore the cooldown |
| `interrupt` | `true` only for `critical` (the client cancels current speech) |
| Client-side safety net | Drop a queued utterance older than 2000 ms. Skip an exact duplicate `message` within 3000 ms. Max queue length 2 |
| Path clear | `path_clear = true` when no object with `distance_m < 3.0` is in the walking corridor |

### 3.3 Hazard alerts to the guardian
A `hazard` alert is persisted and pushed to guardians only for `critical`/`high` warnings, at most **one per 10 s per cooldown key**, so the guardian feed does not flood. Content: `title` = the warning's `short_text`, `message` = the spoken sentence, `risk_level` = the warning's level, `location` = the last known location, and the stored `payload` holds the triggering `Detection`, the `Warning` and the `frame_id`. With `PIPELINE=stub` the mock car warning (`high`) raises one hazard alert per 10 s while frames stream.

### 3.4 User online / offline
- The user is **online** while their socket is connected and they have sent any valid message within the last **10 s**. This is why an idle phone pings every 5 s.
- **Socket closed:** guardians get `user_status` with `online: false` immediately. If the phone is not back within 10 s, a `system` alert is raised. A reconnect inside that window (the client's backoff is 0.5–4 s) raises nothing. A connection replaced by a newer one (`4002`) never shows as offline, and ending the session through `POST /sessions/{id}/end` raises no alert.
- **Socket open but silent for more than 10 s:** `online: false` and the same alert. The next message from the phone sets `online: true` again.
- The alert is `type: "system"`, `risk_level: "high"`, title "User went offline", with the last known location. At most **one per offline period** and **one per 60 s per session**.
- REST `Session.user_online` follows the same rule.

---

## 4. Core data models

### 4.1 `BBox`
```json
{ "x1": 412, "y1": 118, "x2": 598, "y2": 402 }
```
Pixel coordinates in the submitted frame. `x1 < x2`, `y1 < y2`.

### 4.2 `Detection`
```json
{
  "track_id": 7,
  "class_name": "car",
  "spoken_name": "car",
  "category": "vehicle",
  "confidence": 0.91,
  "bbox": { "x1": 520, "y1": 190, "x2": 636, "y2": 300 },
  "cx_norm": 0.903,
  "direction": "right",
  "distance_m": 4.2,
  "distance_zone": "medium",
  "distance_method": "pinhole",
  "motion": "approaching",
  "approach_speed_mps": 1.4,
  "risk_level": "high",
  "risk_score": 0.86
}
```

| Field | Type | Notes |
|---|---|---|
| `track_id` | int \| null | From YOLO tracking (ByteTrack). `null` if tracking is off |
| `class_name` | `ObjectClass` | |
| `spoken_name` | string | From the table in 2.1 |
| `category` | `Category` | |
| `confidence` | float 0–1 | Detector confidence. Threshold 0.40 |
| `bbox` | `BBox` | |
| `cx_norm` | float 0–1 | Box centre x divided by frame width |
| `direction` | `Direction` | |
| `distance_m` | float \| null | Approximate |
| `distance_zone` | `DistanceZone` | |
| `distance_method` | `"pinhole"` \| `"depth_model"` \| `"edge_clipped"` \| `"none"` | `edge_clipped` = box touches the top/bottom frame edge, so the estimate is a lower bound |
| `motion` | `Motion` | |
| `approach_speed_mps` | float \| null | Positive = getting closer |
| `risk_level` | `RiskLevel` | |
| `risk_score` | float 0–1 | |

### 4.3 `Warning`
```json
{
  "warning_id": "6c1f3a8e-6a0b-4a52-9b0e-6a1fd2b7a001",
  "track_id": 7,
  "class_name": "car",
  "risk_level": "high",
  "priority": 80,
  "message": "Warning. Car approaching from your right, approximately 4 meters away. Please move slightly to your left.",
  "short_text": "Car · right · 4.2 m · approaching",
  "speak": true,
  "interrupt": false,
  "rule": "R3"
}
```

| Field | Notes |
|---|---|
| `message` | Exactly what TTS should say. Built by `speech/phrases.py` (Coder 4) |
| `short_text` | For screens (guardian feed, debug overlay). Not spoken |
| `speak` | `false` means display only |
| `interrupt` | `true` means cancel current speech and say this now |
| `rule` | Which rule in 3.1 fired. For debugging and QA |

### 4.4 `FrameResult`
```json
{
  "frame_id": 1042,
  "frame_size": { "width": 640, "height": 480 },
  "ts_captured": 1759900530120,
  "ts_processed": 1759900530310,
  "latency_ms": 190,
  "inference_ms": 74,
  "detections": [ "Detection", "..." ],
  "warnings": [ "Warning", "..." ],
  "path_clear": false,
  "clear_distance_m": 2.1,
  "low_confidence_scene": false
}
```

| Field | Notes |
|---|---|
| `ts_captured` | Copied from the client's `frame` message |
| `latency_ms` | `ts_processed - ts_captured` (both clocks are approximate; good enough for a demo) |
| `clear_distance_m` | Distance to the nearest object in the walking corridor. `null` if the corridor is empty |
| `low_confidence_scene` | P2 trigger for `assistance_request`. Always `false` in the MVP |

### 4.5 `Location`
```json
{ "lat": 11.0168, "lng": 76.9558, "accuracy_m": 12.0, "heading_deg": 87.0, "speed_mps": 0.9, "ts": 1759900530000 }
```
`heading_deg` and `speed_mps` may be `null`.

### 4.6 `Alert`
```json
{
  "alert_id": "0b8d6a41-31b0-4d0e-9c8e-6b9c0f3e8f11",
  "session_id": "5d0e2b7c-8f6a-4f1e-9a43-0c6f6d1b2a10",
  "user_id": "11111111-1111-1111-1111-111111111111",
  "type": "emergency",
  "risk_level": "critical",
  "title": "Emergency triggered",
  "message": "Arun pressed the emergency button.",
  "location": { "lat": 11.0168, "lng": 76.9558, "accuracy_m": 12.0 },
  "snapshot_b64": null,
  "status": "open",
  "created_at": "2026-10-08T10:15:30.120Z",
  "acknowledged_by": null,
  "acknowledged_at": null
}
```
`snapshot_b64` is a small JPEG (max 320 px wide) of the frame at alert time, if one is available. It is sent over WebSocket only and is not stored in the database (REST responses carry `null`). It comes from Coder 2's `make_thumbnail` (CV-11, boxes drawn); until that exists, the backend sends the plain frame scaled to 320 px.

### 4.7 `Session`
```json
{
  "session_id": "5d0e2b7c-8f6a-4f1e-9a43-0c6f6d1b2a10",
  "user_id": "11111111-1111-1111-1111-111111111111",
  "status": "active",
  "started_at": "2026-10-08T10:00:00.000Z",
  "ended_at": null,
  "device_info": { "user_agent": "Mozilla/5.0 ...", "platform": "android" },
  "user_online": true,
  "ws_url": "/ws/user/5d0e2b7c-8f6a-4f1e-9a43-0c6f6d1b2a10",
  "guardian_ws_url": "/ws/guardian/5d0e2b7c-8f6a-4f1e-9a43-0c6f6d1b2a10"
}
```

---

## 5. WebSocket API: user device channel

**URL:** `wss://<host>/ws/user/{session_id}`
Create the session first with `POST /api/v1/sessions`. One user socket per session. A second connection replaces the first, and the old one is closed with code `4002`.

### 5.1 Message envelope (both directions, both channels)
```json
{ "v": 1, "type": "frame", "ts": 1759900530120, "payload": { } }
```
Unknown `type` → server replies with an `error` message (`UNSUPPORTED_MESSAGE`) and keeps the socket open.

### 5.2 Client → server

| `type` | Payload | Frequency | Priority |
|---|---|---|---|
| `hello` | `{ "user_id": "uuid", "device_info": { ... } }` | Once, right after connecting | P0 |
| `frame` | `{ "frame_id": 1042, "image": "<b64 jpeg>", "width": 640, "height": 480 }` | Target 5 fps (see backpressure) | P0 |
| `location` | `Location` | Every 5 s or on 10 m movement | P1 |
| `status` | `{ "battery_pct": 64, "fps": 4.8, "camera": "environment" }` | Every 10 s | P1 |
| `emergency` | `{ "trigger": "button" \| "voice", "note": "optional" }` (the backend attaches the last `location` received on this socket) | On demand | P1 |
| `ping` | `{}` | Every **5 s** if idle (the backend marks the user offline after 10 s of silence, see 3.4) | P0 |

`location` is validated as a `Location` (4.5), kept as the session's latest position and relayed to guardians. `status` is kept for `user_status` (`battery_pct` must be 0–100 or `null`). An invalid `location` or `status` gets `error` `UNSUPPORTED_MESSAGE`. `emergency` creates an `emergency` alert (see 7.11) and is answered with `emergency_ack`; an invalid `trigger` gets `error` `UNSUPPORTED_MESSAGE`. **Any valid message from the phone counts as a sign of life** (see 3.4).

**Frame rules**
- JPEG, longest side ≤ 640 px, quality 0.6–0.7 (about 30–50 KB).
- **Backpressure:** at most **one frame in flight**. Send the next frame only after the `frame_result` for the previous one arrives, or after 1000 ms with no reply. Never queue frames on the client.
- The server also drops any frame that is older than 1000 ms when it reaches the pipeline. Age is measured against the clock offset seen since `hello` (the smallest server-receive time minus envelope `ts`), so the phone and laptop clocks do not need to match.
- **Latest frame wins:** while a frame is being processed, only the newest waiting frame is kept. Frames dropped this way, or as too old, get **no reply**; the client's 1000 ms rule above covers them.
- If the vision pipeline fails on a frame (or cannot be loaded), the server sends `error` `PIPELINE_ERROR` with that `frame_id`; the socket stays open.
- `frame_id` increases monotonically per session (starting at 1). `ts` in the envelope is the capture time.

### 5.3 Server → client

| `type` | Payload | When |
|---|---|---|
| `welcome` | `{ "session_id": "uuid", "config": { "target_fps": 5, "max_width": 640, "jpeg_quality": 0.65 } }` | After `hello` |
| `frame_result` | `FrameResult` | One per processed frame |
| `guardian_message` | `{ "message_id": "uuid", "guardian_name": "Priya", "text": "Move slightly right.", "spoken_text": "Your guardian says: Move slightly right." }` | When a guardian sends a message |
| `emergency_ack` | `{ "alert_id": "uuid", "status": "open" \| "acknowledged", "spoken_text": "Your guardian has been notified." }` | After `emergency` is stored, and again when a guardian acknowledges it |
| `error` | `{ "code": "INVALID_FRAME", "message": "...", "frame_id": 1042 }` | On a bad message. `frame_id` is `null` unless the error is about a frame. Text that is not a valid envelope (or a binary message) gets `UNSUPPORTED_MESSAGE` |
| `pong` | `{}` | Reply to `ping` |

**Speaking order on the client:** `frame_result.warnings` (critical first) > `guardian_message` > `emergency_ack` > Q&A/OCR answers.

### 5.4 Close codes

| Code | Meaning |
|---|---|
| `1000` | Normal close |
| `4001` | `SESSION_NOT_FOUND` or session already ended |
| `4002` | Replaced by a newer connection for the same session |
| `4003` | Protocol violation (e.g. no `hello` within 5 s, the first message is not `hello`, or `hello.user_id` is not the session's user) |

The client reconnects with exponential backoff: 0.5 s, 1 s, 2 s, 4 s, then every 5 s. It tells the user by voice "Connection lost, reconnecting" once, and "Connected" on recovery.

---

## 6. WebSocket API: guardian channel

**URL:** `wss://<host>/ws/guardian/{session_id}?guardian_id={uuid}`
Any number of guardian sockets per session. Closes with `4001` if the session is unknown or ended, or `guardian_id` is missing or not linked to the session's user (one code for all three, so a guardian cannot probe for sessions). Closes with `4003` if `FEATURE_GUARDIAN=false`, if no `hello` arrives within 5 s, or if its `guardian_id` differs from the query parameter.

Right after `welcome` the server sends the current `user_status` and, if one is known, the latest `location`, so a refreshed page is not empty. `ack_alert` follows the same rules as `PATCH /alerts/{alert_id}` (7.13); success shows up as `alert_updated`, failures as `error` (`ALERT_NOT_FOUND`, `INVALID_STATUS_TRANSITION`, or `UNSUPPORTED_MESSAGE` for a bad payload). `guardian_message` is accepted and ignored until BE-11. Each guardian has its own send queue: a guardian that cannot keep up misses snapshots, and one that falls behind repeatedly is closed with `1013`; this never slows the user's socket.

### 6.1 Client → server

| `type` | Payload | Priority |
|---|---|---|
| `hello` | `{ "guardian_id": "uuid" }` | P0 |
| `guardian_message` | `{ "text": "Turn right and continue straight." }` (1–200 chars) | P1 |
| `ack_alert` | `{ "alert_id": "uuid", "status": "acknowledged" \| "resolved" }` | P1 |
| `ping` | `{}` | P0 |

### 6.2 Server → client

| `type` | Payload | Rate | Priority |
|---|---|---|---|
| `welcome` | `{ "session": Session, "user": { "user_id": "uuid", "name": "Arun" }, "open_alerts": [Alert] }` | Once | P0 |
| `snapshot` | `{ "frame_id": 1042, "image": "<b64 jpeg>", "width": 640, "height": 480 }` | Max 2 per second (re-uses the user's frames: this is the MVP "live camera") | P1 |
| `frame_result` | `FrameResult` (same schema as section 4.4) | Max 2 per second | P1 |
| `alert` | `Alert` | On creation | P1 |
| `alert_updated` | `Alert` | On ack/resolve | P1 |
| `location` | `Location` | Relayed as received | P1 |
| `user_status` | `{ "online": true, "fps": 4.8, "latency_ms": 190, "battery_pct": 64, "last_seen": 1759900530120 }` | Every 2 s, and immediately when online/offline changes. `fps` and `latency_ms` are measured on the server over the last 5 s (`latency_ms`: receive to result sent, `null` when idle); `battery_pct` comes from the phone's `status` (`null` if unknown) | P1 |
| `message_delivered` | `{ "message_id": "uuid", "text": "..." }` | After a guardian message is forwarded to the user | P1 |
| `error` / `pong` | as in section 5 | | P0 |

> **Live video.** The MVP live view is the `snapshot` stream (2 fps). Real video and two-way voice over WebRTC is P2. If it is attempted, signalling messages (`webrtc_offer`, `webrtc_answer`, `webrtc_ice`, each with an SDP/ICE payload) are relayed through these same two sockets unchanged.

---

## 7. REST API

All paths are prefixed with `/api/v1`. FastAPI's auto docs at `/docs` must match this section.

### 7.1 Summary

| Method | Path | Purpose | Owner (logic) | Priority |
|---|---|---|---|---|
| GET | `/health` | Liveness and model status | C3 | P0 |
| GET | `/config` | Thresholds from section 3 | C3 | P0 |
| POST | `/sessions` | Start a user session | C3 | P0 |
| GET | `/sessions` | List sessions (filter by user, status) | C3 | P1 |
| GET | `/sessions/{session_id}` | Session details | C3 | P0 |
| POST | `/sessions/{session_id}/end` | End a session | C3 | P0 |
| POST | `/detect` | One image → `FrameResult` (Postman/QA, fallback) | C2 via C3 | P0 |
| POST | `/ask` | Voice question → spoken answer (Gemini) | C4 via C3 | P1 |
| POST | `/ocr` | Read text in an image | C4 via C3 | P1 |
| POST | `/emergency` | Trigger an emergency (REST fallback for the WS message) | C3 | P1 |
| GET | `/alerts` | List alerts | C3 | P1 |
| PATCH | `/alerts/{alert_id}` | Acknowledge or resolve | C3 | P1 |
| POST | `/sessions/{session_id}/guardian-message` | REST fallback for guardian messages | C3 | P1 |
| GET | `/guardians/{guardian_id}/users` | Users linked to a guardian | C3 | P1 |
| POST | `/navigate` | Walking route with spoken steps | C4 via C3 | P2 |
| POST | `/tts` | Server-side TTS fallback | C4 via C3 | P2 |
| POST | `/stt` | Server-side STT fallback | C4 via C3 | P2 |

### 7.2 `GET /health`
**200**
```json
{ "status": "ok", "version": "1.0.0", "models": { "yolo": "loaded", "ocr": "available", "gemini": "configured" }, "uptime_s": 1234 }
```
`models.*` is one of `loaded` / `available` / `configured` / `missing`. Return `status: "degraded"` if YOLO is not loaded.

### 7.3 `GET /config`
**200**
```json
{
  "frame": { "target_fps": 5, "max_width": 640, "jpeg_quality": 0.65, "max_in_flight": 1 },
  "direction_zones": { "left": [0.0, 0.2], "slight_left": [0.2, 0.4], "center": [0.4, 0.6], "slight_right": [0.6, 0.8], "right": [0.8, 1.0] },
  "distance_zones_m": { "very_close": 1.0, "near": 2.0, "medium": 5.0 },
  "speech": { "cooldown_ms": { "critical": 1500, "high": 3000, "medium": 6000 }, "max_queue": 2, "stale_ms": 2000, "dedupe_ms": 3000 },
  "detector": { "model": "yolov8n.pt", "confidence": 0.4, "classes": ["person", "car", "..."] }
}
```

### 7.4 `POST /sessions`
**Request**
```json
{ "user_id": "11111111-1111-1111-1111-111111111111", "device_info": { "user_agent": "Mozilla/5.0 ...", "platform": "android" } }
```
**201** → `Session` (section 4.7)
**404** `USER_NOT_FOUND`
If the user already has an `active` session, that session is returned with **200** instead of creating a new one.

### 7.5 `GET /sessions?user_id={uuid}&status=active`
**200** → `{ "items": [Session], "count": 1 }`

### 7.6 `GET /sessions/{session_id}`
**200** → `Session` · **404** `SESSION_NOT_FOUND`

### 7.7 `POST /sessions/{session_id}/end`
**200** → `Session` with `status: "ended"`. Open sockets for the session are closed with code `1000`. Ending an already-ended session returns **200** with the session unchanged, so the client can safely retry. **404** `SESSION_NOT_FOUND`

### 7.8 `POST /detect`
`multipart/form-data`

| Field | Type | Required |
|---|---|---|
| `image` | file (JPEG/PNG, ≤ 5 MB) | yes |
| `session_id` | string | no. When given, tracking/motion and cooldowns use that session's state. Without it, `motion` is always `"unknown"` |

**200** → `FrameResult`. Without `session_id`, `frame_id` is 0. With `session_id`, the session's own pipeline is used (shared with its WebSocket), `frame_id` counts up per session (1, 2, …), and the result becomes the session's latest frame for `/ask` and `/ocr`. With `PIPELINE=stub` the response is the 13.1 mock.
**400** `INVALID_FRAME` (not JPEG/PNG, empty, or > 5 MB) · **404** `SESSION_NOT_FOUND` (unknown or ended session) · **503** `MODEL_NOT_READY` · **500** `PIPELINE_ERROR` (vision failed on this image)

### 7.9 `POST /ask`
**Request**
```json
{
  "session_id": "5d0e2b7c-8f6a-4f1e-9a43-0c6f6d1b2a10",
  "question": "Is there a vehicle near me?",
  "mode": "question",
  "image": null
}
```
| Field | Notes |
|---|---|
| `mode` | `"question"` \| `"describe"` \| `"path_check"` |
| `image` | Optional base64 JPEG. If `null`, the backend uses the latest frame and `FrameResult` cached for the session (must be < 3 s old, otherwise **409** `NO_RECENT_FRAME`) |

**200**
```json
{
  "answer_id": "a3e1c2d4-...",
  "question": "Is there a vehicle near me?",
  "answer": "Yes. A car is approximately 4 meters away on your right, and it is coming closer.",
  "spoken_text": "Yes. A car is approximately 4 meters away on your right, and it is coming closer.",
  "mode": "question",
  "source": "gemini",
  "grounded_on": { "frame_id": 1042, "detection_count": 2 },
  "latency_ms": 1850
}
```
- `source` is `"gemini"`, or `"fallback"` when Gemini timed out (6 s) or failed. The fallback answer is built from the detections with templates, so the user always gets an answer.
- **Grounding rule:** distances and directions in the answer must come from our `detections`, never from Gemini's own estimate.
- **409** `NO_RECENT_FRAME` · **404** `SESSION_NOT_FOUND`. A Gemini failure is **not** an HTTP error; it returns 200 with `source: "fallback"`.

### 7.10 `POST /ocr`
`multipart/form-data`: `image` (file, required), `session_id` (optional), `interpret` (bool, default `true`)

**200**
```json
{
  "text": "COMPUTER SCIENCE\nDEPARTMENT",
  "lines": [
    { "text": "COMPUTER SCIENCE", "confidence": 0.92, "bbox": { "x1": 80, "y1": 120, "x2": 560, "y2": 180 } },
    { "text": "DEPARTMENT", "confidence": 0.89, "bbox": { "x1": 150, "y1": 190, "x2": 490, "y2": 240 } }
  ],
  "spoken_text": "The sign says Computer Science Department. There is an arrow pointing left.",
  "interpreted": true,
  "source": "tesseract+gemini",
  "latency_ms": 2100
}
```
- No text found → **200** with `lines: []`, `text: ""` and `spoken_text: "I could not find any readable text. Try holding the camera closer and steady."`
- `source` is `"tesseract"` when `interpret` is false or Gemini failed. `spoken_text` is then the cleaned OCR text, read as-is.
- **400** `INVALID_FRAME`

### 7.11 `POST /emergency`
**Request**
```json
{ "session_id": "uuid", "trigger": "button", "location": { "lat": 11.0168, "lng": 76.9558, "accuracy_m": 12.0 }, "note": null }
```
**201** → `Alert` with `type: "emergency"`, `risk_level: "critical"`. The backend also pushes `alert` to every guardian socket and `emergency_ack` to the user socket. The location is the request's, or else the last one the phone sent. **404** `SESSION_NOT_FOUND` for an unknown or ended session. **Repeated presses:** while an emergency is `open`, another one within 10 s (REST or WebSocket) returns that same alert and re-sends its `emergency_ack` instead of creating a duplicate.

### 7.12 `GET /alerts`
Query: `session_id`, `user_id`, `type`, `status`, `limit` (default 50, max 200), `before` (ISO time, for paging)
**200** → `{ "items": [Alert], "count": 12 }`, newest first.

### 7.13 `PATCH /alerts/{alert_id}`
**Request** `{ "status": "acknowledged", "guardian_id": "22222222-2222-2222-2222-222222222222" }`
**200** → `Alert`. Pushes `alert_updated` to guardians and, for emergencies, `emergency_ack` to the user.
**404** `ALERT_NOT_FOUND` (also when `guardian_id` is not linked to the alert's user, so alerts cannot be probed) · **409** `INVALID_STATUS_TRANSITION` (allowed: `open → acknowledged → resolved`, or `open → resolved`). The first acknowledgement records `acknowledged_by` and `acknowledged_at`. `emergency_ack` (`status: "acknowledged"`, "Your guardian has seen your emergency and is responding.") is sent once, when an emergency leaves `open`.

### 7.14 `POST /sessions/{session_id}/guardian-message`
**Request** `{ "guardian_id": "uuid", "text": "Stop and wait." }`
**202** → `{ "message_id": "uuid", "delivered": true }`. `delivered` is `false` if the user socket is offline (the message is not queued).

### 7.15 `GET /guardians/{guardian_id}/users`
**200**
```json
{ "items": [ { "user_id": "1111...", "name": "Arun", "relation": "brother", "active_session_id": "5d0e...", "online": true, "last_location": { "lat": 11.0168, "lng": 76.9558, "accuracy_m": 12.0 } } ] }
```

### 7.16 `POST /navigate` (P2)
**Request**
```json
{ "session_id": "uuid", "origin": { "lat": 11.0168, "lng": 76.9558 }, "destination": "Central Library", "profile": "walking" }
```
`destination` is either a place name (geocoded) or `{ "lat": ..., "lng": ... }`.
**200**
```json
{
  "route_id": "uuid",
  "destination_name": "Central Library",
  "total_distance_m": 240,
  "duration_s": 190,
  "steps": [
    { "index": 0, "maneuver": "depart", "distance_m": 20, "instruction": "Head north", "spoken_text": "Start walking straight for about 20 meters.", "location": { "lat": 11.0168, "lng": 76.9558 } }
  ],
  "geometry": { "type": "LineString", "coordinates": [[76.9558, 11.0168], [76.9560, 11.0170]] }
}
```
**404** `DESTINATION_NOT_FOUND`

### 7.17 `POST /tts` (P2)
**Request** `{ "text": "Hello", "lang": "en-IN" }` → **200** `audio/mpeg` body.

### 7.18 `POST /stt` (P2)
`multipart/form-data`: `audio` (webm/ogg/wav, ≤ 30 s), `lang` (default `en-IN`) → **200** `{ "text": "what is in front of me", "confidence": 0.88 }`

---

## 8. Internal Python module contracts

These are the seams between the isolated scripts (Coders 2 and 4) and the FastAPI app (Coder 3). Build to these signatures from day one and integration becomes a one-line import swap. Pydantic models live in `backend/schemas.py` (owned by Coder 3) and mirror section 4 exactly.

### 8.1 Folder layout
```
backend/
├── main.py                  # C3: app, routers, startup (loads models once)
├── config.py                # C3: settings + thresholds (section 3)
├── schemas.py               # C3: Pydantic models = section 4
├── errors.py                # C3: AppError + error handlers (section 11)
├── routers/                 # C3: REST routers (sessions.py, ...)
├── live/
│   ├── hub.py               # C3: session hub, user + guardian sockets
│   ├── user_ws.py           # C3
│   └── guardian_ws.py       # C3
├── db/
│   ├── client.py            # C3: Supabase client
│   └── repo.py              # C3: sessions, alerts, locations
├── vision/
│   ├── detector.py          # C2
│   ├── direction.py         # C2
│   ├── distance.py          # C2
│   ├── tracking.py          # C2
│   └── pipeline.py          # C2: the one entry point C3 calls
├── safety/
│   └── risk_engine.py       # C2
├── speech/
│   └── phrases.py           # C4: Warning sentence builder
├── ocr/
│   └── reader.py            # C4
├── ai/
│   ├── gemini.py            # C4
│   └── prompts.py           # C4
└── navigation/
    └── maps.py              # C4 (P2)
```

### 8.2 Vision (Coder 2)
```python
# vision/detector.py
@dataclass
class RawDetection:
    track_id: int | None
    class_name: str            # snake_case, section 2.1
    confidence: float
    bbox: tuple[int, int, int, int]   # x1, y1, x2, y2 in pixels

class Detector:
    def __init__(self, model_path: str = "yolov8n.pt", conf: float = 0.4,
                 classes: list[str] | None = None, device: str = "cpu") -> None: ...
    def detect(self, frame_bgr: np.ndarray, track: bool = True) -> list[RawDetection]: ...
    # track=True uses model.track(persist=True). One Detector per session when tracking,
    # because the tracker state lives inside the model object.

# vision/direction.py
def get_direction(cx_norm: float) -> str: ...            # returns a Direction value

# vision/distance.py
def estimate_distance(class_name: str, bbox: tuple[int, int, int, int],
                      frame_w: int, frame_h: int,
                      focal_px: float) -> tuple[float | None, str, str]:
    """Returns (distance_m, distance_zone, distance_method)."""

# vision/tracking.py
class MotionTracker:
    def update(self, track_id: int | None, distance_m: float | None, ts_ms: int) -> tuple[str, float | None]:
        """Returns (motion, approach_speed_mps). Keeps ~1.5 s of history per track."""
    def prune(self, now_ms: int, max_age_ms: int = 3000) -> None: ...

# safety/risk_engine.py
def assess(det: dict) -> tuple[str, int, float, str]:
    """det is a Detection dict without risk fields.
    Returns (risk_level, priority, risk_score, rule_id)."""

class WarningSelector:
    def select(self, detections: list[dict], now_ms: int) -> list[dict]:
        """Applies section 3.2 (cooldown, escalation, max 2) and returns Warning dicts.
        Calls speech.phrases.build_warning_message() for 'message'."""

# vision/pipeline.py  <-- the ONLY thing Coder 3 calls for frames
class VisionPipeline:
    def __init__(self, focal_px: float, detector: Detector | None = None) -> None: ...
    def process(self, frame_bgr: np.ndarray, frame_id: int, ts_captured_ms: int) -> dict:
        """Synchronous, CPU-bound. Returns a dict that validates as FrameResult."""
```

### 8.3 Speech text, OCR, Gemini (Coder 4)
```python
# speech/phrases.py
def build_warning_message(det: dict, risk_level: str, rule_id: str) -> str: ...
def build_short_text(det: dict) -> str: ...
def format_distance(distance_m: float | None) -> str:
    # 0.7 -> "70 centimeters"; 1.0 -> "1 meter"; 3.6 -> "3 and a half meters"; 4.2 -> "4 meters"; None -> ""
def describe_scene_fallback(detections: list[dict], mode: str) -> str:
    # Template answer used when Gemini fails, e.g. "The path ahead appears clear for about 5 meters."

# ocr/reader.py
def read_text(image_bgr: np.ndarray) -> dict:
    """Returns {"text": str, "lines": [{"text", "confidence", "bbox"}]} (section 7.10 without spoken_text)."""

# ai/gemini.py
async def answer_question(question: str, mode: str, detections: list[dict],
                          image_jpeg: bytes | None, timeout_s: float = 6.0) -> tuple[str, str]:
    """Returns (answer_text, source) where source is 'gemini' or 'fallback'. Never raises."""

async def interpret_ocr(ocr_text: str, image_jpeg: bytes | None, timeout_s: float = 6.0) -> tuple[str, str]:
    """Returns (spoken_text, source). Never raises."""
```

### 8.4 Rules for every internal module
- No module except `db/` touches Supabase. No module except `live/` touches sockets.
- Vision and OCR functions are **synchronous**. Coder 3 runs them with `await asyncio.to_thread(...)` so the event loop never blocks.
- Models load **once** at startup (FastAPI lifespan), never per request.
- Every module ships a `if __name__ == "__main__":` demo that runs on a webcam or a sample image without FastAPI.

---

## 9. Frontend service contracts (TypeScript)

`frontend/src/types/contracts.ts` mirrors section 4 one-to-one (owned by Coder 1, reviewed by Coder 3).

```ts
export type Direction = "left" | "slight_left" | "center" | "slight_right" | "right";
export type DistanceZone = "very_close" | "near" | "medium" | "far" | "unknown";
export type Motion = "approaching" | "receding" | "stationary" | "unknown";
export type RiskLevel = "critical" | "high" | "medium" | "low";
export type Category = "person" | "vehicle" | "obstacle" | "animal" | "signal" | "other";
export type AlertType = "hazard" | "emergency" | "assistance_request" | "system";
export type AlertStatus = "open" | "acknowledged" | "resolved";
export type VoiceIntent = "emergency" | "read_text" | "path_check" | "describe" | "ask" | "stop_speaking" | "repeat";

export interface BBox { x1: number; y1: number; x2: number; y2: number; }

export interface Detection {
  track_id: number | null; class_name: string; spoken_name: string; category: Category;
  confidence: number; bbox: BBox; cx_norm: number; direction: Direction;
  distance_m: number | null; distance_zone: DistanceZone;
  distance_method: "pinhole" | "depth_model" | "edge_clipped" | "none";
  motion: Motion; approach_speed_mps: number | null; risk_level: RiskLevel; risk_score: number;
}

export interface Warning {
  warning_id: string; track_id: number | null; class_name: string; risk_level: RiskLevel;
  priority: number; message: string; short_text: string; speak: boolean; interrupt: boolean; rule: string;
}

export interface FrameResult {
  frame_id: number; frame_size: { width: number; height: number };
  ts_captured: number; ts_processed: number; latency_ms: number; inference_ms: number;
  detections: Detection[]; warnings: Warning[];
  path_clear: boolean; clear_distance_m: number | null; low_confidence_scene: boolean;
}

export interface GeoPoint { lat: number; lng: number; accuracy_m?: number; }
export interface Location extends GeoPoint { heading_deg: number | null; speed_mps: number | null; ts: number; }

export interface Alert {
  alert_id: string; session_id: string; user_id: string; type: AlertType; risk_level: RiskLevel;
  title: string; message: string; location: GeoPoint | null; snapshot_b64: string | null;
  status: AlertStatus; created_at: string; acknowledged_by: string | null; acknowledged_at: string | null;
}

export interface Envelope<T = unknown> { v: 1; type: string; ts: number; payload: T; }
```

### 9.1 `services/speech.ts` (owned by Coder 4, used by Coder 1)
```ts
export interface Utterance { text: string; priority: number; interrupt?: boolean; source: "warning" | "guardian" | "system" | "answer"; }

export interface SpeechService {
  unlock(): void;                       // call inside the first user tap (required on iOS/Chrome)
  speak(u: Utterance): void;            // applies queue rules from section 3.2
  speakWarnings(ws: Warning[]): void;   // filters speak=false, sorts by priority
  stop(): void;
  repeatLast(): void;
  isSpeaking(): boolean;
  setVoice(opts: { lang?: string; rate?: number; pitch?: number }): void;  // default lang "en-IN", rate 1.05
}

// Utterance priorities: warnings use Warning.priority (100 / 80 / 50);
// guardian_message 70; emergency_ack and system messages 60; Q&A / OCR answers 40.
// A higher-priority utterance waits for the current one to finish unless interrupt=true.

export interface ListenResult { transcript: string; confidence: number; intent: VoiceIntent; }
export interface SpeechInput {
  isSupported(): boolean;
  listenOnce(opts?: { lang?: string; timeoutMs?: number }): Promise<ListenResult>;  // push-to-talk
  parseIntent(transcript: string): VoiceIntent;
}
```

### 9.2 `services/ws.ts` (owned by Coder 1)
```ts
export interface RealtimeClient {
  connect(url: string): void;
  send<T>(type: string, payload: T): void;
  on<T>(type: string, handler: (payload: T, env: Envelope<T>) => void): () => void;  // returns unsubscribe
  status(): "connecting" | "open" | "closed";
}
// VITE_USE_MOCKS=true swaps in MockRealtimeClient, which replays /src/mocks/*.json on a timer.
```

### 9.3 Environment variables
```
# frontend/.env
VITE_API_BASE=https://<tunnel>/api/v1
VITE_WS_BASE=wss://<tunnel>/ws
VITE_USE_MOCKS=false
VITE_DEMO_USER_ID=11111111-1111-1111-1111-111111111111
VITE_DEMO_GUARDIAN_ID=22222222-2222-2222-2222-222222222222
VITE_MAPBOX_TOKEN=            # P1/P2, or use Leaflet + OpenStreetMap with no token

# backend/.env
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=    # server only, never in the frontend
GEMINI_API_KEY=
GEMINI_MODEL=                 # a current Flash-tier model; keep it configurable
YOLO_MODEL=yolov8n.pt
CAMERA_FOCAL_PX=              # from Coder 2's calibration script
TESSERACT_CMD=/usr/bin/tesseract
MAPBOX_TOKEN=                 # P2
ALLOWED_ORIGINS=http://localhost:5173,https://<tunnel>
ALLOWED_ORIGIN_REGEX=              # demo only: ^https://[a-z0-9-]+\.trycloudflare\.com$
```

---

## 10. Supabase schema and seed data

Run as one SQL migration (`backend/db/migrations/001_init.sql`). The backend uses the service-role key, so RLS policies are not needed for the demo. Enable RLS anyway and add no policies, so a leaked anon key cannot read anything.

```sql
create extension if not exists "pgcrypto";

create table app_users (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  role        text not null check (role in ('user', 'guardian')),
  phone       text,
  created_at  timestamptz not null default now()
);

create table guardian_links (
  guardian_id uuid not null references app_users(id) on delete cascade,
  user_id     uuid not null references app_users(id) on delete cascade,
  relation    text,
  created_at  timestamptz not null default now(),
  primary key (guardian_id, user_id)
);

create table sessions (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references app_users(id) on delete cascade,
  status       text not null default 'active' check (status in ('active', 'ended')),
  device_info  jsonb not null default '{}'::jsonb,
  started_at   timestamptz not null default now(),
  ended_at     timestamptz
);
create index sessions_user_status_idx on sessions (user_id, status);

create table alerts (
  id               uuid primary key default gen_random_uuid(),
  session_id       uuid references sessions(id) on delete set null,
  user_id          uuid not null references app_users(id) on delete cascade,
  type             text not null check (type in ('hazard', 'emergency', 'assistance_request', 'system')),
  risk_level       text not null check (risk_level in ('critical', 'high', 'medium', 'low')),
  title            text not null,
  message          text not null,
  payload          jsonb not null default '{}'::jsonb,   -- e.g. the Detection that triggered it
  lat              double precision,
  lng              double precision,
  accuracy_m       real,
  status           text not null default 'open' check (status in ('open', 'acknowledged', 'resolved')),
  acknowledged_by  uuid references app_users(id),
  acknowledged_at  timestamptz,
  created_at       timestamptz not null default now()
);
create index alerts_session_created_idx on alerts (session_id, created_at desc);
create index alerts_status_idx on alerts (status);

create table location_pings (
  id          bigint generated always as identity primary key,
  session_id  uuid not null references sessions(id) on delete cascade,
  lat         double precision not null,
  lng         double precision not null,
  accuracy_m  real,
  heading_deg real,
  speed_mps   real,
  recorded_at timestamptz not null default now()
);
create index location_pings_session_idx on location_pings (session_id, recorded_at desc);

alter table app_users       enable row level security;
alter table guardian_links  enable row level security;
alter table sessions        enable row level security;
alter table alerts          enable row level security;
alter table location_pings  enable row level security;

-- Seed data (fixed IDs used by frontend mocks, Postman and the demo)
insert into app_users (id, name, role) values
  ('11111111-1111-1111-1111-111111111111', 'Arun', 'user'),
  ('22222222-2222-2222-2222-222222222222', 'Priya', 'guardian');
insert into guardian_links (guardian_id, user_id, relation) values
  ('22222222-2222-2222-2222-222222222222', '11111111-1111-1111-1111-111111111111', 'sister');
```

**What is stored and what is not**
- Stored: users, guardian links, sessions, alerts (hazard alerts throttled per section 3.3), location pings (at most one every 10 s per session).
- Not stored: camera frames, per-frame detections. They stay in memory. Say this in the pitch: it is a privacy point judges like.

**How the backend uses Supabase (BE-09)**
- Only with `FEATURE_ALERTS_DB=true` and both `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` set; otherwise everything stays in memory.
- Memory is the working copy: every request reads from it, so no request waits on Supabase. Each write goes to memory first and is then sent to Supabase **in order** by one background task (an alert never arrives before its session).
- At startup the backend loads users, guardian links, **active** sessions and their **open** alerts. After a restart the phone reconnects to the same session and guardians still see open alerts. Ended sessions are not loaded.
- If Supabase is unreachable, the app keeps working from memory and logs one warning per 30 s with a count of failed writes; **writes made during the outage are not retried**. At startup it falls back to the seed users above.
- Check the setup with `python -m tools.check_supabase` (from `backend/`).

---

## 11. Error model

### 11.1 REST error body (every non-2xx response, including validation errors)
```json
{ "error": { "code": "SESSION_NOT_FOUND", "message": "Session 5d0e... does not exist or has ended.", "details": {} } }
```
Coder 3 adds exception handlers so FastAPI's default 422 body is converted to this shape with `code: "VALIDATION_ERROR"` and the field errors in `details` as `{"errors": [{"loc": ["body", "user_id"], "msg": "...", "type": "uuid_parsing"}]}`. Backend code raises `errors.AppError(code, message)`; the HTTP status comes from the table below. Unhandled exceptions return `INTERNAL` with a generic message; the stack trace goes to the server log only.

### 11.2 Error codes

| Code | HTTP | Where |
|---|---|---|
| `VALIDATION_ERROR` | 422 | Any REST |
| `INVALID_FRAME` | 400 / WS | Image cannot be decoded, wrong size, > 5 MB |
| `USER_NOT_FOUND` | 404 | `/sessions` |
| `SESSION_NOT_FOUND` | 404 / WS 4001 | Session routes, sockets |
| `ALERT_NOT_FOUND` | 404 | `/alerts/{id}` |
| `INVALID_STATUS_TRANSITION` | 409 | `PATCH /alerts/{id}` |
| `NO_RECENT_FRAME` | 409 | `/ask` without an image |
| `DESTINATION_NOT_FOUND` | 404 | `/navigate` |
| `MODEL_NOT_READY` | 503 | `/detect` before YOLO loads |
| `UNSUPPORTED_MESSAGE` | WS | Unknown `type` |
| `PIPELINE_ERROR` | WS / 500 | Vision crash on one frame (the socket stays open) |
| `INTERNAL` | 500 | Anything else |
| `NOT_FOUND` | 404 | Unknown path (raised by the framework) |
| `METHOD_NOT_ALLOWED` | 405 | Wrong HTTP method on a known path (raised by the framework) |
| `BAD_REQUEST` | 400 | Any other client error raised by the framework |

---

## 12. Performance budgets (laptop CPU, YOLOv8n, 640 px)

| Stage | Budget |
|---|---|
| Client capture + JPEG encode | ≤ 30 ms |
| Network upload (LAN/tunnel) | ≤ 80 ms |
| Decode + YOLO + tracking + distance + risk | ≤ 150 ms |
| Result back to client | ≤ 50 ms |
| **Frame → warning on screen** | **≤ 400 ms** |
| **Frame → speech starts** | **≤ 1 s** |
| Throughput | ≥ 4 fps sustained for 5 minutes |
| `/ask` (Gemini) | ≤ 4 s typical, 6 s timeout then fallback |
| `/ocr` | ≤ 3 s |

If the laptop has a CUDA GPU, set `device="cuda"` and raise `target_fps` to 8.

---

## 13. Mock data fixtures

Coder 1 and Member 5 put these in `frontend/src/mocks/` and `backend/tests/fixtures/`. Ready-made copies are in `member5-starter-kit/`. **Every mock file stores the full envelope** (`v`, `type`, `ts`, `payload`), so the mock client can replay any of them the same way. Sections 13.2 and 13.3 show only the payload to save space. Coder 3's stub pipeline (`PIPELINE=stub`) returns `frame_result.vehicle_right.json` before the real model is wired in; the backend copy is `backend/live/fixtures/frame_result.vehicle_right.json`.

### 13.1 `frame_result.vehicle_right.json` (envelope as received over WS)
```json
{
  "v": 1,
  "type": "frame_result",
  "ts": 1759900530310,
  "payload": {
    "frame_id": 1042,
    "frame_size": { "width": 640, "height": 480 },
    "ts_captured": 1759900530120,
    "ts_processed": 1759900530310,
    "latency_ms": 190,
    "inference_ms": 74,
    "detections": [
      {
        "track_id": 7, "class_name": "car", "spoken_name": "car", "category": "vehicle",
        "confidence": 0.91, "bbox": { "x1": 520, "y1": 190, "x2": 636, "y2": 300 }, "cx_norm": 0.903,
        "direction": "right", "distance_m": 4.2, "distance_zone": "medium", "distance_method": "pinhole",
        "motion": "approaching", "approach_speed_mps": 1.4, "risk_level": "high", "risk_score": 0.86
      },
      {
        "track_id": 3, "class_name": "person", "spoken_name": "person", "category": "person",
        "confidence": 0.88, "bbox": { "x1": 290, "y1": 60, "x2": 360, "y2": 420 }, "cx_norm": 0.508,
        "direction": "center", "distance_m": 2.1, "distance_zone": "medium", "distance_method": "pinhole",
        "motion": "stationary", "approach_speed_mps": 0.0, "risk_level": "medium", "risk_score": 0.52
      }
    ],
    "warnings": [
      {
        "warning_id": "6c1f3a8e-6a0b-4a52-9b0e-6a1fd2b7a001", "track_id": 7, "class_name": "car",
        "risk_level": "high", "priority": 80,
        "message": "Warning. Car approaching from your right, approximately 4 meters away. Please move slightly to your left.",
        "short_text": "Car · right · 4.2 m · approaching", "speak": true, "interrupt": false, "rule": "R3"
      },
      {
        "warning_id": "6c1f3a8e-6a0b-4a52-9b0e-6a1fd2b7a002", "track_id": 3, "class_name": "person",
        "risk_level": "medium", "priority": 50,
        "message": "Person about 2 meters directly ahead.",
        "short_text": "Person · ahead · 2.1 m", "speak": true, "interrupt": false, "rule": "R6"
      }
    ],
    "path_clear": false,
    "clear_distance_m": 2.1,
    "low_confidence_scene": false
  }
}
```

### 13.2 `frame_result.critical_obstacle.json` (payload shown; the file stores the full envelope)
```json
{
  "frame_id": 1100, "frame_size": { "width": 640, "height": 480 },
  "ts_captured": 1759900542000, "ts_processed": 1759900542160, "latency_ms": 160, "inference_ms": 70,
  "detections": [
    {
      "track_id": 12, "class_name": "chair", "spoken_name": "chair", "category": "obstacle",
      "confidence": 0.79, "bbox": { "x1": 230, "y1": 210, "x2": 420, "y2": 480 }, "cx_norm": 0.507,
      "direction": "center", "distance_m": 0.7, "distance_zone": "very_close", "distance_method": "edge_clipped",
      "motion": "stationary", "approach_speed_mps": 0.0, "risk_level": "critical", "risk_score": 1.0
    }
  ],
  "warnings": [
    {
      "warning_id": "9a7e...", "track_id": 12, "class_name": "chair", "risk_level": "critical", "priority": 100,
      "message": "Stop. Chair about 70 centimeters directly ahead.",
      "short_text": "Chair · ahead · 0.7 m", "speak": true, "interrupt": true, "rule": "R1"
    }
  ],
  "path_clear": false, "clear_distance_m": 0.7, "low_confidence_scene": false
}
```

### 13.3 `frame_result.clear.json` (payload shown; the file stores the full envelope)
```json
{
  "frame_id": 1200, "frame_size": { "width": 640, "height": 480 },
  "ts_captured": 1759900560000, "ts_processed": 1759900560140, "latency_ms": 140, "inference_ms": 66,
  "detections": [], "warnings": [], "path_clear": true, "clear_distance_m": null, "low_confidence_scene": false
}
```

### 13.4 `alert.emergency.json` (WS `alert` payload)
Use the `Alert` example in section 4.6.

### 13.5 `guardian_message.json`
```json
{ "v": 1, "type": "guardian_message", "ts": 1759900600000,
  "payload": { "message_id": "f1e2...", "guardian_name": "Priya", "text": "Turn right and continue straight.", "spoken_text": "Your guardian says: Turn right and continue straight." } }
```

### 13.6 `user_status.json`
```json
{ "v": 1, "type": "user_status", "ts": 1759900600000,
  "payload": { "online": true, "fps": 4.8, "latency_ms": 190, "battery_pct": 64, "last_seen": 1759900599800 } }
```

### 13.7 Warning sentence golden set (QA and Coder 4 unit tests)

| Input (class, direction, distance, motion, rule) | Expected `message` |
|---|---|
| car, right, 4.2, approaching, R3 | Warning. Car approaching from your right, approximately 4 meters away. Please move slightly to your left. |
| motorcycle, left, 2.6, approaching, R2 | Warning. Motorcycle approaching from your left, approximately 2 and a half meters away. Please move slightly to your right. |
| chair, center, 0.7, stationary, R1 | Stop. Chair about 70 centimeters directly ahead. |
| person, center, 2.1, stationary, R6 | Person about 2 meters directly ahead. |
| person, slight_left, 1.4, stationary, R4 | Person about 1 and a half meters slightly to your left. |
| dog, right, 3.8, stationary, R5 | Dog about 4 meters on your right. |
| bus, center, 2.8, approaching, R2 | Warning. Bus approaching from ahead, approximately 3 meters away. Please stop and step aside. |
| bench, slight_right, null, unknown, R7 | *(not spoken: low risk)* |

Rounding rule: below 1 m → nearest 10 cm in centimeters; 1–3 m → nearest half meter; 3 m and above → nearest whole meter.

---

## 14. Priority map

| Priority | Scope | Contract sections |
|---|---|---|
| **P0 — MVP (must work in the demo)** | Camera feed → WS frames → YOLO detection → direction → approximate distance → motion → risk → spoken warning. `/detect` for Postman. Health, config, sessions | 2, 3, 4.1–4.4, 4.7, 5 (`hello`, `frame`, `frame_result`, `ping`), 7.2–7.8, 8.2, 8.3 (`phrases.py`), 9 |
| **P1 — Strong demo** | Guardian dashboard (snapshot live view, alerts, location, status), guardian voice messages, emergency, Ask AI (Gemini), OCR, voice commands | 5 (rest), 6, 7.9–7.15, 10 |
| **P2 — Stretch** | Navigation, WebRTC video/voice, server TTS/STT, assistance requests on low confidence, custom classes (stairs, door, pole), metric depth model | 7.16–7.18, 6 (WebRTC note) |

**Rule:** nobody starts P1 work until the P0 pipeline runs end-to-end on a phone. Nobody starts P2 until P1 is demo-ready.
