"""POST /api/v1/detect, contract 7.8 (BE-06)."""
import copy
import sys
import types
import time
from uuid import UUID

import cv2
import numpy as np
import pytest

from db.repo import DEMO_USER_ID
from schemas import ErrorResponse, FrameResult
from vision.pipelines import STUB_RESULT

URL = "/api/v1/detect"
USER = str(DEMO_USER_ID)
UNKNOWN = "99999999-9999-4999-8999-999999999999"


def image_bytes(ext: str = ".jpg", h: int = 24, w: int = 32) -> bytes:
    return cv2.imencode(ext, np.zeros((h, w, 3), np.uint8))[1].tobytes()


def upload(client, data: bytes | None = None, session_id: str | None = None, name: str = "frame.jpg"):
    files = {"image": (name, image_bytes() if data is None else data, "image/jpeg")}
    form = {"session_id": session_id} if session_id else {}
    return client.post(URL, files=files, data=form)


def new_session(client) -> str:
    return client.post("/api/v1/sessions", json={"user_id": USER}).json()["session_id"]


def assert_error(r, status: int, code: str) -> None:
    assert r.status_code == status, r.text
    ErrorResponse.model_validate(r.json())
    assert r.json()["error"]["code"] == code


# --- Fake Coder 2 modules (contract 8.2) ---

class FakeDetector:
    instances: list["FakeDetector"] = []
    fail = False

    def __init__(self, model_path="yolov8n.pt", conf=0.4, classes=None, device="cpu"):
        if FakeDetector.fail:
            raise RuntimeError("weights missing")
        FakeDetector.instances.append(self)

    def detect(self, frame_bgr, track=True):
        return []


class FakePipeline:
    instances: list["FakePipeline"] = []
    behaviour = "ok"  # "ok" | "raise" | "invalid"

    def __init__(self, focal_px: float, detector=None):
        self.detector = detector
        self.calls: list[tuple[tuple[int, ...], int]] = []
        FakePipeline.instances.append(self)

    def process(self, frame_bgr, frame_id, ts_captured_ms):
        self.calls.append((frame_bgr.shape, frame_id))
        if FakePipeline.behaviour == "raise":
            raise RuntimeError("model exploded: secret-detail")
        if FakePipeline.behaviour == "invalid":
            return {"frame_id": frame_id}
        r = copy.deepcopy(STUB_RESULT)
        r.update(frame_id=frame_id, ts_captured=ts_captured_ms, ts_processed=ts_captured_ms, latency_ms=0)
        return r


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    FakeDetector.instances.clear()
    FakePipeline.instances.clear()
    FakeDetector.fail, FakePipeline.behaviour = False, "ok"
    det = types.ModuleType("vision.detector")
    det.Detector = FakeDetector
    pipe = types.ModuleType("vision.pipeline")
    pipe.VisionPipeline = FakePipeline
    monkeypatch.setitem(sys.modules, "vision.detector", det)
    monkeypatch.setitem(sys.modules, "vision.pipeline", pipe)


@pytest.fixture
def stub(make_client):
    return make_client()


@pytest.fixture
def real(make_client):
    return make_client(pipeline="real")


# --- Stub mode ---

@pytest.mark.parametrize("ext", [".jpg", ".png"])
def test_stub_returns_frame_result(stub, ext):
    r = upload(stub, image_bytes(ext), name=f"frame{ext}")
    assert r.status_code == 200, r.text
    body = r.json()
    FrameResult.model_validate(body)
    assert body["frame_id"] == 0
    assert body["warnings"] == STUB_RESULT["warnings"]
    assert abs(body["ts_captured"] - int(time.time() * 1000)) < 5000


@pytest.mark.parametrize("data", [b"this is a text file", b"", b"\xff" * (5 * 1024 * 1024 + 1)],
                         ids=["not-an-image", "empty", "over-5mb"])
def test_bad_image_is_invalid_frame(stub, data):
    assert_error(upload(stub, data), 400, "INVALID_FRAME")


def test_missing_image_is_validation_error(stub):
    assert_error(stub.post(URL, data={"session_id": UNKNOWN}), 422, "VALIDATION_ERROR")


def test_malformed_session_id_is_validation_error(stub):
    assert_error(upload(stub, session_id="arun"), 422, "VALIDATION_ERROR")


def test_unknown_session_is_not_found(stub):
    assert_error(upload(stub, session_id=UNKNOWN), 404, "SESSION_NOT_FOUND")


def test_ended_session_is_not_found(stub):
    sid = new_session(stub)
    stub.post(f"/api/v1/sessions/{sid}/end")
    assert_error(upload(stub, session_id=sid), 404, "SESSION_NOT_FOUND")


# --- Real mode (fake Coder 2 modules) ---

def test_without_session_uses_fresh_pipeline_and_shared_detector(real):
    shared = real.app.state.models.detector
    assert real.app.state.models.yolo == "loaded"
    for _ in range(2):
        r = upload(real, image_bytes(h=48, w=64))
        assert r.status_code == 200 and r.json()["frame_id"] == 0
    assert len(FakePipeline.instances) == 2                       # fresh each call: no history
    assert all(p.detector is shared for p in FakePipeline.instances)
    assert FakePipeline.instances[0].calls == [((48, 64, 3), 0)]


def test_with_session_uses_session_pipeline_and_updates_cache(real):
    sid = new_session(real)
    data = image_bytes()
    assert upload(real, data, session_id=sid).json()["frame_id"] == 1
    assert upload(real, data, session_id=sid).json()["frame_id"] == 2
    state = real.app.state.hub.state(UUID(sid))
    (pipeline,) = FakePipeline.instances                           # created once, kept on the session
    assert state.pipeline is pipeline
    assert pipeline.detector is not real.app.state.models.detector  # its own Detector for tracking
    assert state.latest_jpeg == data and state.latest_result["frame_id"] == 2


def test_session_pipeline_is_shared_with_websocket(real, monkeypatch):
    from live import user_ws

    monkeypatch.setattr(user_ws, "HELLO_TIMEOUT_S", 0.5)
    sid = new_session(real)
    with real.websocket_connect(f"/ws/user/{sid}") as ws:
        ws.send_json({"v": 1, "type": "hello", "ts": int(time.time() * 1000), "payload": {"user_id": USER}})
        assert ws.receive_json()["type"] == "welcome"
        assert upload(real, session_id=sid).status_code == 200
    assert len(FakePipeline.instances) == 1


def test_yolo_not_loaded_is_model_not_ready(make_client):
    FakeDetector.fail = True
    client = make_client(pipeline="real")
    assert client.app.state.models.yolo == "missing"
    assert_error(upload(client), 503, "MODEL_NOT_READY")


def test_session_pipeline_unavailable_is_model_not_ready(real):
    sid = new_session(real)
    FakeDetector.fail = True  # the per-session Detector cannot load
    assert_error(upload(real, session_id=sid), 503, "MODEL_NOT_READY")


@pytest.mark.parametrize("behaviour", ["raise", "invalid"])
def test_pipeline_failure_is_pipeline_error(real, behaviour):
    FakePipeline.behaviour = behaviour
    r = upload(real)
    assert_error(r, 500, "PIPELINE_ERROR")
    assert "secret-detail" not in r.text


# --- Docs ---

def test_openapi_documents_multipart_upload(stub):
    op = stub.get("/openapi.json").json()["paths"]["/api/v1/detect"]["post"]
    content = op["requestBody"]["content"]
    assert list(content) == ["multipart/form-data"]
    schema_ref = content["multipart/form-data"]["schema"]["$ref"].rsplit("/", 1)[-1]
    props = stub.get("/openapi.json").json()["components"]["schemas"][schema_ref]["properties"]
    assert set(props) == {"image", "session_id"}
