# Coder 2 — AI Vision (YOLOv8 + OpenCV)

**Mission:** Turn a camera frame into a list of objects that each have a **class, direction, approximate distance, motion and risk level**, plus at most two warnings worth speaking. You own the hardest part of the project and three of the five MVP features (detection, distance, direction).

**You own:** `backend/vision/` and `backend/safety/`. Your branch: `ai-core`.
**Contract sections you implement:** 2.1–2.6, 3.1–3.2, 4.2–4.4, 8.2, 12.
**You depend on:** Coder 4's `speech/phrases.py` for the warning sentence (use a one-line template until it lands).
**You unblock:** Coder 3, who calls only `VisionPipeline.process()`.

> **Rule:** write everything as plain Python that runs from a webcam script with **no FastAPI**. Coder 3 handles the server. If `python -m vision.pipeline` works on your laptop, integration is a one-line import.

---

## P0 — MVP

### CV-01 · Object detector with tracking
**As a** visually impaired user, **I want** the system to recognise people, vehicles and common obstacles, **so that** I know what is around me and not just that "something" is there.

**Acceptance criteria**
- [ ] `Detector` class matches contract 8.2. Uses `ultralytics` YOLOv8n (`yolov8n.pt`) by default.
- [ ] Only returns the classes in contract 2.1. COCO names are converted to `snake_case` (`traffic light` → `traffic_light`, `dining table` → `dining_table`).
- [ ] Confidence threshold 0.40 (configurable).
- [ ] `track=True` uses `model.track(frame, persist=True, tracker="bytetrack.yaml")` and fills `track_id`. Document that each session needs its own `Detector` instance, because tracker state lives in the model object.
- [ ] Model loads once. Run one warm-up inference on a blank frame at startup.
- [ ] **Benchmark** on the demo laptop at 640×480: report mean and p95 inference ms on CPU (and GPU if present) in the README. Target ≤ 100 ms on CPU. If too slow, try `imgsz=480` or `yolov8n` exported to ONNX/OpenVINO before anything else.

### CV-02 · Direction estimation
**As a** visually impaired user, **I want** to know whether something is on my left, ahead or on my right, **so that** I know which way to step.

**Acceptance criteria**
- [ ] `get_direction(cx_norm)` returns one of the 5 zones in contract 2.3, with the exact boundaries listed there.
- [ ] `cx_norm = ((x1 + x2) / 2) / frame_width`, clamped to [0, 1].
- [ ] Unit tests at every boundary: 0.0, 0.199, 0.2, 0.4, 0.5, 0.6, 0.6001, 0.8, 1.0.
- [ ] README note for the pitch: direction is relative to where the **camera** points, so the phone should be worn on a chest strap/lanyard facing forward.

### CV-03 · Approximate distance estimation
**As a** visually impaired user, **I want** to hear roughly how far away an object is, **so that** I can tell an urgent obstacle from a distant one.

**Approach (MVP):** pinhole camera model with known real-world object heights.
`distance_m = (real_height_m × focal_px) / bbox_height_px`

**Acceptance criteria**
- [ ] `estimate_distance()` matches contract 8.2 and returns `(distance_m, distance_zone, distance_method)`.
- [ ] A `KNOWN_HEIGHTS_M` table, starting values to tune: person 1.65 · car 1.5 · bus 3.0 · truck 3.0 · motorcycle 1.2 · bicycle 1.0 · chair 0.9 · bench 0.85 · dining_table 0.75 · potted_plant 0.6 · dog 0.6 · cow 1.4 · fire_hydrant 0.7 · stop_sign 0.75 · traffic_light 0.9 · backpack 0.5 · suitcase 0.65 · bottle 0.25.
- [ ] **Calibration script** `vision/calibrate.py`: a person stands at exactly 2.0 m. The script reads their bbox height over 30 frames and prints `focal_px = bbox_h × 2.0 / 1.65`. The value goes into `CAMERA_FOCAL_PX`. Re-run it for the actual demo phone; every camera differs.
- [ ] **Clipped boxes:** if the box touches the top or bottom frame edge (within 3 px), the real height is unknown. Return the estimate as a lower bound with `distance_method: "edge_clipped"`. If the box covers > 60% of the frame height and touches the bottom edge, force `distance_m = min(estimate, 0.9)` (the object is very close).
- [ ] Smooth with an exponential moving average per `track_id` (α = 0.4) so the spoken distance does not jump between frames.
- [ ] `distance_m` rounded to 1 decimal place. Unknown class or zero-height box → `(None, "unknown", "none")`.
- [ ] **Accuracy table for the pitch:** measure a person and a chair at 1, 2, 3, 4 and 5 m. Record estimated vs. real distance and % error. Target: within ±25% up to 5 m. Give the table to Member 5.

### CV-04 · Motion (approaching / receding)
**As a** visually impaired user, **I want** to know whether a vehicle is coming toward me, **so that** a moving car is treated as more dangerous than a parked one.

**Acceptance criteria**
- [ ] `MotionTracker` matches contract 8.2. Keeps about 1.5 s of `(ts_ms, distance_m)` history per `track_id`.
- [ ] Speed = slope of a least-squares fit over the history (needs ≥ 3 points, otherwise `"unknown"`).
- [ ] `approaching` if closing speed ≥ 0.5 m/s, `receding` if ≤ −0.5 m/s, otherwise `stationary`. `approach_speed_mps` is positive when closing.
- [ ] `prune()` drops tracks not seen for 3 s.
- [ ] Test with a recorded clip of someone walking toward the camera: `approaching` within 1 s of them starting to walk, and no `approaching` while they stand still (noise check).

### CV-05 · Risk engine
**As a** visually impaired user, **I want** the system to prioritise real dangers, **so that** I am not overwhelmed by announcements about harmless objects.

**Acceptance criteria**
- [ ] `assess()` implements rules R1–R7 from contract 3.1 **in order** and returns `(risk_level, priority, risk_score, rule_id)`.
- [ ] Thresholds come from `config.py`, never hard-coded inside the function.
- [ ] Table-driven unit tests: at least one case per rule, plus edge cases (`distance_m = None`, exactly 1.0 m, exactly 5.0 m, vehicle receding at 2 m).
- [ ] The rule ID is carried into `Warning.rule` so QA can see why something was said.

### CV-06 · Warning selection and cooldown
**As a** visually impaired user, **I want** each hazard announced once and repeated only when it matters, **so that** the voice stays useful and not noisy.

**Acceptance criteria**
- [ ] `WarningSelector.select()` implements contract 3.2: `low` never spoken; cooldown by key (`track_id`, otherwise `class_name + direction`) of 1500 / 3000 / 6000 ms; immediate re-announcement on escalation; max 2 warnings per frame, sorted by priority.
- [ ] `interrupt = True` only for `critical`.
- [ ] Builds `message` with `speech.phrases.build_warning_message()` and `short_text` with `build_short_text()`. Until Coder 4 delivers, use the fallback `f"{spoken_name} {distance} meters {direction}"`.
- [ ] Simulation test: feed 50 detections, 200 ms apart (10 s), of the same person standing 1.5 m directly ahead (R4, high, 3000 ms cooldown). Exactly 4 warnings come out, at about t = 0, 3, 6 and 9 s, not 50. Then move the person to 0.8 m (R1, critical): a warning comes out on that very frame, ignoring the cooldown.

### CV-07 · Vision pipeline (the one entry point)
**As the** backend developer, **I want** a single function that turns a frame into a `FrameResult`, **so that** I can plug the vision system into the WebSocket with one call.

**Acceptance criteria**
- [ ] `VisionPipeline.process(frame_bgr, frame_id, ts_captured_ms) -> dict` matches contract 8.2. The output validates against the `FrameResult` Pydantic model in `backend/schemas.py`.
- [ ] Order: detect → per detection: direction, distance, motion, risk → `path_clear` and `clear_distance_m` (CV-08) → warnings.
- [ ] Fills `inference_ms` (YOLO time) and `ts_processed`.
- [ ] One `VisionPipeline` per session (it holds the tracker, motion history and cooldowns). Not thread-safe; Coder 3 calls it from one worker at a time per session.
- [ ] Exceptions on one frame are caught and logged. Return an empty `FrameResult` rather than crash the stream.
- [ ] `python -m vision.pipeline --source 0` opens the webcam, draws the overlay (boxes, direction zones, distance, risk colors) in an OpenCV window, prints warnings to the console and optionally speaks them with `pyttsx3`. This is the fallback demo if the network fails on stage.

### CV-08 · Path-clear check
**As a** visually impaired user, **I want** to know when the path ahead is clear, **so that** I can walk confidently.

**Acceptance criteria**
- [ ] `path_clear = True` when no detection in the walking corridor (`slight_left`, `center`, `slight_right`) has `distance_m < 3.0`.
- [ ] `clear_distance_m` = smallest `distance_m` in the corridor, or `None` if the corridor is empty.
- [ ] Note in the README: "clear" only means no **known** object class was detected. Holes, kerbs and stairs are not detectable in the MVP. The pitch must not claim otherwise.

### CV-09 · Test clips and fixtures for QA
**As the** QA member, **I want** recorded clips and expected outputs, **so that** I can re-test the pipeline after every change without walking into traffic.

**Acceptance criteria**
- [ ] 4 short clips (10–20 s, 640×480) recorded on the demo phone: person walking toward the camera; chair placed 0.7 m ahead; vehicle passing on the right (a parking lot is fine); empty corridor.
- [ ] `vision/replay.py --clip <file>` runs the pipeline on a clip and writes `FrameResult` JSON lines, so Member 5 can diff outputs between versions.
- [ ] Clips live outside git if large (shared drive link in the README).

---

## P1 — Demo features

### CV-10 · Scene summary for Ask AI
**As a** visually impaired user asking "What is around me?", **I want** the AI's answer to use our measured distances, **so that** the answer is consistent with the warnings.

**Acceptance criteria**
- [ ] `summarize_for_llm(frame_result) -> list[dict]` returns the top 8 detections by `risk_score` with only `spoken_name, direction, distance_m, motion, risk_level`. Coder 4 passes this to Gemini.

### CV-11 · Snapshot thumbnail for alerts
**Acceptance criteria**
- [ ] `make_thumbnail(frame_bgr, detections) -> str` returns a base64 JPEG, max 320 px wide, with boxes drawn, used for `Alert.snapshot_b64`.

---

## P2 — Stretch
- **CV-12** Low-confidence detection: set `low_confidence_scene = True` when, for 3 s, the frame is very dark (mean brightness < 40), very blurred (Laplacian variance < 50), or has more than 8 people in the corridor. Coder 3 turns this into an `assistance_request` alert.
- **CV-13** Metric depth model (e.g. a Depth Anything V2 metric checkpoint): sample the depth map at the bottom-centre of each box, compare against the pinhole table and keep whichever wins on your accuracy table. Only if it fits the latency budget.
- **CV-14** Custom classes (stairs, door, pole, open drain) from a public dataset, fine-tuned YOLOv8n, merged into the class table.

---

## Definition of done (every story)
- Unit tests pass (`pytest backend/tests/vision`).
- Works from the standalone webcam script with no server.
- Output validates against `schemas.FrameResult`.
- Latency stays inside contract section 12 on the demo laptop.
