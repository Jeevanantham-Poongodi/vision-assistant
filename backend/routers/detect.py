# backend/routers/detect.py
"""POST /detect, contract 7.8: one image -> FrameResult, for Postman, QA and as a fallback. Owner: Coder 3."""
import asyncio
import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, File, Form, Request, UploadFile
from pydantic import ValidationError

from config import API_PREFIX, THRESHOLDS
from errors import AppError
from live.frame_worker import InvalidFrame, decode_jpeg, now_ms
from schemas import FrameResult
from vision.pipelines import make_pipeline, make_stateless_pipeline

log = logging.getLogger("vision_assistant")
router = APIRouter(prefix=API_PREFIX, tags=["vision"])


async def _read_image(image: UploadFile) -> bytes:
    limit = THRESHOLDS.frame.max_image_bytes
    data = await image.read(limit + 1)  # never load more than the limit
    if len(data) > limit:
        raise AppError("INVALID_FRAME", "Image is larger than 5 MB.")
    if not data:
        raise AppError("INVALID_FRAME", "Image is empty.")
    return data


def _decode_and_process(pipeline: Any, data: bytes, frame_id: int, ts: int) -> dict:
    return pipeline.process(decode_jpeg(data), frame_id, ts)  # cv2.imdecode reads JPEG and PNG


async def _process(pipeline: Any, data: bytes, frame_id: int, ts: int) -> dict:
    try:
        result = await asyncio.to_thread(_decode_and_process, pipeline, data, frame_id, ts)
    except InvalidFrame as exc:
        raise AppError("INVALID_FRAME", "Image could not be decoded as JPEG or PNG.") from exc
    except Exception as exc:
        log.exception("Vision pipeline failed on /detect")
        raise AppError("PIPELINE_ERROR", "Vision failed on this image.") from exc
    try:
        return FrameResult.model_validate(result).model_dump(mode="json")
    except ValidationError as exc:
        log.exception("Pipeline result does not match FrameResult (contract 4.4)")
        raise AppError("PIPELINE_ERROR", "Vision returned an invalid result.") from exc


@router.post("/detect", response_model=FrameResult, responses={
    400: {"description": "INVALID_FRAME"}, 404: {"description": "SESSION_NOT_FOUND"},
    503: {"description": "MODEL_NOT_READY"}})
async def detect(request: Request,
                 image: Annotated[UploadFile, File(description="JPEG or PNG, max 5 MB")],
                 session_id: Annotated[UUID | None, Form()] = None) -> dict:
    """Without session_id: frame_id 0, motion "unknown". With it: the session's own pipeline."""
    app = request.app
    settings = app.state.settings
    data = await _read_image(image)
    ts = now_ms()

    if session_id is None:
        if settings.pipeline != "stub" and app.state.models.yolo != "loaded":
            raise AppError("MODEL_NOT_READY", "The vision model is not loaded yet.")
        async with app.state.detect_lock:  # the shared startup detector is not thread-safe
            pipeline = make_stateless_pipeline(settings, app.state.models.detector)
            return await _process(pipeline, data, frame_id=0, ts=ts)

    session = await app.state.repo.get_session(session_id)
    if session is None or session["status"] != "active":
        raise AppError("SESSION_NOT_FOUND", f"Session {session_id} does not exist or has ended.")
    state = app.state.hub.state(session_id)
    async with state.pipeline_lock:  # same pipeline as the session's socket: tracking and cooldowns carry over
        if state.pipeline is None:
            try:
                state.pipeline = await asyncio.to_thread(make_pipeline, settings)
            except Exception as exc:
                log.exception("Could not create the vision pipeline for session %s", session_id)
                raise AppError("MODEL_NOT_READY", "The vision model is not available.") from exc
        state.detect_count += 1
        result = await _process(state.pipeline, data, frame_id=state.detect_count, ts=ts)
    state.latest_jpeg, state.latest_result, state.latest_at_ms = data, result, now_ms()
    return result
