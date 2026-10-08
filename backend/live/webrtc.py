# backend/live/webrtc.py
"""WebRTC signalling relay between the phone and its guardians (BE-15). Owner: Coder 3.
The backend only forwards offers, answers and ICE candidates; audio and video then flow
directly between the browsers (mobile networks may need a TURN server for that)."""
from typing import Any
from uuid import UUID

from live.hub import SessionHub

WEBRTC_TYPES = {"webrtc_offer", "webrtc_answer", "webrtc_ice"}
MAX_SIGNAL_BYTES = 64 * 1024  # an SDP offer is a few KB; anything bigger is not signalling


def too_large(raw_text: str) -> bool:
    return len(raw_text.encode()) > MAX_SIGNAL_BYTES


def from_user(hub: SessionHub, session_id: UUID, type_: str, payload: dict[str, Any]) -> int:
    """Phone -> the guardian named in payload.guardian_id, or every guardian. Returns how many."""
    state = hub.state(session_id)
    target = payload.get("guardian_id")
    reached = 0
    for guardian in list(state.guardians):
        if target is None or str(guardian.guardian_id) == str(target):
            reached += guardian.post(type_, payload)
    return reached


async def from_guardian(hub: SessionHub, session_id: UUID, guardian_id: UUID, type_: str,
                        payload: dict[str, Any]) -> bool:
    """Guardian -> phone, with guardian_id added so the phone knows whom to answer."""
    return await hub.send_to_user(session_id, type_, {**payload, "guardian_id": str(guardian_id)})
