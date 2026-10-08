# backend/live/hub.py
"""In-memory session hub: per session, the user socket, guardian sockets and the vision
pipeline. Owner: Coder 3. BE-04/05/08 add the frame loop, caches and relays."""
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from fastapi import WebSocket

log = logging.getLogger("vision_assistant")


@dataclass
class SessionState:
    user_ws: WebSocket | None = None
    guardian_ws: set[WebSocket] = field(default_factory=set)
    pipeline: Any = None  # vision.pipeline.VisionPipeline, created on hello (BE-05)


class SessionHub:
    def __init__(self) -> None:
        self._sessions: dict[UUID, SessionState] = {}

    def state(self, session_id: UUID) -> SessionState:
        return self._sessions.setdefault(session_id, SessionState())

    def is_online(self, session_id: UUID) -> bool:
        s = self._sessions.get(session_id)
        return s is not None and s.user_ws is not None

    async def close_session(self, session_id: UUID, code: int = 1000) -> None:
        """Closes every socket of the session and drops its state, including the pipeline."""
        s = self._sessions.pop(session_id, None)
        if s is None:
            return
        for ws in [w for w in (s.user_ws, *s.guardian_ws) if w is not None]:
            try:
                await ws.close(code=code)
            except Exception:
                # Already closed or broken; it must not stop the others from closing.
                log.debug("Socket for session %s was already closed", session_id, exc_info=True)
