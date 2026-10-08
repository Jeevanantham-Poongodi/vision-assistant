# Team Plan — AI-Powered Vision & Guardian Navigation Assistant

Read this first, then your own story file, then `API_CONTRACTS.md`.

| File | For |
|---|---|
| `API_CONTRACTS.md` | Everyone. Single source of truth for every message, endpoint and threshold |
| `01_CODER1_FRONTEND_STORIES.md` | Coder 1: user app + guardian dashboard |
| `02_CODER2_AI_VISION_STORIES.md` | Coder 2: detection, distance, direction, motion, risk |
| `03_CODER3_BACKEND_STORIES.md` | Coder 3: FastAPI, WebSockets, Supabase, deployment |
| `04_CODER4_INTEGRATIONS_STORIES.md` | Coder 4: voice in/out, warning sentences, Gemini, OCR, maps |
| `05_IMPLEMENTATION_AND_INTEGRATION_ROADMAP.md` | Everyone: phases, story order, dependencies, checkpoint procedure, git rules |
| `06_MEMBER5_QA_AND_PRESENTATION_PLAN.md` | Member 5: plain-language guide to testing, checkpoints, measurements, pitch deck and demo |
| `member5-starter-kit/` | Ready-made mock data, Postman collection and environments, WebSocket test messages |

## The one sentence we demo

> Camera sees a vehicle → YOLO detects it → direction = right → distance ≈ 4 m → it is approaching → risk = high → the phone says *"Warning. Car approaching from your right, approximately 4 meters away. Please move slightly to your left."*

Every P0 story in every file exists to make that sentence happen, live, on a phone, in under one second.

## One flagged gap in the original role split

The roles list Coder 1 as "Guardian Dashboard". But four of the five MVP features need the **user-facing camera page** (camera capture, sending frames, speaking warnings), and nobody else owns it. In these stories, **Coder 1 builds the user camera page first (P0)** and the guardian dashboard second (P1). The guardian dashboard is not in the MVP list.

## Checkpoints

The detailed schedule, story order, dependencies and merge procedure are in **`05_IMPLEMENTATION_AND_INTEGRATION_ROADMAP.md`**. In short:

| Checkpoint | Time | Definition of done |
|---|---|---|
| **CP0 — Setup** | H+1 | Repo, branches, protection, stubs and mocks merged; everything builds |
| **CP1 — Skeleton loop** | H+4 | Phone camera → backend (stub) → phone speaks the mock warning |
| **CP2 — MVP ★** | H+8 | Phone camera → real YOLO → spoken warning, ≤ 1 s, ≥ 4 fps, 5 minutes without a crash |
| **CP3 — Guardian** | H+12 | Live view, hazard alerts, emergency + acknowledge, Supabase persistence |
| **CP4 — Feature complete** | H+16 | Ask AI, OCR, guardian messages, map; full demo scenario runs |
| **CP5 — Release candidate** | H+20 | Hardening, fallbacks, optional stretch; feature freeze, tag `v1.0-demo` |

## Integration handshakes (who unblocks whom)

```
C3 WS echo + stub pipeline ──► C1 swaps mock client for real socket
C2 VisionPipeline.process() ──► C3 replaces stub with real pipeline
C4 phrases.build_warning_message() ──► C2 WarningSelector uses real sentences
C4 speech.ts ──► C1 wires speakWarnings() into the user page
C4 gemini.py / reader.py ──► C3 wires /ask and /ocr
C3 guardian WS ──► C1 guardian dashboard goes live
```

## Working agreements
- **Nobody pushes to `main`.** One branch per member: `frontend-ui` (C1), `ai-core` (C2), `backend-api` (C3), `voice-ocr` (C4), `qa-docs` (M5). Branches meet in `integration` every 4 hours; only a green `integration` goes to `main` by PR (merge commit, never squash). Full rules: roadmap section 2.
- Commit messages start with the story ID: `[CV-03] add pinhole distance estimation`.
- After every checkpoint, everyone merges `main` back into their own branch.
- Contract changes: Coder 3 edits `API_CONTRACTS.md` on `backend-api` and announces it; after CP2, additive changes only (roadmap section 14.2).
- Member 5 (QA) owns the Postman collection and the mock JSON fixtures, and runs the golden-set and latency checks at every gate.
- A broken `main` is fixed before anything else.
