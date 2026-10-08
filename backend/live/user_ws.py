# backend/live/user_ws.py
"""User device WebSocket, contract section 5. Owner: Coder 3.
PIPELINE=stub answers every frame with the contract 13.1 mock (BE-04); BE-05 adds the real pipeline."""
import asyncio
import base64
import binascii
import copy
import json
import logging
import time
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from config import THRESHOLDS, WS_CLOSE
from schemas import (
    Envelope,
    ErrorCode,
    FramePayload,
    FrameResult,
    HelloPayload,
    WelcomeConfig,
    WelcomePayload,
    WsErrorPayload,
)

log = logging.getLogger("vision_assistant")
router = APIRouter()

HELLO_TIMEOUT_S = THRESHOLDS.frame.hello_timeout_ms / 1000
# Valid contract 5.2 types whose handling arrives later (BE-08, BE-10); accepted silently until then.
NOT_YET_HANDLED = {"hello", "location", "status", "emergency"}

_FIXTURE = Path(__file__).with_name("fixtures") / "frame_result.vehicle_right.json"
STUB_RESULT: dict[str, Any] = json.loads(_FIXTURE.read_text(encoding="utf-8"))["payload"]
FrameResult.model_validate(STUB_RESULT)  # a broken fixture fails at import, not on the phone


class InvalidFrame(Exception):
    pass


def now_ms() -> int:
    return int(time.time() * 1000)


async def send(ws: WebSocket, type_: str, payload: dict[str, Any]) -> None:
    await ws.send_json({"v": 1, "type": type_, "ts": now_ms(), "payload": payload})


async def send_error(ws: WebSocket, code: ErrorCode, message: str, frame_id: int | None = None) -> None:
    await send(ws, "error", WsErrorPayload(code=code, message=message, frame_id=frame_id).model_dump(mode="json"))


def decode_frame(image_b64: str) -> Any:
    """base64 JPEG -> BGR numpy array. Raises InvalidFrame."""
    try:
        data = base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidFrame("Image is not valid base64.") from exc
    if len(data) > THRESHOLDS.frame.max_image_bytes:
        raise InvalidFrame("Image is larger than 5 MB.")
    import cv2  # installed by ultralytics (requirements/vision.txt)
    import numpy as np

    frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise InvalidFrame("Image could not be decoded as JPEG.")
    return frame


def stub_frame_result(frame_id: int, ts_captured: int) -> dict[str, Any]:
    result = copy.deepcopy(STUB_RESULT)
    ts_processed = max(now_ms(), ts_captured)
    result.update(frame_id=frame_id, ts_captured=ts_captured, ts_processed=ts_processed,
                  latency_ms=ts_processed - ts_captured)
    return result


async def handle_frame(ws: WebSocket, env: Envelope) -> None:
    raw_id = env.payload.get("frame_id")
    try:
        frame = FramePayload.model_validate(env.payload)
    except ValidationError:
        await send_error(ws, "INVALID_FRAME", "Frame payload needs frame_id, image, width and height.",
                         raw_id if isinstance(raw_id, int) else None)
        return
    try:
        decode_frame(frame.image)  # BE-05 passes the decoded image to the vision pipeline
    except InvalidFrame as exc:
        await send_error(ws, "INVALID_FRAME", str(exc), frame.frame_id)
        return
    if ws.app.state.settings.pipeline != "stub":
        await send_error(ws, "PIPELINE_ERROR", "The real pipeline arrives in BE-05; use PIPELINE=stub.",
                         frame.frame_id)
        return
    await send(ws, "frame_result", stub_frame_result(frame.frame_id, env.ts))


async def handle_message(ws: WebSocket, text: str) -> None:
    try:
        env = Envelope.model_validate_json(text)
    except ValidationError:
        await send_error(ws, "UNSUPPORTED_MESSAGE", "Message is not a valid envelope {v, type, ts, payload}.")
        return
    if env.type == "frame":
        await handle_frame(ws, env)
    elif env.type == "ping":
        await send(ws, "pong", {})
    elif env.type not in NOT_YET_HANDLED:
        await send_error(ws, "UNSUPPORTED_MESSAGE", f"Unknown message type '{env.type}'.")


async def receive_text(ws: WebSocket) -> str | None:
    """Next text message, or None for a binary one. Raises WebSocketDisconnect when the client leaves."""
    message = await ws.receive()
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(message.get("code", 1000))
    return message.get("text")


async def wait_for_hello(ws: WebSocket) -> HelloPayload | None:
    """The first message must be hello within 5 s; anything else returns None."""
    try:
        text = await asyncio.wait_for(receive_text(ws), HELLO_TIMEOUT_S)
        env = Envelope.model_validate_json(text or "")
        return HelloPayload.model_validate(env.payload) if env.type == "hello" else None
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

    try:
        hello = await wait_for_hello(ws)
    except WebSocketDisconnect:
        return
    if hello is None or hello.user_id != session["user_id"]:
        await ws.close(code=WS_CLOSE["protocol"], reason="Expected hello with this session's user_id")
        return

    state = ws.app.state.hub.state(session_id)
    old, state.user_ws = state.user_ws, ws
    if old is not None:
        try:
            await old.close(code=WS_CLOSE["replaced"], reason="Replaced by a newer connection")
        except Exception:
            log.debug("Old user socket for %s was already closed", session_id, exc_info=True)

    f = THRESHOLDS.frame
    welcome = WelcomePayload(session_id=session_id, config=WelcomeConfig(
        target_fps=f.target_fps, max_width=f.max_width, jpeg_quality=f.jpeg_quality))
    try:
        await send(ws, "welcome", welcome.model_dump(mode="json"))
        while True:
            text = await receive_text(ws)
            try:
                if text is None:
                    await send_error(ws, "UNSUPPORTED_MESSAGE", "Binary messages are not supported; send JSON text.")
                else:
                    await handle_message(ws, text)
            except WebSocketDisconnect:
                raise
            except Exception:
                log.exception("Error handling a message on session %s", session_id)
                await send_error(ws, "INTERNAL", "Internal server error.")
    except WebSocketDisconnect:
        pass
    finally:
        if state.user_ws is ws:  # a replaced connection must not mark the new one offline
            state.user_ws = None
