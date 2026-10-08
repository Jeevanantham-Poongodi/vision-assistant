# backend/live/assistance.py
"""Assistance requests when vision is unsure (BE-14). Owner: Coder 3.
Coder 2's pipeline sets FrameResult.low_confidence_scene (CV-12: very dark, very blurred or a
crowded corridor). If it stays true for 3 s, guardians get an assistance_request alert and the
phone says so. One per low-confidence period, and at most one per minute per session."""
import asyncio
import logging
import time
from uuid import UUID

import numpy as np

from config import THRESHOLDS
from live.alerts import alert_message, make_snapshot
from live.hub import SessionHub, SessionState, post_all
from schemas import AssistanceRequestedPayload

log = logging.getLogger("vision_assistant")

ASSIST_AFTER_S = THRESHOLDS.alerts.assistance_after_ms / 1000
ASSIST_THROTTLE_S = THRESHOLDS.alerts.assistance_throttle_ms / 1000
SPOKEN = "I need assistance to determine the safest direction. I have asked your guardian."


def due(state: SessionState, result: dict) -> bool:
    """Called for every frame result; True once per low-confidence period, after 3 s."""
    now = time.monotonic()
    if not result.get("low_confidence_scene"):
        state.low_conf_since, state.assist_raised = None, False
        return False
    if state.low_conf_since is None:
        state.low_conf_since = now
    if state.assist_raised or now - state.low_conf_since < ASSIST_AFTER_S:
        return False
    state.assist_raised = True  # whether or not throttled: no re-check every frame
    if state.last_assist_at is not None and now - state.last_assist_at < ASSIST_THROTTLE_S:
        return False
    state.last_assist_at = now
    return True


async def raise_assistance(hub: SessionHub, session_id: UUID, frame_bgr: np.ndarray | None,
                           detections: list[dict]) -> None:
    """Background task: the alert to guardians, then the spoken notice to the phone."""
    try:
        session = await hub.repo.get_session(session_id)
        if session is None or session["status"] != "active":
            return
        state = hub.state(session_id)
        user = await hub.repo.get_user(session["user_id"])
        name = user["name"] if user else "The user"
        snapshot = await asyncio.to_thread(make_snapshot, frame_bgr, detections)
        row = await hub.repo.create_alert(
            session_id=session_id, user_id=session["user_id"], type="assistance_request", risk_level="high",
            title="Assistance requested",
            message=f"{name}'s camera cannot see clearly enough to guide safely. Please help with directions.",
            location=state.latest_location, payload={"reason": "low_confidence_scene"},
        )
        post_all(state, "alert", alert_message(row, snapshot))
        await hub.send_to_user(session_id, "assistance_requested", AssistanceRequestedPayload(
            alert_id=row["id"], spoken_text=SPOKEN).model_dump(mode="json"))
    except Exception:
        log.exception("Could not raise the assistance request for session %s", session_id)
