"""FastAPI entry point. Owner: Coder 3. Run from backend/: uvicorn main:app --reload --port 8000"""
import asyncio
import logging
import shutil
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from config import API_PREFIX, APP_VERSION, OBJECT_CLASSES, THRESHOLDS, Settings, settings
from db.repo import InMemoryRepo
from errors import install_error_handlers
from live.hub import SessionHub
from routers import sessions
from schemas import (
    ConfigResponse,
    DetectorConfig,
    ErrorResponse,
    FrameConfig,
    HealthResponse,
    ModelState,
    ModelsStatus,
    SpeechConfig,
)

log = logging.getLogger("vision_assistant")


@dataclass
class Models:
    """Loaded once at startup and kept on app.state.models (contract 8.4)."""
    detector: Any = None  # vision.detector.Detector once Coder 2 ships it
    yolo: ModelState = "missing"
    ocr: ModelState = "missing"
    gemini: ModelState = "missing"


def _load_detector(s: Settings) -> Any:
    import numpy as np

    from vision.detector import Detector  # Coder 2, contract 8.2

    detector = Detector(model_path=s.yolo_model, conf=THRESHOLDS.detector_confidence, classes=list(OBJECT_CLASSES))
    # The first inference is slow (lazy init); do it now instead of on the user's first frame.
    detector.detect(np.zeros((480, 640, 3), dtype=np.uint8), track=False)
    return detector


async def load_models(s: Settings) -> Models:
    models = Models(
        ocr="available" if shutil.which(s.tesseract_cmd) else "missing",
        gemini="configured" if s.gemini_api_key else "missing",
    )
    if s.pipeline != "real":
        log.info("PIPELINE=%s: YOLO not loaded, /health reports degraded", s.pipeline)
        return models
    try:
        models.detector = await asyncio.to_thread(_load_detector, s)
        models.yolo = "loaded"
    except Exception:
        # Keep serving: /health reports degraded and /detect will answer MODEL_NOT_READY.
        log.exception("YOLO failed to load")
    return models


router = APIRouter(prefix=API_PREFIX)


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    models: Models = request.app.state.models
    return HealthResponse(
        status="ok" if models.yolo == "loaded" else "degraded",
        version=APP_VERSION,
        models=ModelsStatus(yolo=models.yolo, ocr=models.ocr, gemini=models.gemini),
        uptime_s=int(time.monotonic() - request.app.state.started_at),
    )


@router.get("/config", response_model=ConfigResponse)
def get_config(request: Request) -> ConfigResponse:
    s: Settings = request.app.state.settings
    t = THRESHOLDS
    return ConfigResponse(
        frame=FrameConfig(
            target_fps=t.frame.target_fps,
            max_width=t.frame.max_width,
            jpeg_quality=t.frame.jpeg_quality,
            max_in_flight=t.frame.max_in_flight,
        ),
        direction_zones=t.direction_zones,
        distance_zones_m=t.distance_zones_m,
        speech=SpeechConfig(
            cooldown_ms=t.speech.cooldown_ms,
            max_queue=t.speech.max_queue,
            stale_ms=t.speech.stale_ms,
            dedupe_ms=t.speech.dedupe_ms,
        ),
        detector=DetectorConfig(model=s.yolo_model, confidence=t.detector_confidence, classes=list(OBJECT_CLASSES)),
    )


def create_app(s: Settings = settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.started_at = time.monotonic()
        app.state.models = await load_models(s)
        yield

    app = FastAPI(
        title="Vision Assistant API",
        version=APP_VERSION,
        lifespan=lifespan,
        # Every route documents the 11.1 error body instead of FastAPI's default HTTPValidationError.
        responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )
    app.state.settings = s
    app.state.repo = InMemoryRepo()  # BE-09 swaps in the Supabase repository
    app.state.hub = SessionHub()
    app.state.session_lock = asyncio.Lock()
    install_error_handlers(app)  # before CORS, so CORS also wraps 500 responses
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    app.include_router(sessions.router)
    return app


app = create_app()
