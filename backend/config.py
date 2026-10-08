# backend/config.py
"""Settings from backend/.env (contract 9.3) and the fixed thresholds from contract section 3.
Owner: Coder 3. If a value here and API_CONTRACTS.md disagree, the contract wins: fix this file."""
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from schemas import Category, Direction, DistanceZone, ObjectClass, RiskLevel

APP_VERSION = "1.0.0"
API_PREFIX = "/api/v1"

# Contract 2.1: class_name -> (spoken_name, category). Classes not listed here are dropped by the detector.
OBJECT_CLASSES: dict[ObjectClass, tuple[str, Category]] = {
    "person": ("person", "person"),
    "bicycle": ("bicycle", "vehicle"),
    "car": ("car", "vehicle"),
    "motorcycle": ("motorcycle", "vehicle"),
    "bus": ("bus", "vehicle"),
    "truck": ("truck", "vehicle"),
    "traffic_light": ("traffic light", "signal"),
    "stop_sign": ("stop sign", "signal"),
    "fire_hydrant": ("fire hydrant", "obstacle"),
    "bench": ("bench", "obstacle"),
    "chair": ("chair", "obstacle"),
    "dining_table": ("table", "obstacle"),
    "potted_plant": ("plant pot", "obstacle"),
    "backpack": ("bag", "obstacle"),
    "suitcase": ("suitcase", "obstacle"),
    "dog": ("dog", "animal"),
    "cow": ("cow", "animal"),
    "bottle": ("bottle", "other"),
}


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class FrameRules(_Frozen):
    """Contract 5.2 and 7.3."""
    target_fps: int = 5
    max_width: int = 640
    jpeg_quality: float = 0.65
    max_in_flight: int = 1
    max_age_ms: int = 1000  # the server drops frames older than this
    max_image_bytes: int = 5 * 1024 * 1024
    hello_timeout_ms: int = 5000  # 5.4: no hello within this -> close 4003


class RiskRules(_Frozen):
    """Contract 3.1 (evaluated R1 to R7, first match wins) and the path_clear rule in 3.2."""
    corridor: tuple[Direction, ...] = ("slight_left", "center", "slight_right")
    very_close_m: float = 1.0        # R1: corridor, < 1.0 -> critical
    near_m: float = 2.0              # R4: corridor, 1.0 to < 2.0 -> high
    medium_m: float = 5.0            # R5/R6: < 5.0 -> medium
    vehicle_critical_m: float = 3.0  # R2: approaching vehicle, < 3.0 -> critical
    vehicle_high_m: float = 5.0      # R3: approaching vehicle, < 5.0 -> high
    nearby_categories: tuple[Category, ...] = ("vehicle", "animal")  # R5
    priority: dict[RiskLevel, int] = {"critical": 100, "high": 80, "medium": 50, "low": 20}
    max_score_bonus: float = 0.1     # risk_score = priority / 100 + up to this, capped at 1.0
    path_clear_m: float = 3.0        # path_clear when nothing in the corridor is closer than this


class SpeechRules(_Frozen):
    """Contract 3.2."""
    max_warnings_per_frame: int = 2
    cooldown_ms: dict[RiskLevel, int] = {"critical": 1500, "high": 3000, "medium": 6000}
    interrupt_levels: tuple[RiskLevel, ...] = ("critical",)
    silent_levels: tuple[RiskLevel, ...] = ("low",)  # never auto-spoken
    max_queue: int = 2
    stale_ms: int = 2000
    dedupe_ms: int = 3000


class AlertRules(_Frozen):
    """Contract 3.3."""
    hazard_levels: tuple[RiskLevel, ...] = ("critical", "high")
    hazard_throttle_ms: int = 10_000  # per cooldown key
    offline_alert_throttle_ms: int = 60_000  # system alert "user went offline": max one per minute


class LiveRules(_Frozen):
    """Contract 5.2 and 6.2: guardian relays and user liveness (BE-08)."""
    relay_interval_ms: int = 500          # snapshot + frame_result to guardians: max 2 per second
    user_status_interval_ms: int = 2000   # user_status to each guardian
    silence_timeout_ms: int = 10_000      # no message from the phone for this long -> offline
    guardian_queue_size: int = 32         # outgoing messages buffered per guardian
    guardian_max_drops: int = 3           # a guardian that misses this many in a row is closed
    location_ping_interval_ms: int = 10_000  # contract 10: at most one stored location per 10 s per session


class Thresholds(_Frozen):
    # Contract 2.3: [low, high) on cx_norm; center is closed on both ends.
    direction_zones: dict[Direction, tuple[float, float]] = {
        "left": (0.0, 0.2),
        "slight_left": (0.2, 0.4),
        "center": (0.4, 0.6),
        "slight_right": (0.6, 0.8),
        "right": (0.8, 1.0),
    }
    # Contract 2.4: upper bound (exclusive) of each zone; >= medium is "far".
    distance_zones_m: dict[DistanceZone, float] = {"very_close": 1.0, "near": 2.0, "medium": 5.0}
    detector_confidence: float = 0.4
    frame: FrameRules = FrameRules()
    risk: RiskRules = RiskRules()
    speech: SpeechRules = SpeechRules()
    alerts: AlertRules = AlertRules()
    live: LiveRules = LiveRules()


THRESHOLDS = Thresholds()

# Contract 5.4: WebSocket close codes.
WS_CLOSE = {
    "normal": 1000,
    "session_not_found": 4001,  # unknown session or already ended
    "replaced": 4002,           # a newer connection took over the session
    "protocol": 4003,           # e.g. no valid hello within 5 s
}


class Settings(BaseSettings):
    # Blank lines like KEY= in .env fall back to the defaults below.
    model_config = SettingsConfigDict(
        env_file=Path(__file__).with_name(".env"), extra="ignore", env_ignore_empty=True
    )

    # Coder 3: backend
    pipeline: Literal["stub", "real"] = "stub"
    allowed_origins: str = "http://localhost:5173"
    # Demo only: e.g. ^https://[a-z0-9-]+\.trycloudflare\.com$ so a new tunnel URL needs no restart.
    # It lets any trycloudflare.com page call the API from a browser; leave empty outside the demo.
    allowed_origin_regex: str = ""
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    feature_guardian: bool = False
    feature_alerts_db: bool = False
    debug_save_frames: bool = False

    # Coder 2: vision
    yolo_model: str = "yolov8n.pt"
    camera_focal_px: float = 800.0

    # Coder 4: integrations
    gemini_api_key: str = ""
    gemini_model: str = ""
    tesseract_cmd: str = "tesseract"
    mapbox_token: str = ""
    feature_ask: bool = False
    feature_ocr: bool = False
    feature_navigation: bool = False

    @field_validator("supabase_url")
    @classmethod
    def _strip_rest_path(cls, v: str) -> str:
        # The client adds /rest/v1 itself; people often paste the REST endpoint.
        v = v.strip().rstrip("/")
        return v.removesuffix("/rest/v1")

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def supabase_enabled(self) -> bool:
        return self.feature_alerts_db and bool(self.supabase_url and self.supabase_service_role_key)


settings = Settings()
