"""GET /health (contract 7.2), GET /config (7.3), CORS and YOLO loading in the lifespan."""
import sys
import types

import pytest

from config import APP_VERSION


class FakeDetector:
    """Stands in for Coder 2's vision.detector.Detector (contract 8.2)."""
    instances: list["FakeDetector"] = []

    def __init__(self, model_path: str = "yolov8n.pt", conf: float = 0.4, classes=None, device: str = "cpu"):
        self.model_path, self.conf, self.classes = model_path, conf, classes
        self.calls: list[tuple[tuple[int, ...], bool]] = []
        FakeDetector.instances.append(self)

    def detect(self, frame_bgr, track: bool = True):
        self.calls.append((frame_bgr.shape, track))
        return []


class BrokenDetector:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("weights not found")


@pytest.fixture
def fake_vision(monkeypatch):
    def _install(detector_cls):
        FakeDetector.instances.clear()
        module = types.ModuleType("vision.detector")
        module.Detector = detector_cls
        monkeypatch.setitem(sys.modules, "vision.detector", module)
    return _install


# --- /health ---

def test_health_shape_in_stub_mode(make_client):
    r = make_client(pipeline="stub", tesseract_cmd="definitely-not-installed").get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"status", "version", "models", "uptime_s"}
    assert set(body["models"]) == {"yolo", "ocr", "gemini"}
    assert body == {
        "status": "degraded",  # contract 7.2: degraded whenever YOLO is not loaded
        "version": APP_VERSION,
        "models": {"yolo": "missing", "ocr": "missing", "gemini": "missing"},
        "uptime_s": body["uptime_s"],
    }
    assert isinstance(body["uptime_s"], int) and body["uptime_s"] >= 0


def test_health_reports_gemini_and_ocr(make_client):
    # sys.executable is a real executable on every machine, so it stands in for tesseract.
    r = make_client(gemini_api_key="test-key", tesseract_cmd=sys.executable).get("/api/v1/health")
    assert r.json()["models"] == {"yolo": "missing", "ocr": "available", "gemini": "configured"}


def test_health_ok_when_yolo_loads_and_is_warmed_up(make_client, fake_vision):
    fake_vision(FakeDetector)
    client = make_client(pipeline="real", yolo_model="custom.pt")
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok"
    assert body["models"]["yolo"] == "loaded"

    (detector,) = FakeDetector.instances  # loaded exactly once, at startup
    assert client.app.state.models.detector is detector
    assert detector.model_path == "custom.pt"
    assert detector.conf == 0.4
    assert detector.calls == [((480, 640, 3), False)]  # one warm-up frame, tracking off


def test_health_degraded_when_yolo_fails_to_load(make_client, fake_vision):
    fake_vision(BrokenDetector)
    r = make_client(pipeline="real").get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "degraded"
    assert r.json()["models"]["yolo"] == "missing"


def test_stub_mode_never_imports_the_detector(make_client, fake_vision):
    fake_vision(FakeDetector)
    make_client(pipeline="stub").get("/api/v1/health")
    assert FakeDetector.instances == []


# --- /config ---

EXPECTED_CONFIG = {
    "frame": {"target_fps": 5, "max_width": 640, "jpeg_quality": 0.65, "max_in_flight": 1},
    "direction_zones": {
        "left": [0.0, 0.2], "slight_left": [0.2, 0.4], "center": [0.4, 0.6],
        "slight_right": [0.6, 0.8], "right": [0.8, 1.0],
    },
    "distance_zones_m": {"very_close": 1.0, "near": 2.0, "medium": 5.0},
    "speech": {
        "cooldown_ms": {"critical": 1500, "high": 3000, "medium": 6000},
        "max_queue": 2, "stale_ms": 2000, "dedupe_ms": 3000,
    },
    "detector": {
        "model": "yolov8n.pt",
        "confidence": 0.4,
        "classes": [
            "person", "bicycle", "car", "motorcycle", "bus", "truck", "traffic_light", "stop_sign",
            "fire_hydrant", "bench", "chair", "dining_table", "potted_plant", "backpack", "suitcase",
            "dog", "cow", "bottle",
        ],
    },
}


def test_config_matches_contract(make_client):
    r = make_client().get("/api/v1/config")
    assert r.status_code == 200
    assert r.json() == EXPECTED_CONFIG


def test_config_reports_configured_yolo_model(make_client):
    r = make_client(yolo_model="yolov8s.pt").get("/api/v1/config")
    assert r.json()["detector"]["model"] == "yolov8s.pt"


# --- CORS and routing ---

def test_cors_allows_configured_origins_only(make_client):
    client = make_client(allowed_origins="http://localhost:5173,https://demo.trycloudflare.com")
    for origin in ("http://localhost:5173", "https://demo.trycloudflare.com"):
        r = client.get("/api/v1/health", headers={"Origin": origin})
        assert r.headers["access-control-allow-origin"] == origin
    r = client.get("/api/v1/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_routes_use_api_prefix(make_client):
    client = make_client()
    assert client.get("/health").status_code == 404
    assert client.get("/docs").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/api/v1/health", "/api/v1/config"} <= set(paths)


TUNNEL_REGEX = r"^https://[a-z0-9-]+\.trycloudflare\.com$"


@pytest.mark.parametrize("origin, allowed", [
    ("https://brave-otter-words.trycloudflare.com", True),
    ("http://localhost:5173", True),                       # ALLOWED_ORIGINS still works
    ("https://evil.example", False),
    ("http://brave-otter-words.trycloudflare.com", False),  # https only
    ("https://x.trycloudflare.com.evil.example", False),
])
def test_cors_origin_regex_for_tunnels(make_client, origin, allowed):
    client = make_client(allowed_origin_regex=TUNNEL_REGEX)
    r = client.get("/api/v1/health", headers={"Origin": origin})
    assert (r.headers.get("access-control-allow-origin") == origin) is allowed


def test_cors_regex_off_by_default(make_client):
    r = make_client().get("/api/v1/health", headers={"Origin": "https://brave-otter-words.trycloudflare.com"})
    assert "access-control-allow-origin" not in r.headers
