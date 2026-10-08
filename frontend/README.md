# Vision Guardian

ROLE: CODER 1 ONLY — FRONTEND

You are working as Coder 1 in a 5-member team building:

AI-Powered Vision & Guardian Navigation Assistant

Your responsibility is ONLY the frontend.

You must follow these project documents as the source of truth:

Team Plan — AI-Powered Vision & Guardian Navigation Assistant

API_CONTRACTS.md

01_CODER1_FRONTEND_STORIES.md

The API contract is the single source of truth for all API messages, endpoints, JSON structures, enums, thresholds, and frontend service contracts.

🚨 ABSOLUTE SCOPE RULE

You are CODER 1 ONLY.

Implement ONLY the work assigned to Coder 1 in 01_CODER1_FRONTEND_STORIES.md.

DO NOT implement, modify, replace, or simulate the responsibilities of other team members.

DO NOT BUILD CODER 2 WORK

Coder 2 owns:

YOLO object detection

object tracking

ByteTrack

distance estimation

pinhole calculation

direction calculation

motion calculation

approach speed calculation

risk engine

risk rules

WarningSelector

VisionPipeline

backend/vision/*

backend/safety/*

The frontend must only CONSUME the detection and warning data provided by the API/WebSocket contract.

Never implement these algorithms in the frontend.

DO NOT BUILD CODER 3 WORK

Coder 3 owns:

FastAPI backend

REST API implementation

WebSocket server

WebSocket routing

Supabase

database

sessions backend

alerts backend

backend configuration

backend authentication/session logic

backend deployment

server-side frame processing

backend error handlers

Do not create a replacement backend.

Do not create mock backend APIs that pretend to be the real backend.

Frontend mocks are allowed only where explicitly required by the Coder 1 story.

DO NOT BUILD CODER 4 WORK

Coder 4 owns:

src/services/speech.ts

src/features/voice/

speech queue implementation

TTS implementation

speech priority implementation

speech deduplication

speech interruption logic

speech recognition implementation

speechInput

Gemini integration

OCR implementation

warning sentence generation

backend/speech/

backend/ocr/

backend/ai/

navigation backend

Coder 1 only CONSUMES the interfaces provided by Coder 4.

DO NOT rewrite or replace Coder 4's implementation.

DO NOT create another speech engine.

DO NOT BUILD MEMBER 5 WORK

Member 5 owns:

QA documentation

Postman collection

golden-set testing

latency testing ownership

mock fixture ownership

QA stories

final QA documentation

You may make the frontend testable, but do not take ownership of Member 5's work.

CODER 1 RESPONSIBILITY

Your frontend responsibility consists of:

P0 — USER CAMERA APPLICATION

Build:

React

TypeScript

Vite

Tailwind

/user

camera capture

frame encoding

WebSocket client

frame streaming

frame result handling

detection overlay

warning display

integration with Coder 4 speech service

accessibility

Start/Stop

Wake Lock

basic emergency UI integration

The P0 goal is:

Camera
→ JPEG frame
→ WebSocket
→ backend
→ FrameResult
→ frontend
→ warning
→ Coder 4 speech service
→ user hears warning

This is the primary MVP flow.

P1 — GUARDIAN DASHBOARD

Only after the P0 frontend structure is complete, implement:

/guardian

guardian session pickup

live snapshot view

detection overlay

alert feed

emergency banner

acknowledge/resolve alerts

guardian → user messages

location/map

user status

Ask AI / Read Text frontend integration

emergency flow integration

P2 — DO NOT PRIORITIZE

Only create the frontend integration points for:

Navigation

WebRTC

Settings

Do not implement backend functionality for these.

Do not start P2 before P0 and P1 are complete.

REQUIRED FRONTEND STRUCTURE

Use the existing project structure if it already exists.

Do NOT unnecessarily rename, delete, or reorganize unrelated files.

The frontend should follow this conceptual structure:

frontend/
├── src/
│ ├── components/
│ ├── features/
│ ├── pages/
│ ├── services/
│ │ ├── ws.ts
│ │ ├── api.ts
│ │ └── config.ts
│ ├── types/
│ │ └── contracts.ts
│ ├── mocks/
│ └── App.tsx
├── .env
└── ...

IMPORTANT:

src/services/speech.ts belongs to Coder 4.

src/features/voice/ belongs to Coder 4.

DO NOT modify those areas unless a minimal integration import is required.

FE-01 — PROJECT SCAFFOLD AND ROUTING

Use:

React

TypeScript

Vite

Tailwind CSS

Required routes:

/

Redirect to:

/user

Required:

/user

User camera application.

Required:

/guardian

Guardian dashboard.

Development-only:

/dev/speech

This should host/use Coder 4's speech test page if that page exists.

Do not add authentication.

Do not add registration.

Do not add unnecessary login screens.

The API contract explicitly says MVP authentication is:

None

Use the seeded demo IDs from the contract.

FE-01 — ENVIRONMENT CONFIGURATION

Read environment variables through ONE frontend configuration module.

Required:

VITE_API_BASE

VITE_WS_BASE

VITE_USE_MOCKS

VITE_DEMO_USER_ID

VITE_DEMO_GUARDIAN_ID

VITE_MAPBOX_TOKEN

Do not access import.meta.env throughout the application.

Centralize configuration.

Never expose:

SUPABASE_SERVICE_ROLE_KEY

GEMINI_API_KEY

or any backend secret.

FE-01 — TYPES

Create:

src/types/contracts.ts

It must mirror the API contract section 9.

Use the exact enums and interfaces from the contract.

Required types include:

Direction

DistanceZone

Motion

RiskLevel

Category

AlertType

AlertStatus

VoiceIntent

BBox

Detection

Warning

FrameResult

GeoPoint

Location

Alert

Envelope

Do not invent incompatible field names.

Use snake_case exactly where the API contract specifies it.

Do not use any for API/WebSocket message payloads.

FE-02 — REALTIME CLIENT

Create:

src/services/ws.ts

Implement the exact frontend contract:

export interface RealtimeClient {
  connect(url: string): void;
  send<T>(type: string, payload: T): void;
  on<T>(
    type: string,
    handler: (payload: T, env: Envelope<T>) => void
  ): () => void;
  status(): "connecting" | "open" | "closed";
}


Every outgoing WebSocket message must use:

{
  "v": 1,
  "type": "...",
  "ts": 0,
  "payload": {}
}


Implement:

connection

message parsing

typed event listeners

unsubscribe

reconnect

reconnect backoff:

0.5 seconds

1 second

2 seconds

4 seconds

then every 5 seconds

hello after every reconnect

ping every 15 seconds while idle

close code handling

Handle:

1000

Normal close.

4001

Session not found/session ended.

Create a new session through REST when appropriate.

4002

Connection replaced.

4003

Protocol violation.

Do not create a second custom WebSocket architecture elsewhere.

There must be ONE reusable realtime client service.

FE-03 — CAMERA CAPTURE

On Start:

Create a session using:

POST /api/v1/sessions

using the demo user ID.

Receive the session.

Connect to:

ws_url

Send hello.

Start camera.

Camera constraints:

{
  video: {
    facingMode: "environment",
    width: 640,
    height: 480
  }
}


Provide laptop fallback if environment camera is unavailable.

Use:

navigator.mediaDevices.getUserMedia()

Draw video into an off-screen canvas.

Encode as JPEG.

JPEG quality:

0.65

Longest side:

<= 640px

Remove:

data:image/jpeg;base64,

before sending.

FE-03 — FRAME BACKPRESSURE

This is mandatory.

Maximum:

ONE frame in flight.

Do NOT create a frame queue.

Send the next frame only when:

frame_result for the previous frame arrives

OR

1000 ms passes without a response.

Never allow multiple outstanding frames.

Target:

Approximately 5 FPS.

Frame IDs must increase monotonically per session starting at 1.

FE-03 — DEBUG INFORMATION

Show, where appropriate for judges/development:

measured FPS

latency_ms

connection status

frame information

Do not expose unnecessary debug UI to the user by default.

FE-03 — CAMERA PERMISSION FAILURE

If camera permission is denied:

Use Coder 4's speech service:

"I need camera permission to help you"

Also show clear visual instructions.

Do not silently fail.

FE-03 — STOP

When Stop is pressed:

stop all camera tracks

stop frame sending

close/clean WebSocket connection appropriately

call:

POST /api/v1/sessions/{session_id}/end

Return UI to idle state.

FE-04 — ACCESSIBLE USER SCREEN

The user may be unable to see the screen.

Therefore the interface MUST work without visual feedback.

Design:

Approximately:

70%:

Large Start/Stop interaction area.

Approximately:

30%:

Emergency button.

Every button must have:

aria-label

The first user interaction must call:

speech.unlock()

Use the Coder 4 speech service.

Start:

"Vision assistant started"

Stop:

"Vision assistant stopped"

Use:

aria-live="assertive"

for important warnings/status.

Requirements:

high contrast

WCAG AA

minimum text size approximately 20px

do not communicate important information using colour alone

large touch targets

screen-reader compatible

Test conceptually with:

Android TalkBack

and

iOS VoiceOver.

The interface should still make sense with eyes closed.

WAKE LOCK

While the assistant is running, use:

navigator.wakeLock

when supported.

Release it when the assistant stops.

Handle unsupported browsers gracefully.

FE-05 — WARNING HANDLING

When:

frame_result

is received:

pass:

payload.warnings

to:

speech.speakWarnings()

Do NOT recreate speech queue logic.

Do NOT implement cooldowns in the frontend.

Do NOT implement warning priority logic independently.

Coder 4's speech.ts owns speech queue behaviour.

Critical warnings:

interrupt: true

must be passed correctly.

Guardian messages must be spoken using:

spoken_text

with the correct source/priority through the Coder 4 service.

The mock:

vehicle_right.json

must produce the warning defined by the API contract.

Do not alter the backend warning sentence.

FE-06 — DETECTION OVERLAY

Create a visual detection overlay for judges/guardian.

The user does not depend on this overlay.

For every Detection:

Use:

bbox

from the original frame.

Scale coordinates according to:

frame_size

and displayed video/image size.

Display information such as:

car · right · 4.2 m · ↗ approaching

Use risk levels:

critical

high

medium

low

Do not rely on colour alone.

Include text/icon indicators.

Add direction zone guide lines around:

0.2

0.4

0.6

0.8

Show walking corridor.

Provide a toggle to hide/show the overlay.

Display:

Path clear

OR

Nearest obstacle 2.1 m

based on:

path_clear

and:

clear_distance_m

Do not calculate risk in the frontend.

REST API SERVICE

Create a reusable frontend API service for the endpoints required by Coder 1.

Use:

VITE_API_BASE

Do not hardcode backend URLs.

At minimum support the Coder 1-required operations:

create session

get session

end session

emergency fallback

guardian users

alerts

acknowledge/resolve alert

guardian message fallback

Ask

OCR

config

Use typed request/response structures.

Use the exact API contract paths.

Do not invent endpoints.

REST ERROR HANDLING

The backend error format is:

{
  "error": {
    "code": "SESSION_NOT_FOUND",
    "message": "...",
    "details": {}
  }
}


Create a small reusable frontend error handling approach.

Do not create a different error format.

Handle relevant errors gracefully.

Never expose raw stack traces to the user.

GET /config

Frontend may load:

GET /api/v1/config

Use the server-provided configuration where applicable.

Do not create conflicting hardcoded thresholds.

The API contract remains the source of truth.

MOCK MODE

Support:

VITE_USE_MOCKS=true

When enabled:

the application must use:

MockRealtimeClient

instead of the real WebSocket client.

No other frontend code should need to know whether mock mode is enabled.

Mock fixtures are used only for frontend development/testing.

Do not create a fake backend server.

Do not modify Coder 3's backend.

The mock system should support the contract fixtures such as:

frame_result.vehicle_right.json

frame_result.critical_obstacle.json

frame_result.clear.json

alert.emergency.json

guardian_message.json

user_status.json

Use the exact contract payload shapes.

FE-07 — GUARDIAN DASHBOARD

Implement:

/guardian

On load:

call:

GET /api/v1/guardians/{guardian_id}/users

Use:

VITE_DEMO_GUARDIAN_ID

If an active session exists:

connect to:

/ws/guardian/{session_id}?guardian_id={guardian_id}

Send:

hello

If no active session:

show:

Arun is not using the assistant right now

Poll every 5 seconds.

GUARDIAN DASHBOARD LAYOUT

Desktop-first but tablet usable.

Layout:

Left/large:

Live view.

Right:

Map.

Bottom-left:

Alert feed.

Bottom-right:

User status + guardian message box.

Keep the UI clean and demo-friendly.

Do not add unrelated pages.

FE-08 — GUARDIAN LIVE VIEW

The API provides:

snapshot

and:

frame_result

Use:

snapshot

for the actual live image.

Use:

frame_result

for detection/warning/overlay information.

Target:

approximately 2 FPS.

Display:

Live · 2 fps · 190 ms

based on actual user status where available.

If no snapshot is received for 5 seconds:

show a grey/placeholder view and:

Connection to user lost

FE-09 — GUARDIAN ALERT FEED

New alerts appear at the beginning of the feed.

Show:

time

type

risk

message

thumbnail if snapshot_b64 exists

For:

type = emergency

show a prominent emergency banner.

The banner should have repeating alert sound until acknowledged.

Acknowledge using:

ack_alert

or:

PATCH /api/v1/alerts/{alert_id}

Close the emergency banner when:

alert_updated

is received.

Support:

open → acknowledged → resolved

and:

open → resolved

Keep the latest 100 alerts in frontend state.

Older alerts can be loaded through:

GET /api/v1/alerts?before=...

FE-10 — GUARDIAN → USER MESSAGE

Text input:

maximum 200 characters.

Quick phrases:

Stop

Wait

Move slightly left

Move slightly right

Continue straight

I'm watching, you're safe

Use Coder 4's:

speechInput.listenOnce()

for push-to-talk.

Send:

guardian_message

through WebSocket.

Show:

Delivered

when:

message_delivered

is received.

If unavailable/offline:

show:

User offline, not delivered

Use the REST fallback endpoint when the contract requires it.

Do not queue messages when the user is offline.

FE-11 — EMERGENCY

User emergency button must require approximately:

1 second long press.

Prevent accidental pocket activation.

Use:

navigator.vibrate

where supported.

Send:

{
  "trigger": "button"
}


through the user WebSocket.

If WebSocket is unavailable:

use:

POST /api/v1/emergency

with latest location when available.

When:

emergency_ack

is received:

speak:

spoken_text

through Coder 4's speech service.

If no acknowledgement within 3 seconds:

speak:

Trying to reach your guardian

and retry once through REST.

Voice emergency integration should consume Coder 4's listenOnce() result.

Do not implement speech recognition yourself.

FE-12 — ASK AI / READ TEXT

Coder 4 owns the voice implementation.

Coder 1 only mounts/integrates it.

Double-tap on the Start area should support push-to-talk according to the contract.

Use Coder 4's:

speechInput.listenOnce()

Route intents exactly:

read_text
→

POST /api/v1/ocr

describe
→

POST /api/v1/ask

with:

mode: "describe"

path_check
→

POST /api/v1/ask

with:

mode: "path_check"

ask
→

POST /api/v1/ask

with:

mode: "question"

stop_speaking
→ local speech service

repeat
→ local speech service

While waiting:

speak:

Let me look

once.

Speak the API's:

spoken_text

through Coder 4.

Do not implement Gemini.

Do not implement OCR.

Do not create an alternative AI service.

FE-13 — LOCATION

User app:

use:

navigator.geolocation.watchPosition

with high accuracy.

Send location:

every 5 seconds

OR

when movement is approximately 10 meters

Use the exact Location contract.

Guardian map:

Use Leaflet + OpenStreetMap by default.

No map token required.

If Mapbox token is configured, Mapbox may be used according to the contract.

Display:

user marker

accuracy circle

heading arrow

last 20 trail points

emergency location pin

Do not build a custom map backend.

FE-14 — USER STATUS

Use the user_status WebSocket payload.

Show:

online/offline

FPS

latency

battery

last seen

If offline for more than 10 seconds:

show a clear red status panel.

Do not create backend offline detection.

Use backend-provided status.

User app should send status approximately every 10 seconds.

Battery:

use:

navigator.getBattery()

when available.

Otherwise:

send/display null.

P2 FRONTEND ONLY

Do NOT implement P2 backend functionality.

Only create frontend integration structures where required for:

navigation

WebRTC

settings

P2 must not interfere with P0/P1.

DESIGN REQUIREMENTS

The UI should be:

elegant

modern

clean

accessible

responsive

demo-friendly

easy for judges to understand

But do NOT add unnecessary:

login

registration

authentication

payment

profile system

social features

unrelated settings

admin panel

database UI

extra pages

fake AI features

unrelated animations

This is a hackathon MVP.

Functionality and contract correctness are more important than decorative UI.

SECURITY / PRIVACY RULES

Never place backend secrets in frontend.

Never use:

SUPABASE_SERVICE_ROLE_KEY

in frontend.

Never use:

GEMINI_API_KEY

in frontend.

Camera frames are not to be persisted by the frontend.

Follow the API contract privacy model.

PERFORMANCE REQUIREMENTS

The frontend should target the API contract budgets:

Client capture + JPEG:

≤ 30 ms

Network upload:

≤ 80 ms on appropriate network

Frame → warning on screen:

≤ 400 ms

Frame → speech starts:

≤ 1 second

Sustained throughput:

≥ 4 FPS

Target WebSocket frame rate:

approximately 5 FPS

Maximum frame in flight:

1

Never create a frame queue.

IMPORTANT TEAM INTEGRATION RULE

The frontend must be compatible with the exact API contract.

Do not change backend contracts just to make frontend implementation easier.

If an API is not implemented yet, use the documented contract and mock mode.

Do not invent a new request/response format.

Do not rename backend fields.

Do not convert snake_case API fields into different API field names.

Do not modify:

API_CONTRACTS.md

Do not modify:

Coder 2 backend modules.

Do not modify:

Coder 3 backend modules.

Do not modify:

Coder 4 speech/voice implementation.

IMPLEMENTATION ORDER

Follow this order strictly.

PHASE 1 — P0

Project scaffold

Routing

Types

Config

REST API service

WebSocket service

MockRealtimeClient

User page

Camera capture

Frame encoding

Backpressure

Session lifecycle

Frame result handling

Speech integration

Detection overlay

Accessibility

Emergency integration

Do not move to Guardian Dashboard until the P0 architecture is stable.

PHASE 2 — P1

Guardian route

Guardian session selection

Guardian WebSocket

Snapshot live view

Frame-result overlay

Alert feed

Emergency banner

Acknowledge/resolve

Guardian messages

Location

Map

User status

Ask AI integration

OCR integration

PHASE 3 — P2

Only after P0 and P1 are complete:

navigation frontend

WebRTC frontend integration

settings frontend

ACCEPTANCE CRITERIA

Before considering Coder 1 complete, verify:

P0

The following works:

Camera starts.

Session is created.

WebSocket connects.

Hello is sent.

Camera frame is encoded correctly.

Only one frame is in flight.

Frame is sent using the exact contract envelope.

frame_result is received.

Detection data is displayed.

Warning data is displayed.

Warning is passed to Coder 4 speech service.

Critical warnings can interrupt speech through Coder 4.

Start/Stop works.

Camera stops correctly.

Session ends correctly.

Wake Lock works where supported.

Screen-reader labels exist.

Emergency UI works according to the contract.

Mock mode works.

Real backend mode can be switched through environment configuration.

P1

Guardian page loads.

Guardian session is discovered.

Guardian WebSocket connects.

Snapshot appears.

Frame-result overlay appears.

Alerts appear.

Emergency banner works.

Acknowledge works.

Resolve works.

Guardian message works.

Location appears.

Map works.

User status appears.

Ask integration works.

OCR integration works.

MOST IMPORTANT RULE

If you discover something that belongs to:

Coder 2,
Coder 3,
Coder 4,
or Member 5,

STOP and do not implement it.

Instead, leave a clear integration point/interface for that team member.

Do not solve their problem inside the frontend.

If a requirement is ambiguous, follow API_CONTRACTS.md first and preserve the existing architecture.

Do not invent new functionality.

Do not refactor unrelated code.

Do not delete working code unless it directly conflicts with the Coder 1 requirements.

Make the smallest necessary changes to achieve the Coder 1 stories.

FINAL ROLE DEFINITION

Your entire job can be summarized as:

CODER 1 = BUILD THE FRONTEND THAT CONSUMES THE TEAM'S BACKEND, VISION, AND VOICE SERVICES.

P0:

User camera → WebSocket → FrameResult → warning → speech

P1:

Guardian dashboard → live snapshot → alerts → emergency → messages → map → status → AI/OCR integration

Do not build the backend, AI vision, risk engine, speech engine, OCR engine, Gemini, database, or QA system.

Stay strictly inside the Coder 1 boundary.

This project was built with [Lovable](https://lovable.dev).

## Build with Lovable

Continue developing this project in the [Lovable editor](https://lovable.dev/projects/fca76b9d-1ece-43bc-8087-0a9c5faf4bc9).

- **Ship faster**: describe what you want to build and Lovable handles the code.
- **Stay in sync**: every change made in Lovable is committed straight to this repository.
- **Full ownership**: this code is yours. Push to `main` on GitHub and your changes sync back into Lovable, ready for your next prompt.

## Development

Prefer working locally? You need Node.js and npm — [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating).

```sh
git clone <this-repository-url>
cd <repository-name>
npm i
npm run dev
```

### Frontend and phone demo

Install dependencies with `npm install --legacy-peer-deps` when npm's peer resolver fails on this repository, then run `npm run dev -- --host`. Set the contract's `VITE_*` values in `.env` or `.env.local`; use `VITE_USE_MOCKS=true` to exercise the user and guardian screens without the backend.

For a phone demo, serve both the Vite app and backend over HTTPS with a tunnel such as Cloudflare Tunnel or ngrok, then set `VITE_API_BASE` and `VITE_WS_BASE` to the matching HTTPS/WSS tunnel URLs. A phone accessing a LAN IP over plain HTTP cannot use the camera or microphone; `localhost` is the only plain-HTTP secure-context exception.

On `/user`, a single tap on the large Start/Stop area toggles the assistant. While it is running, double-tap that area to push-to-talk for Ask AI, Read Text, or an emergency voice intent. Emergency button activation requires a one-second press and hold.
