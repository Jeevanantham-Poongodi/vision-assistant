# backend/live/guardian_ws.py
"""Guardian WebSocket, contract section 6 (BE-08). Owner: Coder 3.
Live view (welcome, snapshots, results, location, user_status, alerts), ack_alert (BE-10) and
guardian_message (BE-11)."""
import asyncio
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from auth import socket_allows
from config import WS_CLOSE
from errors import AppError
from live import alerts, webrtc
from live.messages import send_guardian_message
from live import hub as hub_module
from live.hub import GuardianConnection, SessionHub, to_alert
from live.user_ws import receive_text, wait_for_hello
from routers.sessions import to_session
from schemas import (
    AckAlertPayload,
    GuardianMessagePayload,
    Envelope,
    ErrorCode,
    GuardianHelloPayload,
    GuardianUser,
    GuardianWelcomePayload,
    MessageDeliveredPayload,
    WsErrorPayload,
)

log = logging.getLogger("vision_assistant")
router = APIRouter()

# Valid contract 6.1 types handled by later stories; accepted silently until then.
NOT_YET_HANDLED = {"hello"}


def post_error(conn: GuardianConnection, code: ErrorCode, message: str) -> None:
    conn.post("error", WsErrorPayload(code=code, message=message).model_dump(mode="json"))


async def status_ticker(hub: SessionHub, session_id: UUID, conn: GuardianConnection) -> None:
    """user_status every 2 s while this guardian is connected (contract 6.2)."""
    while not conn.closed:
        await asyncio.sleep(hub_module.STATUS_INTERVAL_S)
        conn.post("user_status", hub.user_status(session_id))


async def handle_message(conn: GuardianConnection, hub: SessionHub, session_id: UUID, text: str | None) -> None:
    if text is None:
        post_error(conn, "UNSUPPORTED_MESSAGE", "Binary messages are not supported; send JSON text.")
        return
    try:
        env = Envelope.model_validate_json(text)
    except ValidationError:
        post_error(conn, "UNSUPPORTED_MESSAGE", "Message is not a valid envelope {v, type, ts, payload}.")
        return
    if env.type == "ping":
        conn.post("pong", {})
    elif env.type == "guardian_message":
        try:
            msg = GuardianMessagePayload.model_validate(env.payload)
        except ValidationError:
            post_error(conn, "UNSUPPORTED_MESSAGE", "guardian_message needs text: 1-200 characters, not blank.")
            return
        message_id, delivered = await send_guardian_message(hub, session_id, conn.guardian_id, msg.text)
        conn.post("message_delivered", MessageDeliveredPayload(
            message_id=message_id, text=msg.text, delivered=delivered).model_dump(mode="json"))
    elif env.type in webrtc.WEBRTC_TYPES:  # relayed to the phone with guardian_id added (BE-15)
        if webrtc.too_large(text):
            post_error(conn, "UNSUPPORTED_MESSAGE", "WebRTC signalling messages are limited to 64 KB.")
            return
        await webrtc.from_guardian(hub, session_id, conn.guardian_id, env.type, env.payload)
    elif env.type == "ack_alert":
        try:
            ack = AckAlertPayload.model_validate(env.payload)
        except ValidationError:
            post_error(conn, "UNSUPPORTED_MESSAGE", 'ack_alert needs alert_id and status "acknowledged" or "resolved".')
            return
        try:  # success is visible as alert_updated, which this guardian receives too
            await alerts.update_alert(hub, ack.alert_id, ack.status, conn.guardian_id)
        except AppError as exc:
            post_error(conn, exc.code, exc.message)
    elif env.type not in NOT_YET_HANDLED:
        post_error(conn, "UNSUPPORTED_MESSAGE", f"Unknown message type '{env.type}'.")


async def authorise(ws: WebSocket, session_id: UUID) -> tuple[dict[str, Any], UUID] | None:
    """Closes the socket and returns None unless this guardian may watch this session.
    One code (4001) for unknown, ended and unlinked, so a guardian cannot probe for sessions."""
    if not ws.app.state.settings.feature_guardian:
        await ws.close(code=WS_CLOSE["protocol"], reason="FEATURE_DISABLED")
        return None
    repo = ws.app.state.repo
    session = await repo.get_session(session_id)
    try:
        guardian_id = UUID(ws.query_params.get("guardian_id", ""))
    except ValueError:
        guardian_id = None
    if not socket_allows(ws, "guardian", guardian_id):  # BE-17, only with AUTH_REQUIRED=true
        await ws.close(code=WS_CLOSE["unauthorized"], reason="UNAUTHORIZED")
        return None
    linked = guardian_id is not None and session is not None and any(
        link["user_id"] == session["user_id"] for link in await repo.get_linked_users(guardian_id))
    if session is None or session["status"] != "active" or not linked:
        await ws.close(code=WS_CLOSE["session_not_found"], reason="SESSION_NOT_FOUND")
        return None
    return session, guardian_id


@router.websocket("/ws/guardian/{session_id}")
async def guardian_socket(ws: WebSocket, session_id: UUID) -> None:
    await ws.accept()  # accept first, or the client sees HTTP 403 instead of our close code
    allowed = await authorise(ws, session_id)
    if allowed is None:
        return
    session, guardian_id = allowed

    try:
        hello = await wait_for_hello(ws, GuardianHelloPayload)
    except WebSocketDisconnect:
        return
    if hello is None or hello[1].guardian_id != guardian_id:
        await ws.close(code=WS_CLOSE["protocol"], reason="Expected hello with the same guardian_id")
        return

    repo, hub = ws.app.state.repo, ws.app.state.hub
    state = hub.state(session_id)
    conn = GuardianConnection(ws, guardian_id)
    state.guardians.add(conn)
    ticker = asyncio.create_task(status_ticker(hub, session_id, conn))
    try:
        user = await repo.get_user(session["user_id"])
        open_alerts = [to_alert(a) for a in await repo.list_alerts(session_id, "open")]
        welcome = GuardianWelcomePayload(
            session=to_session(session, hub),
            user=GuardianUser(user_id=session["user_id"], name=user["name"] if user else "User"),
            open_alerts=open_alerts,
        )
        conn.post("welcome", welcome.model_dump(mode="json"))
        conn.post("user_status", hub.user_status(session_id))
        if state.latest_location is not None:  # a refreshed guardian page is not left empty
            conn.post("location", state.latest_location)
        while True:
            await handle_message(conn, hub, session_id, await receive_text(ws))
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("Guardian socket for session %s failed", session_id)
    finally:
        ticker.cancel()
        state.guardians.discard(conn)
        await conn.close()
