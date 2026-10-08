# backend/routers/media.py
"""POST /navigate, /tts, /stt, contract 7.16-7.18 (BE-16, P2). Owner: Coder 3.
The work is Coder 4's (navigation/maps.py, speech/server_audio.py), reached through integrations.py.
Without their modules each endpoint answers 503 MODEL_NOT_READY."""
import logging
import time
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from pydantic import ValidationError

import integrations
from auth import Auth, require_user
from config import API_PREFIX
from errors import AppError
from schemas import NavigateRequest, NavigateResponse, SttResponse, TtsRequest

log = logging.getLogger("vision_assistant")
router = APIRouter(prefix=API_PREFIX, tags=["media"])

MAX_AUDIO_BYTES = 10 * 1024 * 1024  # about 30 s of compressed speech (contract 7.18) with room to spare
AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/wav", "audio/x-wav", "audio/wave"}


@router.post("/navigate", response_model=NavigateResponse, responses={
    404: {"description": "SESSION_NOT_FOUND or DESTINATION_NOT_FOUND"},
    503: {"description": "MODEL_NOT_READY (FEATURE_NAVIGATION=false, or no navigation module)"}})
async def navigate(body: NavigateRequest, request: Request, p: Auth) -> NavigateResponse:
    """Walking route with spoken steps (Mapbox, through Coder 4's navigation/maps.py)."""
    if not request.app.state.settings.feature_navigation:
        raise AppError("MODEL_NOT_READY", "Navigation is switched off (FEATURE_NAVIGATION=false).")
    session = await request.app.state.repo.get_session(body.session_id)
    if session is None or session["status"] != "active":
        raise AppError("SESSION_NOT_FOUND", f"Session {body.session_id} does not exist or has ended.")
    require_user(p, session["user_id"])
    destination = body.destination if isinstance(body.destination, str) else body.destination.model_dump(mode="json", exclude_none=True)
    started = time.perf_counter()
    route = await integrations.navigate(body.origin.model_dump(mode="json", exclude_none=True), destination)
    route = {"route_id": str(uuid4()), **(route or {})}
    try:
        result = NavigateResponse.model_validate(route)
    except ValidationError as exc:
        log.exception("Navigation returned a route that does not match contract 7.16")
        raise AppError("MODEL_NOT_READY", "Navigation returned an invalid route.") from exc
    log.info("navigate: %d steps, %.0f m, latency_ms=%d", len(result.steps), result.total_distance_m,
             round((time.perf_counter() - started) * 1000))
    return result


@router.post("/tts", response_class=Response, responses={
    200: {"content": {"audio/mpeg": {}}, "description": "Spoken audio"},
    503: {"description": "MODEL_NOT_READY (no server-side TTS module)"}})
async def tts(body: TtsRequest, p: Auth) -> Response:  # any valid token
    """Server-side text-to-speech fallback; the phone normally speaks with the browser's own voice."""
    audio, media_type = await integrations.tts(body.text, body.lang)
    return Response(content=audio, media_type=media_type)


@router.post("/stt", response_model=SttResponse, responses={
    503: {"description": "MODEL_NOT_READY (no server-side STT module)"}})
async def stt(p: Auth, audio: Annotated[UploadFile, File(description="webm, ogg or wav, up to 30 s")],
              lang: Annotated[str, Form()] = "en-IN") -> SttResponse:
    """Server-side speech-to-text fallback for browsers without Web Speech recognition."""
    content_type = (audio.content_type or "").split(";")[0].strip().lower()
    if content_type not in AUDIO_TYPES:
        raise AppError("VALIDATION_ERROR", f"Audio must be webm, ogg or wav, not {content_type or 'unknown'}.",
                       details={"allowed": sorted(AUDIO_TYPES)})
    data = await audio.read(MAX_AUDIO_BYTES + 1)
    if not data:
        raise AppError("VALIDATION_ERROR", "Audio is empty.")
    if len(data) > MAX_AUDIO_BYTES:
        raise AppError("VALIDATION_ERROR", "Audio is larger than 10 MB (about 30 s is the limit).")
    out = await integrations.stt(data, content_type, lang)
    try:
        return SttResponse.model_validate({"text": out.get("text", ""), "confidence": out.get("confidence", 0.0)})
    except (AttributeError, ValidationError) as exc:
        raise AppError("MODEL_NOT_READY", "Speech-to-text returned an invalid result.") from exc
