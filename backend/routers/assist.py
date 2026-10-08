# backend/routers/assist.py
"""POST /ask and POST /ocr, contract 7.9-7.10 (BE-12). Owner: Coder 3.
Gemini and OCR calls go through integrations.py, which bridges to Coder 4's code."""
import asyncio
import logging
import time
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, Request, UploadFile

import integrations
from auth import Auth, require_user
from config import API_PREFIX
from errors import AppError
from live.frame_worker import InvalidFrame, decode_b64, decode_jpeg, now_ms
from routers.detect import _read_image
from schemas import AskRequest, AskResponse, GroundedOn, OcrLine, OcrResponse

log = logging.getLogger("vision_assistant")
router = APIRouter(prefix=API_PREFIX, tags=["assist"])

FRESH_MS = 3000  # contract 7.9: the cached frame must be under 3 s old


async def _active_session(request: Request, session_id: UUID) -> dict:
    session = await request.app.state.repo.get_session(session_id)
    if session is None or session["status"] != "active":
        raise AppError("SESSION_NOT_FOUND", f"Session {session_id} does not exist or has ended.")
    return session


async def _decodable(data: bytes) -> None:
    try:
        await asyncio.to_thread(decode_jpeg, data)
    except InvalidFrame as exc:
        raise AppError("INVALID_FRAME", "Image could not be decoded as JPEG or PNG.") from exc


@router.post("/ask", response_model=AskResponse, responses={
    404: {"description": "SESSION_NOT_FOUND"}, 409: {"description": "NO_RECENT_FRAME"},
    503: {"description": "MODEL_NOT_READY (FEATURE_ASK=false)"}})
async def ask(body: AskRequest, request: Request, p: Auth) -> AskResponse:
    """Distances and directions in the answer come only from our detections (grounding rule).
    A Gemini failure is not an HTTP error: the answer comes back with source "fallback"."""
    if not request.app.state.settings.feature_ask:
        raise AppError("MODEL_NOT_READY", "Ask AI is switched off (FEATURE_ASK=false).")
    started = time.perf_counter()
    require_user(p, (await _active_session(request, body.session_id))["user_id"])
    state = request.app.state.hub.state(body.session_id)
    fresh = state.latest_at_ms is not None and now_ms() - state.latest_at_ms <= FRESH_MS

    if body.image is not None:
        try:
            jpeg = decode_b64(body.image)
        except InvalidFrame as exc:
            raise AppError("INVALID_FRAME", str(exc)) from exc
        await _decodable(jpeg)
    elif fresh:
        jpeg = state.latest_jpeg
    else:
        raise AppError("NO_RECENT_FRAME", "No camera frame from the last 3 seconds; send one with the question.")

    result = state.latest_result if fresh else None
    detections = result["detections"] if result else []
    path_info = {"path_clear": result["path_clear"], "clear_distance_m": result["clear_distance_m"]} if result else None
    answer, source = await integrations.ask(body.question, body.mode, detections, jpeg, path_info)
    latency_ms = round((time.perf_counter() - started) * 1000)
    log.info("ask: mode=%s source=%s latency_ms=%d detections=%d", body.mode, source, latency_ms, len(detections))
    return AskResponse(
        answer_id=uuid4(), question=body.question, answer=answer, spoken_text=answer, mode=body.mode,
        source=source, grounded_on=GroundedOn(frame_id=result["frame_id"] if result else None,
                                              detection_count=len(detections)),
        latency_ms=latency_ms,
    )


@router.post("/ocr", response_model=OcrResponse, responses={
    400: {"description": "INVALID_FRAME"}, 404: {"description": "SESSION_NOT_FOUND"},
    503: {"description": "MODEL_NOT_READY (FEATURE_OCR=false, or no OCR on this server)"}})
async def ocr(request: Request, p: Auth,
              image: Annotated[UploadFile, File(description="JPEG or PNG, max 5 MB")],
              session_id: Annotated[UUID | None, Form()] = None,
              interpret: Annotated[bool, Form()] = True) -> OcrResponse:
    """Reads text with Tesseract; with interpret=true Gemini turns it into a spoken sentence."""
    app = request.app
    if not app.state.settings.feature_ocr:
        raise AppError("MODEL_NOT_READY", "OCR is switched off (FEATURE_OCR=false).")
    started = time.perf_counter()
    data = await _read_image(image)
    if session_id is not None:
        require_user(p, (await _active_session(request, session_id))["user_id"])
    if app.state.models.ocr != "available":
        raise AppError("MODEL_NOT_READY", "OCR is not available: Tesseract is not installed (TESSERACT_CMD).")
    try:
        image_bgr = await asyncio.to_thread(decode_jpeg, data)
    except InvalidFrame as exc:
        raise AppError("INVALID_FRAME", "Image could not be decoded as JPEG or PNG.") from exc
    try:
        found = await integrations.read_text(image_bgr)
    except integrations.ModelNotReady as exc:
        raise AppError("MODEL_NOT_READY", str(exc)) from exc

    if not found["lines"]:
        spoken, source = integrations.NO_TEXT, "tesseract"
    elif interpret:
        spoken, source = await integrations.interpret(found["text"], data)
    else:
        spoken, source = " ".join(found["text"].split()), "tesseract"
    latency_ms = round((time.perf_counter() - started) * 1000)
    log.info("ocr: source=%s lines=%d latency_ms=%d", source, len(found["lines"]), latency_ms)
    return OcrResponse(text=found["text"], lines=[OcrLine(**line) for line in found["lines"]],
                       spoken_text=spoken, interpreted=source == "tesseract+gemini", source=source,
                       latency_ms=latency_ms)
