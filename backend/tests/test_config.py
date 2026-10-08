"""config.py must match API_CONTRACTS.md sections 2.1, 2.3, 2.4, 3 and 9.3."""
from typing import get_args

import pytest
from pydantic import ValidationError

from config import OBJECT_CLASSES, THRESHOLDS, WS_CLOSE
from schemas import Direction, ObjectClass, RiskLevel
from tests.conftest import make_settings


# --- Section 3.1: risk rules ---

def test_risk_priorities():
    assert THRESHOLDS.risk.priority == {"critical": 100, "high": 80, "medium": 50, "low": 20}


def test_risk_distance_thresholds():
    r = THRESHOLDS.risk
    assert r.very_close_m == 1.0          # R1
    assert r.vehicle_critical_m == 3.0    # R2
    assert r.vehicle_high_m == 5.0        # R3
    assert r.near_m == 2.0                # R4
    assert r.medium_m == 5.0              # R5, R6
    assert r.nearby_categories == ("vehicle", "animal")
    assert r.max_score_bonus == 0.1


def test_walking_corridor():
    assert THRESHOLDS.risk.corridor == ("slight_left", "center", "slight_right")


# --- Section 3.2: speech and warning policy ---

def test_speech_policy():
    s = THRESHOLDS.speech
    assert s.max_warnings_per_frame == 2
    assert s.cooldown_ms == {"critical": 1500, "high": 3000, "medium": 6000}
    assert s.interrupt_levels == ("critical",)
    assert s.silent_levels == ("low",)
    assert s.max_queue == 2
    assert s.stale_ms == 2000
    assert s.dedupe_ms == 3000
    assert THRESHOLDS.risk.path_clear_m == 3.0


# --- Section 3.3: hazard alerts ---

def test_hazard_alert_policy():
    assert THRESHOLDS.alerts.hazard_levels == ("critical", "high")
    assert THRESHOLDS.alerts.hazard_throttle_ms == 10_000


# --- Sections 2.3, 2.4, 5.2: zones and frames ---

def test_direction_zones_cover_frame_in_order():
    zones = THRESHOLDS.direction_zones
    assert list(zones) == list(get_args(Direction))
    assert zones == {
        "left": (0.0, 0.2), "slight_left": (0.2, 0.4), "center": (0.4, 0.6),
        "slight_right": (0.6, 0.8), "right": (0.8, 1.0),
    }
    bounds = list(zones.values())
    assert all(a[1] == b[0] for a, b in zip(bounds, bounds[1:]))  # no gaps or overlaps


def test_distance_zones():
    assert THRESHOLDS.distance_zones_m == {"very_close": 1.0, "near": 2.0, "medium": 5.0}


def test_frame_rules():
    f = THRESHOLDS.frame
    assert (f.target_fps, f.max_width, f.jpeg_quality, f.max_in_flight) == (5, 640, 0.65, 1)
    assert f.max_age_ms == 1000
    assert f.max_image_bytes == 5 * 1024 * 1024
    assert f.hello_timeout_ms == 5000


def test_live_rules():  # contract 5.2 and 6.2 (BE-08)
    live = THRESHOLDS.live
    assert live.relay_interval_ms == 500            # snapshot + frame_result: max 2 per second
    assert live.user_status_interval_ms == 2000
    assert live.silence_timeout_ms == 10_000        # no message from the phone -> offline
    assert (live.guardian_queue_size, live.guardian_max_drops) == (32, 3)
    assert THRESHOLDS.alerts.offline_alert_throttle_ms == 60_000


def test_websocket_close_codes():  # contract 5.4
    assert WS_CLOSE == {"normal": 1000, "session_not_found": 4001, "replaced": 4002, "protocol": 4003}


def test_detector_confidence():
    assert THRESHOLDS.detector_confidence == 0.4


def test_thresholds_are_read_only():
    with pytest.raises(ValidationError):
        THRESHOLDS.risk.near_m = 9.9


# --- Section 2.1: object classes ---

def test_object_class_table_matches_schema_enum():
    assert tuple(OBJECT_CLASSES) == get_args(ObjectClass)


@pytest.mark.parametrize("class_name, spoken, category", [
    ("traffic_light", "traffic light", "signal"),
    ("dining_table", "table", "obstacle"),
    ("potted_plant", "plant pot", "obstacle"),
    ("backpack", "bag", "obstacle"),
    ("motorcycle", "motorcycle", "vehicle"),
    ("dog", "dog", "animal"),
    ("bottle", "bottle", "other"),
])
def test_object_class_spoken_names(class_name, spoken, category):
    assert OBJECT_CLASSES[class_name] == (spoken, category)


def test_risk_level_keys_are_valid_enum_values():
    levels = set(get_args(RiskLevel))
    assert set(THRESHOLDS.risk.priority) == levels
    assert set(THRESHOLDS.speech.cooldown_ms) <= levels


# --- Section 9.3: environment settings ---

def test_defaults_without_env_file():
    s = make_settings()
    assert s.pipeline == "stub"
    assert s.yolo_model == "yolov8n.pt"
    assert s.camera_focal_px == 800.0
    assert s.cors_origins == ["http://localhost:5173"]
    assert s.supabase_enabled is False


def test_reads_environment_variables(monkeypatch):
    monkeypatch.setenv("PIPELINE", "real")
    monkeypatch.setenv("CAMERA_FOCAL_PX", "612.5")
    monkeypatch.setenv("FEATURE_ALERTS_DB", "true")
    s = make_settings()
    assert (s.pipeline, s.camera_focal_px, s.feature_alerts_db) == ("real", 612.5, True)


def test_blank_values_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("CAMERA_FOCAL_PX", "")
    assert make_settings().camera_focal_px == 800.0


def test_allowed_origins_is_comma_separated():
    s = make_settings(allowed_origins="http://localhost:5173, https://demo.trycloudflare.com ,")
    assert s.cors_origins == ["http://localhost:5173", "https://demo.trycloudflare.com"]


def test_unknown_pipeline_is_rejected():
    with pytest.raises(ValidationError):
        make_settings(pipeline="fast")


@pytest.mark.parametrize("raw", [
    "https://abc.supabase.co",
    "https://abc.supabase.co/",
    "https://abc.supabase.co/rest/v1",
    "https://abc.supabase.co/rest/v1/",
    "  https://abc.supabase.co/rest/v1/  ",
])
def test_supabase_url_is_normalised(raw):
    assert make_settings(supabase_url=raw).supabase_url == "https://abc.supabase.co"


def test_supabase_enabled_needs_flag_url_and_key():
    full = {"supabase_url": "https://abc.supabase.co", "supabase_service_role_key": "k"}
    assert make_settings(**full).supabase_enabled is False
    assert make_settings(**full, feature_alerts_db=True).supabase_enabled is True
    assert make_settings(feature_alerts_db=True).supabase_enabled is False
