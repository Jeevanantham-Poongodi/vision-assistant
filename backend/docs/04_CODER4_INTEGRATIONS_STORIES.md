# Coder 4 — Integrations (Voice, Warning Sentences, Gemini, OCR, Maps)

**Mission:** Give the system its **voice and ears**. You own the fifth MVP feature, the *natural voice warning*: both the sentence the system says and the way it is spoken. After the MVP, you add the features that make the demo memorable: Ask AI (Gemini), Read Text (OCR) and voice commands.

**You own:** `backend/speech/`, `backend/ocr/`, `backend/ai/`, `backend/navigation/`, `frontend/src/services/speech.ts` and `frontend/src/features/voice/`. Your branch: `voice-ocr`.
**Contract sections you implement:** 2.9, 3.2 (client-side rules), 7.9, 7.10, 7.16–7.18, 8.3, 9.1, 13.7.
**You depend on:** Coder 2's `Detection` dicts (use contract 13 mocks until then), Coder 3 for wiring endpoints.
**You unblock:** Coder 2 (real sentences in warnings), Coder 1 (speech service for both screens).

> **Rule:** everything you write is a pure function or a self-contained service with its own test script. No FastAPI routes (Coder 3 does those), no React components (Coder 1 does those).

---

## P0 — MVP

### IN-01 · Warning sentence builder
**As a** visually impaired user, **I want** warnings phrased like a person would say them, **so that** I understand them instantly while walking.

**Acceptance criteria**
- [ ] `build_warning_message(det, risk_level, rule_id)`, `build_short_text(det)` and `format_distance(distance_m)` match contract 8.3.
- [ ] Sentence patterns:
  - Approaching vehicle (R2/R3): `"Warning. {Name} approaching {from-direction}, approximately {distance} away. Please {advice}."`
  - Critical, very close (R1): `"Stop. {Name} about {distance} {position}."`
  - Everything else spoken: `"{Name} about {distance} {position}."`
- [ ] Direction phrases exactly as contract 2.3 (position form and "from" form).
- [ ] Advice: object on the right side → "move slightly to your left"; left side → "move slightly to your right"; centre → "stop and step aside".
- [ ] Distance rounding exactly as contract 13.7: < 1 m → nearest 10 cm in centimeters; 1–3 m → nearest half meter ("2 and a half meters"); ≥ 3 m → whole meters; "1 meter" singular.
- [ ] `distance_m = None` → leave the distance out: `"Car approaching from your right."`
- [ ] Sentences stay short, ≤ 20 words. Test that.
- [ ] `pytest` runs every row of the golden set in contract 13.7 and passes. Member 5 adds new rows as bugs are found.
- [ ] Hand it to Coder 2 the moment the golden set passes.

### IN-02 · Text-to-speech service with a priority queue
**As a** visually impaired user, **I want** urgent warnings to cut through anything else being said, **so that** I never miss a danger because the phone was busy talking.

**Acceptance criteria**
- [ ] `frontend/src/services/speech.ts` implements `SpeechService` (contract 9.1) on top of the browser `speechSynthesis` API.
- [ ] Queue rules (contract 3.2 and 9.1): `interrupt: true` → `cancel()` then speak now; otherwise queue by priority; max queue length 2 (drop the lowest priority); drop items older than 2000 ms; skip an identical text within 3000 ms.
- [ ] `unlock()` speaks an empty utterance inside a user gesture (needed on iOS Safari and Chrome Android).
- [ ] Voice selection: prefer an `en-IN` voice, fall back to any `en-*`. Handles `getVoices()` being empty until the `voiceschanged` event fires.
- [ ] Works around the Chrome bug where long utterances stop after about 15 s (keep sentences short; call `resume()` on a timer while speaking).
- [ ] `repeatLast()` and `stop()` work.
- [ ] A small test page `/dev/speech` (Coder 1 adds the route) with buttons that fire a medium, then a critical warning 300 ms later. The critical one cuts the medium one off.

### IN-03 · Server-side speech fallback for the offline demo
**As a** team, **we want** the standalone vision demo to talk, **so that** we still have a voice demo if the network fails on stage.

**Acceptance criteria**
- [ ] `speech/local_tts.py` with `speak(text, interrupt=False)` using `pyttsx3` on a background thread. Coder 2's webcam script calls it with `--speak`.

---

## P1 — Demo features

### IN-04 · Speech-to-text and voice intents
**As a** visually impaired user, **I want** to speak commands and questions, **so that** I never need to find a button.

**Acceptance criteria**
- [ ] `SpeechInput` (contract 9.1) on top of `SpeechRecognition` / `webkitSpeechRecognition`, push-to-talk via `listenOnce()`, `lang` default `en-IN`, 6 s timeout.
- [ ] `parseIntent(transcript)` maps to the `VoiceIntent` values in contract 2.9 with keyword rules (lower-case, punctuation removed). `emergency` is checked **first** and needs no network.
- [ ] Short earcons: a rising beep when listening starts, a falling beep when it stops.
- [ ] `isSupported()` returns false on Firefox and similar, so Coder 1 can show the button fallback.
- [ ] Unit test for `parseIntent` with at least 25 example phrases, including Indian-English variants ("what is there in front", "read this board", "is the road clear").

### IN-05 · Ask AI with Gemini (grounded)
**As a** visually impaired user, **I want** to ask "What is in front of me?" and get a short, accurate answer, **so that** I can understand my surroundings on demand.

**Acceptance criteria**
- [ ] `answer_question(question, mode, detections, image_jpeg)` matches contract 8.3. Uses the official Google Gen AI Python SDK, model name from `GEMINI_MODEL` (a current Flash-tier model for speed).
- [ ] `ai/prompts.py` system prompt requires:
  - Answer in at most 2 short sentences, spoken style, no markdown, no lists.
  - **Distances and directions must come only from the provided detections list.** Never estimate distance from the image.
  - Use the image only for things the detector cannot see (what kind of place it is, colours, the type of object the user is holding for "what is this?").
  - If unsure, say so plainly ("I'm not sure. Please ask your guardian to take a look.").
- [ ] Modes: `question` (free question), `describe` (one-sentence scene + the 2 most important objects), `path_check` (answers from `path_clear` / `clear_distance_m` first, then the image).
- [ ] 6 s timeout. On timeout or any error, returns `describe_scene_fallback(detections, mode)` with `source = "fallback"`. **Never raises.**
- [ ] `describe_scene_fallback` lives in `phrases.py` and covers: empty scene ("I don't see any obstacles ahead."), path clear ("The path ahead appears clear for about 5 meters."), and a top-2 objects summary.
- [ ] Image sent downscaled to max 640 px, JPEG quality 0.7.
- [ ] Test script `python -m ai.gemini --image sample.jpg --question "..."` with 5 saved scenes and the expected style of answer. Check latency (target ≤ 4 s).

### IN-06 · OCR — read signs and labels
**As a** visually impaired user, **I want** to point my phone at a sign and hear what it says, **so that** I can read room numbers, notices and directions.

**Acceptance criteria**
- [ ] `read_text(image_bgr)` matches contract 8.3, using `pytesseract` (system package `tesseract-ocr` installed; path from `TESSERACT_CMD`).
- [ ] Pre-processing pipeline: grayscale → upscale 2× if the image is under 1000 px wide → CLAHE contrast → light denoise. Try `--psm 6` and `--psm 11`; keep the result with the higher mean confidence.
- [ ] Drop words with confidence < 60 and lines that are mostly non-alphanumeric noise. Group words into lines with bounding boxes (`image_to_data`).
- [ ] Test set of 10 photos (room number, notice board, product label, bus number, direction sign): record what was read correctly. Share with Member 5 for the pitch.

### IN-07 · OCR interpretation into natural speech
**As a** visually impaired user, **I want** the sign read as a sentence and arrows explained, **so that** I understand what it means, not just the raw letters.

**Acceptance criteria**
- [ ] `interpret_ocr(ocr_text, image_jpeg)` matches contract 8.3. Gemini turns raw text into one natural sentence ("The sign says Computer Science Department. There is an arrow pointing left.") and fixes obvious OCR errors.
- [ ] The prompt forbids inventing text that is not in the OCR output or clearly visible in the image.
- [ ] On failure returns the cleaned OCR text with "The text says: " in front and `source = "tesseract"`.
- [ ] No text → the exact `spoken_text` in contract 7.10.

### FE-12 · Ask AI and Read Text controls *(moved from Coder 1, see roadmap §1.2)*
Build `frontend/src/features/voice/VoiceControls.tsx` to the acceptance criteria of FE-12 in `01_CODER1_FRONTEND_STORIES.md`. Coder 1 only mounts the component on the user page.

### IN-08 · Guardian voice input
**As a** guardian, **I want** to speak my instruction instead of typing it, **so that** I can react quickly in a tense moment.

**Acceptance criteria**
- [ ] The same `SpeechInput.listenOnce()` works on the guardian dashboard (desktop Chrome), with no intent parsing; the transcript goes into the message box for the guardian to confirm and send.

---

## P2 — Stretch

### IN-09 · Walking navigation
**As a** visually impaired user, **I want** to say "Take me to the library" and get step-by-step spoken directions, **so that** I can reach places on my own.

**Acceptance criteria**
- [ ] `navigation/maps.py`: geocode the destination name, then request a walking route (Mapbox Directions with `MAPBOX_TOKEN`; OpenRouteService or OSRM as a free alternative).
- [ ] Convert each step into `spoken_text` in our style ("Turn slightly right, then continue for about 30 meters.") and return the shape in contract 7.16.
- [ ] Destination not found → `DESTINATION_NOT_FOUND`.

### IN-10 · Server TTS/STT fallbacks
- [ ] `POST /tts` (gTTS or Google Cloud TTS) returning `audio/mpeg`, and `POST /stt` (Gemini audio input or Google STT), for browsers without Web Speech support. Contract 7.17–7.18.

### IN-11 · Tamil voice
- [ ] A `ta-IN` sentence table for the warning templates in `phrases.py`, plus `lang` switching in `speech.ts` where a Tamil voice exists on the device. Good pitch point for local relevance; only if the MVP is solid.

---

## Definition of done (every story)
- Isolated test script or `pytest` passes without the server running.
- Python functions never raise on bad input from the network; they return a safe fallback.
- `speech.ts` tested on a real Android phone in Chrome **and** desktop Chrome.
- Example inputs and outputs added to Member 5's test sheet.
