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
from db.repo import InMemoryRepo, SupabaseRepo
from errors import install_error_handlers
import integrations
from live import guardian_ws, user_ws
from live.hub import SessionHub
from routers import alerts, assist, detect, guardians, sessions
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

# Without a handler, INFO lines (e.g. the per-session fps/latency summary) never show under uvicorn.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
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


def make_repo(s: Settings) -> InMemoryRepo:
    """Supabase when FEATURE_ALERTS_DB=true and the URL and key are set; memory only otherwise."""
    if not s.supabase_enabled:
        return InMemoryRepo()
    try:
        from db.client import SupabaseClient

        return SupabaseRepo(SupabaseClient(s.supabase_url, s.supabase_service_role_key))
    except Exception as exc:  # e.g. a malformed URL: run from memory rather than not at all
        log.warning("Supabase disabled: could not create the client (%s)", type(exc).__name__)
        return InMemoryRepo()


def create_app(s: Settings = settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.started_at = time.monotonic()
        integrations.export_env(s)  # Coder 4's Gemini/OCR code reads os.environ
        await app.state.repo.start()  # Supabase: load users, links, active sessions, open alerts
        app.state.models = await load_models(s)
        yield
        await app.state.repo.close()  # Supabase: let queued writes finish (max 5 s)

    app = FastAPI(
        title="Vision Assistant API",
        version=APP_VERSION,
        lifespan=lifespan,
        # Every route documents the 11.1 error body instead of FastAPI's default HTTPValidationError.
        responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    )
    app.state.settings = s
    app.state.repo = make_repo(s)
    app.state.hub = SessionHub(app.state.repo)  # the hub raises system alerts through the repo
    app.state.session_lock = asyncio.Lock()
    app.state.detect_lock = asyncio.Lock()  # POST /detect shares the startup detector
    install_error_handlers(app)  # before CORS, so CORS also wraps 500 responses
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_origin_regex=s.allowed_origin_regex or None,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    app.include_router(sessions.router)
    app.include_router(detect.router)
    app.include_router(alerts.router)
    app.include_router(assist.router)
    app.include_router(guardians.router)
    app.include_router(user_ws.router)
    app.include_router(guardian_ws.router)
    return app


app = create_app()
