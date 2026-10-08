# backend/schemas.py
"""Pydantic v2 models for API_CONTRACTS.md: enums (section 2), core models (section 4) and
REST bodies (section 7). Owner: Coder 3. If this file and the contract disagree, the contract wins.
WebSocket envelopes (sections 5 and 6) are added with BE-04 and BE-08."""
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, PlainSerializer, model_validator

# --- Section 2: shared enums ---------------------------------------------------------------

ObjectClass = Literal[
    "person", "bicycle", "car", "motorcycle", "bus", "truck", "traffic_light", "stop_sign",
    "fire_hydrant", "bench", "chair", "dining_table", "potted_plant", "backpack", "suitcase",
    "dog", "cow", "bottle",
]
Category = Literal["person", "vehicle", "obstacle", "animal", "signal", "other"]
Direction = Literal["left", "slight_left", "center", "slight_right", "right"]
DistanceZone = Literal["very_close", "near", "medium", "far", "unknown"]
DistanceMethod = Literal["pinhole", "depth_model", "edge_clipped", "none"]
Motion = Literal["approaching", "receding", "stationary", "unknown"]
RiskLevel = Literal["critical", "high", "medium", "low"]
RuleId = Literal["R1", "R2", "R3", "R4", "R5", "R6", "R7"]
AlertType = Literal["hazard", "emergency", "assistance_request", "system"]
AlertStatus = Literal["open", "acknowledged", "resolved"]
VoiceIntent = Literal["emergency", "read_text", "path_check", "describe", "ask", "stop_speaking", "repeat"]

SessionStatus = Literal["active", "ended"]
AskMode = Literal["question", "describe", "path_check"]
AnswerSource = Literal["gemini", "fallback"]
OcrSource = Literal["tesseract", "tesseract+gemini"]
EmergencyTrigger = Literal["button", "voice"]
ModelState = Literal["loaded", "available", "configured", "missing"]
HealthStatus = Literal["ok", "degraded"]

# --- Shared field types --------------------------------------------------------------------

Probability = Annotated[float, Field(ge=0.0, le=1.0)]
Pixel = Annotated[int, Field(ge=0)]
EpochMs = Annotated[int, Field(ge=0)]
NonNegative = Annotated[float, Field(ge=0.0)]


def _iso_utc_ms(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# Contract 1: REST timestamps are ISO 8601 UTC, e.g. "2026-10-08T10:15:30.120Z".
UtcDatetime = Annotated[AwareDatetime, PlainSerializer(_iso_utc_ms, return_type=str, when_used="json")]


class ContractModel(BaseModel):
    """Unknown fields are rejected so typos and contract drift fail loudly."""
    model_config = ConfigDict(extra="forbid")


# --- Section 4: core models ----------------------------------------------------------------

class BBox(ContractModel):
    x1: Pixel
    y1: Pixel
    x2: Pixel
    y2: Pixel

    @model_validator(mode="after")
    def _ordered(self) -> "BBox":
        if self.x1 >= self.x2 or self.y1 >= self.y2:
            raise ValueError("bbox needs x1 < x2 and y1 < y2")
        return self


class Detection(ContractModel):
    track_id: int | None
    class_name: ObjectClass
    spoken_name: str
    category: Category
    confidence: Probability
    bbox: BBox
    cx_norm: Probability
    direction: Direction
    distance_m: NonNegative | None
    distance_zone: DistanceZone
    distance_method: DistanceMethod
    motion: Motion
    approach_speed_mps: float | None  # positive = getting closer
    risk_level: RiskLevel
    risk_score: Probability


class Warning(ContractModel):  # noqa: A001 - name mirrors the contract; shadows the builtin only here
    warning_id: UUID
    track_id: int | None
    class_name: ObjectClass
    risk_level: RiskLevel
    priority: Annotated[int, Field(ge=0, le=100)]
    message: str
    short_text: str
    speak: bool
    interrupt: bool
    rule: RuleId


class FrameSize(ContractModel):
    width: Annotated[int, Field(gt=0)]
    height: Annotated[int, Field(gt=0)]


class FrameResult(ContractModel):
    frame_id: Annotated[int, Field(ge=0)]  # 0 for /detect without a session
    frame_size: FrameSize
    ts_captured: EpochMs
    ts_processed: EpochMs
    latency_ms: int
    inference_ms: Annotated[int, Field(ge=0)]
    detections: list[Detection]
    warnings: Annotated[list[Warning], Field(max_length=2)]  # contract 3.2
    path_clear: bool
    clear_distance_m: NonNegative | None
    low_confidence_scene: bool


class GeoPoint(ContractModel):
    lat: Annotated[float, Field(ge=-90, le=90)]
    lng: Annotated[float, Field(ge=-180, le=180)]
    accuracy_m: NonNegative | None = None


class Location(GeoPoint):
    heading_deg: Annotated[float, Field(ge=0, lt=360)] | None = None
    speed_mps: NonNegative | None = None
    ts: EpochMs


class Alert(ContractModel):
    alert_id: UUID
    session_id: UUID | None  # null if the session was deleted
    user_id: UUID
    type: AlertType
    risk_level: RiskLevel
    title: str
    message: str
    location: GeoPoint | None
    snapshot_b64: str | None  # WebSocket only, never stored
    status: AlertStatus
    created_at: UtcDatetime
    acknowledged_by: UUID | None
    acknowledged_at: UtcDatetime | None


class Session(ContractModel):
    session_id: UUID
    user_id: UUID
    status: SessionStatus
    started_at: UtcDatetime
    ended_at: UtcDatetime | None
    device_info: dict[str, Any]
    user_online: bool
    ws_url: str
    guardian_ws_url: str


# --- Section 7: REST bodies ----------------------------------------------------------------

class ModelsStatus(ContractModel):
    yolo: ModelState
    ocr: ModelState
    gemini: ModelState


class HealthResponse(ContractModel):  # 7.2
    status: HealthStatus
    version: str
    models: ModelsStatus
    uptime_s: Annotated[int, Field(ge=0)]


class FrameConfig(ContractModel):
    target_fps: int
    max_width: int
    jpeg_quality: float
    max_in_flight: int


class SpeechConfig(ContractModel):
    cooldown_ms: dict[RiskLevel, int]
    max_queue: int
    stale_ms: int
    dedupe_ms: int


class DetectorConfig(ContractModel):
    model: str
    confidence: Probability
    classes: list[ObjectClass]


class ConfigResponse(ContractModel):  # 7.3
    frame: FrameConfig
    direction_zones: dict[Direction, tuple[float, float]]
    distance_zones_m: dict[DistanceZone, float]
    speech: SpeechConfig
    detector: DetectorConfig


class SessionCreate(ContractModel):  # 7.4
    user_id: UUID
    device_info: dict[str, Any] = Field(default_factory=dict)


class SessionList(ContractModel):  # 7.5
    items: list[Session]
    count: int


class AskRequest(ContractModel):  # 7.9
    session_id: UUID
    question: Annotated[str, Field(max_length=500)]
    mode: AskMode = "question"
    image: str | None = None  # base64 JPEG without the data: prefix


class GroundedOn(ContractModel):
    frame_id: int | None
    detection_count: Annotated[int, Field(ge=0)]


class AskResponse(ContractModel):
    answer_id: UUID
    question: str
    answer: str
    spoken_text: str
    mode: AskMode
    source: AnswerSource
    grounded_on: GroundedOn
    latency_ms: Annotated[int, Field(ge=0)]


class OcrLine(ContractModel):  # 7.10
    text: str
    confidence: Probability
    bbox: BBox


class OcrResponse(ContractModel):
    text: str
    lines: list[OcrLine]
    spoken_text: str
    interpreted: bool
    source: OcrSource
    latency_ms: Annotated[int, Field(ge=0)]


class EmergencyRequest(ContractModel):  # 7.11
    session_id: UUID
    trigger: EmergencyTrigger
    location: GeoPoint | None = None
    note: Annotated[str, Field(max_length=200)] | None = None


class AlertList(ContractModel):  # 7.12
    items: list[Alert]
    count: int


class AlertUpdate(ContractModel):  # 7.13; "open" is never a valid target
    status: Literal["acknowledged", "resolved"]
    guardian_id: UUID


class GuardianMessageRequest(ContractModel):  # 7.14
    guardian_id: UUID
    text: Annotated[str, Field(min_length=1, max_length=200)]


class GuardianMessageResponse(ContractModel):
    message_id: UUID
    delivered: bool


class LinkedUser(ContractModel):  # 7.15
    user_id: UUID
    name: str
    relation: str | None
    active_session_id: UUID | None
    online: bool
    last_location: GeoPoint | None


class LinkedUserList(ContractModel):
    items: list[LinkedUser]


class NavigateRequest(ContractModel):  # 7.16 (P2)
    session_id: UUID
    origin: GeoPoint
    destination: Annotated[str, Field(min_length=1)] | GeoPoint
    profile: Literal["walking"] = "walking"


class NavigateStep(ContractModel):
    index: Annotated[int, Field(ge=0)]
    maneuver: str
    distance_m: NonNegative
    instruction: str
    spoken_text: str
    location: GeoPoint


class LineString(ContractModel):
    type: Literal["LineString"]
    coordinates: list[tuple[float, float]]  # GeoJSON order: [lng, lat]


class NavigateResponse(ContractModel):
    route_id: UUID
    destination_name: str
    total_distance_m: NonNegative
    duration_s: NonNegative
    steps: list[NavigateStep]
    geometry: LineString


class TtsRequest(ContractModel):  # 7.17 (P2)
    text: Annotated[str, Field(min_length=1)]
    lang: str = "en-IN"


class SttResponse(ContractModel):  # 7.18 (P2)
    text: str
    confidence: Probability


# --- Section 11: error model ---------------------------------------------------------------

ErrorCode = Literal[
    "VALIDATION_ERROR", "INVALID_FRAME", "USER_NOT_FOUND", "SESSION_NOT_FOUND", "ALERT_NOT_FOUND",
    "INVALID_STATUS_TRANSITION", "NO_RECENT_FRAME", "DESTINATION_NOT_FOUND", "MODEL_NOT_READY",
    "UNSUPPORTED_MESSAGE", "PIPELINE_ERROR", "INTERNAL",
    "NOT_FOUND", "METHOD_NOT_ALLOWED", "BAD_REQUEST",  # raised by the framework itself
]


class ErrorDetail(ContractModel):
    code: ErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(ContractModel):  # 11.1: the body of every non-2xx REST response
    error: ErrorDetail


# --- Section 5: user WebSocket messages ----------------------------------------------------

class Envelope(ContractModel):  # 5.1, both directions
    v: Literal[1]
    type: str
    ts: EpochMs
    payload: dict[str, Any] = Field(default_factory=dict)


class HelloPayload(ContractModel):
    user_id: UUID
    device_info: dict[str, Any] = Field(default_factory=dict)


class FramePayload(ContractModel):
    frame_id: Annotated[int, Field(ge=1)]
    image: str  # base64 JPEG without the data: prefix
    width: Annotated[int, Field(gt=0)]
    height: Annotated[int, Field(gt=0)]


class WelcomeConfig(ContractModel):
    target_fps: int
    max_width: int
    jpeg_quality: float


class WelcomePayload(ContractModel):
    session_id: UUID
    config: WelcomeConfig


class WsErrorPayload(ContractModel):
    code: ErrorCode
    message: str
    frame_id: int | None = None
