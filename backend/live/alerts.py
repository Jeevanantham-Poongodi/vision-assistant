# backend/live/alerts.py
"""Hazard and emergency alerts and their acknowledgement (BE-10). Owner: Coder 3.
Shared by the user socket, the guardian socket and the REST routes, so every path behaves the same."""
import asyncio
import base64
import importlib
import logging
import time
from typing import Any
from uuid import UUID

import numpy as np

from config import THRESHOLDS
from errors import AppError
from live.hub import SessionHub, SessionState, post_all, to_alert

log = logging.getLogger("vision_assistant")

HAZARD_THROTTLE_S = THRESHOLDS.alerts.hazard_throttle_ms / 1000  # contract 3.3: per cooldown key
EMERGENCY_DEDUPE_S = 10.0  # a second press within this re-acks the open emergency
THUMBNAIL_MAX_WIDTH = 320  # contract 4.6
# Where Coder 2's CV-11 make_thumbnail(frame_bgr, detections) -> str may live.
THUMBNAIL_MODULES = ("vision.thumbnail", "vision.pipeline")

NOTIFIED = "Your guardian has been notified."
RESPONDING = "Your guardian has seen your emergency and is responding."
ALLOWED_TRANSITIONS = {("open", "acknowledged"), ("acknowledged", "resolved"), ("open", "resolved")}


# --- Thumbnail (snapshot_b64) ---

def _coder2_make_thumbnail() -> Any:
    for name in THUMBNAIL_MODULES:
        try:
            fn = getattr(importlib.import_module(name), "make_thumbnail", None)
        except ImportError:
            continue
        if fn is not None:
            return fn
    return None


def plain_thumbnail(frame_bgr: np.ndarray) -> str:
    """Fallback until CV-11: the frame scaled to at most 320 px wide, no boxes."""
    import cv2

    h, w = frame_bgr.shape[:2]
    if w > THUMBNAIL_MAX_WIDTH:
        frame_bgr = cv2.resize(frame_bgr, (THUMBNAIL_MAX_WIDTH, round(h * THUMBNAIL_MAX_WIDTH / w)),
                               interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return base64.b64encode(buf.tobytes()).decode() if ok else ""


def make_snapshot(frame_bgr: np.ndarray | None, detections: list[dict]) -> str | None:
    """Coder 2's make_thumbnail when it exists, else the plain fallback. Blocking: run in a thread."""
    if frame_bgr is None:
        return None
    fn = _coder2_make_thumbnail()
    if fn is not None:
        try:
            return fn(frame_bgr, detections)
        except Exception:
            log.exception("make_thumbnail failed; using the plain thumbnail")
    return plain_thumbnail(frame_bgr) or None


def decode_latest(jpeg: bytes | None) -> np.ndarray | None:
    if not jpeg:
        return None
    import cv2

    return cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)


def alert_message(row: dict, snapshot: str | None = None) -> dict:
    body = to_alert(row).model_dump(mode="json")
    body["snapshot_b64"] = snapshot  # WebSocket only; never stored (contract 4.6)
    return body


# --- Hazards (contract 3.3) ---

def cooldown_key(warning: dict, detection: dict | None) -> str:
    """Contract 3.2: track_id if present, otherwise class_name + direction."""
    if warning.get("track_id") is not None:
        return f"track:{warning['track_id']}"
    direction = detection["direction"] if detection else "?"
    return f"{warning['class_name']}:{direction}"


def _detection_for(warning: dict, detections: list[dict]) -> dict | None:
    if warning.get("track_id") is not None:
        return next((d for d in detections if d.get("track_id") == warning["track_id"]), None)
    return next((d for d in detections if d["class_name"] == warning["class_name"]
                 and d["risk_level"] == warning["risk_level"]), None)


def due_hazards(state: SessionState, result: dict) -> list[tuple[dict, dict | None]]:
    """critical/high warnings whose cooldown key has not alerted in the last 10 s; marks them now.
    Cheap and synchronous, so the frame loop only starts a task when there is something to send."""
    levels = THRESHOLDS.alerts.hazard_levels
    due, now = [], time.monotonic()
    for warning in result.get("warnings", []):
        if warning["risk_level"] not in levels:
            continue
        detection = _detection_for(warning, result.get("detections", []))
        key = cooldown_key(warning, detection)
        last = state.hazard_last.get(key)
        if last is not None and now - last < HAZARD_THROTTLE_S:
            continue
        state.hazard_last[key] = now
        due.append((warning, detection))
    return due


async def raise_hazards(hub: SessionHub, session_id: UUID, due: list[tuple[dict, dict | None]],
                        frame_id: int, frame_bgr: np.ndarray | None, detections: list[dict]) -> None:
    """Runs as a background task after the user already has the frame_result."""
    try:
        session = await hub.repo.get_session(session_id)
        if session is None or session["status"] != "active":
            return
        state = hub.state(session_id)
        snapshot = await asyncio.to_thread(make_snapshot, frame_bgr, detections)
        for warning, detection in due:
            row = await hub.repo.create_alert(
                session_id=session_id, user_id=session["user_id"], type="hazard",
                risk_level=warning["risk_level"], title=warning["short_text"], message=warning["message"],
                location=state.latest_location,
                payload={"detection": detection, "warning": warning, "frame_id": frame_id},
            )
            post_all(state, "alert", alert_message(row, snapshot))
    except Exception:
        log.exception("Could not raise a hazard alert for session %s", session_id)


# --- Emergencies (contract 5.2 and 7.11) ---

async def trigger_emergency(hub: SessionHub, session_id: UUID, trigger: str,
                            location: dict | None = None, note: str | None = None) -> dict:
    """Creates the emergency alert, pushes it to guardians and acks the phone. A second press
    within 10 s of an open emergency re-acks that one instead of creating a duplicate."""
    repo = hub.repo
    session = await repo.get_session(session_id)
    if session is None or session["status"] != "active":
        raise AppError("SESSION_NOT_FOUND", f"Session {session_id} does not exist or has ended.")
    state = hub.state(session_id)
    if state.last_emergency is not None:
        alert_id, at = state.last_emergency
        existing = await repo.get_alert(alert_id)
        if existing is not None and existing["status"] == "open" and time.monotonic() - at < EMERGENCY_DEDUPE_S:
            await send_ack(hub, session_id, existing["id"], "open", NOTIFIED)
            return existing

    user = await repo.get_user(session["user_id"])
    name = user["name"] if user else "The user"
    action = "asked for help by voice" if trigger == "voice" else "pressed the emergency button"
    frame = await asyncio.to_thread(decode_latest, state.latest_jpeg)
    detections = (state.latest_result or {}).get("detections", [])
    snapshot = await asyncio.to_thread(make_snapshot, frame, detections)
    row = await repo.create_alert(
        session_id=session_id, user_id=session["user_id"], type="emergency", risk_level="critical",
        title="Emergency triggered", message=f"{name} {action}.",
        location=location or state.latest_location, payload={"trigger": trigger, "note": note},
    )
    state.last_emergency = (row["id"], time.monotonic())
    post_all(state, "alert", alert_message(row, snapshot))
    await send_ack(hub, session_id, row["id"], "open", NOTIFIED)
    return row


async def send_ack(hub: SessionHub, session_id: UUID | None, alert_id: UUID, status: str, text: str) -> None:
    if session_id is not None:
        await hub.send_to_user(session_id, "emergency_ack",
                               {"alert_id": str(alert_id), "status": status, "spoken_text": text})


# --- Acknowledgement (contract 6.1 and 7.13) ---

async def update_alert(hub: SessionHub, alert_id: UUID, status: str, guardian_id: UUID) -> dict:
    """Applies a guardian's acknowledge/resolve. Unknown alert or unlinked guardian -> ALERT_NOT_FOUND
    (one answer for both, so nobody can probe for alerts)."""
    repo = hub.repo
    row = await repo.get_alert(alert_id)
    linked = row is not None and any(link["user_id"] == row["user_id"]
                                     for link in await repo.get_linked_users(guardian_id))
    if not linked:
        raise AppError("ALERT_NOT_FOUND", f"Alert {alert_id} does not exist.")
    if (row["status"], status) not in ALLOWED_TRANSITIONS:
        raise AppError("INVALID_STATUS_TRANSITION",
                       f"Cannot change an alert from {row['status']} to {status}.",
                       details={"from": row["status"], "to": status})
    was_open = row["status"] == "open"
    row = await repo.update_alert_status(alert_id, status, guardian_id)
    if row["session_id"] is not None:
        hub.broadcast(row["session_id"], "alert_updated", alert_message(row))
        if row["type"] == "emergency" and was_open:
            await send_ack(hub, row["session_id"], row["id"], "acknowledged", RESPONDING)
    return row
