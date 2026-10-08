# backend/live/user_ws.py
"""User device WebSocket, contract section 5. Owner: Coder 3.
Frames go to a FrameWorker (live/frame_worker.py): latest frame wins, pipeline in a thread."""
import asyncio
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from auth import socket_allows
from config import THRESHOLDS, WS_CLOSE
from errors import AppError
from live import alerts, webrtc
from live.frame_worker import FrameWorker, now_ms
from live.hub import SessionHub
from schemas import (
    EmergencyPayload,
    Envelope,
    ErrorCode,
    HelloPayload,
    Location,
    StatusPayload,
    WelcomeConfig,
    WelcomePayload,
    WsErrorPayload,
)

log = logging.getLogger("vision_assistant")
router = APIRouter()

HELLO_TIMEOUT_S = THRESHOLDS.frame.hello_timeout_ms / 1000
# A repeated hello is accepted silently.
NOT_YET_HANDLED = {"hello"}


class Connection:
    """One user socket. The send lock stops the frame task and the receive loop writing at once."""

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self._send_lock = asyncio.Lock()

    async def send(self, type_: str, payload: dict[str, Any]) -> None:
        async with self._send_lock:
            await self.ws.send_json({"v": 1, "type": type_, "ts": now_ms(), "payload": payload})

    async def send_error(self, code: ErrorCode, message: str, frame_id: int | None = None) -> None:
        payload = WsErrorPayload(code=code, message=message, frame_id=frame_id)
        await self.send("error", payload.model_dump(mode="json"))


async def handle_message(conn: Connection, worker: FrameWorker, hub: SessionHub, session_id: UUID,
                         text: str) -> None:
    try:
        env = Envelope.model_validate_json(text)
    except ValidationError:
        await conn.send_error("UNSUPPORTED_MESSAGE", "Message is not a valid envelope {v, type, ts, payload}.")
        return
    hub.mark_seen(session_id)  # any valid message is a sign of life (BE-08 offline detection)
    state = hub.state(session_id)
    if env.type == "frame":
        await worker.submit(env)
    elif env.type == "ping":
        await conn.send("pong", {})
    elif env.type == "location":
        try:
            location = Location.model_validate(env.payload)
        except ValidationError:
            await conn.send_error("UNSUPPORTED_MESSAGE", "location needs lat, lng and ts (contract 4.5).")
            return
        state.latest_location = location.model_dump(mode="json")
        hub.broadcast(session_id, "location", state.latest_location)  # relayed as received
        if hub.repo is not None:
            await hub.repo.insert_location(session_id, state.latest_location)  # stored max once per 10 s
    elif env.type == "status":
        try:
            status = StatusPayload.model_validate(env.payload)
        except ValidationError:
            await conn.send_error("UNSUPPORTED_MESSAGE", "status needs battery_pct (0-100 or null), fps, camera.")
            return
        state.client_status = status.model_dump(mode="json")
    elif env.type == "emergency":
        try:
            emergency = EmergencyPayload.model_validate(env.payload)
        except ValidationError:
            await conn.send_error("UNSUPPORTED_MESSAGE", 'emergency needs trigger "button" or "voice".')
            return
        try:  # alert to guardians + emergency_ack back to this phone (contract 5.3)
            await alerts.trigger_emergency(hub, session_id, emergency.trigger, note=emergency.note)
        except AppError as exc:
            await conn.send_error(exc.code, exc.message)
    elif env.type in webrtc.WEBRTC_TYPES:  # relayed to guardians (BE-15)
        if webrtc.too_large(text):
            await conn.send_error("UNSUPPORTED_MESSAGE", "WebRTC signalling messages are limited to 64 KB.")
            return
        webrtc.from_user(hub, session_id, env.type, env.payload)
    elif env.type not in NOT_YET_HANDLED:
        await conn.send_error("UNSUPPORTED_MESSAGE", f"Unknown message type '{env.type}'.")


async def receive_text(ws: WebSocket) -> str | None:
    """Next text message, or None for a binary one. Raises WebSocketDisconnect when the client leaves."""
    message = await ws.receive()
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(message.get("code", 1000))
    return message.get("text")


async def wait_for_hello(ws: WebSocket, model: type[BaseModel] = HelloPayload) -> tuple[Envelope, Any] | None:
    """The first message must be hello within 5 s (HELLO_TIMEOUT_S); anything else returns None.
    The guardian socket reuses this with its own payload model."""
    try:
        text = await asyncio.wait_for(receive_text(ws), HELLO_TIMEOUT_S)
        env = Envelope.model_validate_json(text or "")
        return (env, model.model_validate(env.payload)) if env.type == "hello" else None
    except (TimeoutError, ValidationError):
        return None


@router.websocket("/ws/user/{session_id}")
async def user_socket(ws: WebSocket, session_id: UUID) -> None:
    # Accept first: closing before accept gives the client an HTTP 403 without our close code.
    await ws.accept()
    session = await ws.app.state.repo.get_session(session_id)
    if session is None or session["status"] != "active":
        await ws.close(code=WS_CLOSE["session_not_found"], reason="SESSION_NOT_FOUND")
        return
    if not socket_allows(ws, "user", session["user_id"]):  # BE-17, only with AUTH_REQUIRED=true
        await ws.close(code=WS_CLOSE["unauthorized"], reason="UNAUTHORIZED")
        return

    try:
        hello = await wait_for_hello(ws)
    except WebSocketDisconnect:
        return
    if hello is None or hello[1].user_id != session["user_id"]:
        await ws.close(code=WS_CLOSE["protocol"], reason="Expected hello with this session's user_id")
        return

    hub: SessionHub = ws.app.state.hub
    state = hub.state(session_id)
    old, state.user_ws = state.user_ws, ws
    if old is not None:
        try:
            await old.close(code=WS_CLOSE["replaced"], reason="Replaced by a newer connection")
        except Exception:
            log.debug("Old user socket for %s was already closed", session_id, exc_info=True)

    conn = Connection(ws)
    state.user_conn = conn  # emergency_ack from REST or a guardian goes through this lock
    worker = FrameWorker(session_id, state, ws.app.state.settings, conn.send, conn.send_error,
                         hello_ts=hello[0].ts, hub_=hub)
    f = THRESHOLDS.frame
    welcome = WelcomePayload(session_id=session_id, config=WelcomeConfig(
        target_fps=f.target_fps, max_width=f.max_width, jpeg_quality=f.jpeg_quality))
    watchdog = asyncio.create_task(hub.watch_silence(session_id, ws))
    try:
        await conn.send("welcome", welcome.model_dump(mode="json"))
        hub.user_connected(session_id)  # guardians see the user come online
        while True:
            text = await receive_text(ws)
            try:
                if text is None:
                    await conn.send_error("UNSUPPORTED_MESSAGE", "Binary messages are not supported; send JSON text.")
                else:
                    await handle_message(conn, worker, hub, session_id, text)
            except WebSocketDisconnect:
                raise
            except Exception:
                log.exception("Error handling a message on session %s", session_id)
                await conn.send_error("INTERNAL", "Internal server error.")
    except WebSocketDisconnect:
        pass
    finally:
        watchdog.cancel()
        await worker.close()
        if state.user_conn is conn:
            state.user_conn = None
        # Offline for guardians right away; the system alert only if the phone stays gone. Does
        # nothing for a replaced connection (it must not mark the new one offline) or an ended session.
        hub.user_disconnected(session_id, ws)
