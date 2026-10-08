# backend/live/guardian_ws.py
"""Guardian WebSocket, contract section 6 (BE-08). Owner: Coder 3.
Read-only live view for now: welcome, snapshots, results, location, user_status and alerts.
guardian_message (BE-11) and ack_alert (BE-10) are accepted and ignored until those stories land."""
import asyncio
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from config import WS_CLOSE
from live import hub as hub_module
from live.hub import GuardianConnection, SessionHub, to_alert
from live.user_ws import receive_text, wait_for_hello
from routers.sessions import to_session
from schemas import (
    Envelope,
    ErrorCode,
    GuardianHelloPayload,
    GuardianUser,
    GuardianWelcomePayload,
    WsErrorPayload,
)

log = logging.getLogger("vision_assistant")
router = APIRouter()

# Valid contract 6.1 types handled by later stories; accepted silently until then.
NOT_YET_HANDLED = {"hello", "guardian_message", "ack_alert"}


def post_error(conn: GuardianConnection, code: ErrorCode, message: str) -> None:
    conn.post("error", WsErrorPayload(code=code, message=message).model_dump(mode="json"))


async def status_ticker(hub: SessionHub, session_id: UUID, conn: GuardianConnection) -> None:
    """user_status every 2 s while this guardian is connected (contract 6.2)."""
    while not conn.closed:
        await asyncio.sleep(hub_module.STATUS_INTERVAL_S)
        conn.post("user_status", hub.user_status(session_id))


def handle_message(conn: GuardianConnection, text: str | None) -> None:
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
            handle_message(conn, await receive_text(ws))
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("Guardian socket for session %s failed", session_id)
    finally:
        ticker.cancel()
        state.guardians.discard(conn)
        await conn.close()
