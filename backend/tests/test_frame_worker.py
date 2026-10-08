"""Frame loop (BE-05): pipeline per session, latest frame wins, stale drop, cache, debug frames, stats."""
import base64
import copy
import logging
import sys
import threading
import time
import types
from contextlib import contextmanager
from uuid import UUID

import cv2
import numpy as np
import pytest

from db.repo import DEMO_USER_ID
from live import frame_worker, user_ws
from live.stats import FrameStats, percentile
from tools.replay_ws import encode_jpeg, resize_for_phone
from vision.pipelines import STUB_RESULT

USER = str(DEMO_USER_ID)


def now_ms() -> int:
    return int(time.time() * 1000)


def env(type_: str, payload: dict | None = None, ts: int | None = None) -> dict:
    return {"v": 1, "type": type_, "ts": now_ms() if ts is None else ts, "payload": payload or {}}


def jpeg_b64(h: int = 12, w: int = 16) -> str:
    return base64.b64encode(cv2.imencode(".jpg", np.zeros((h, w, 3), np.uint8))[1].tobytes()).decode()


def frame(frame_id: int, ts: int | None = None, image: str | None = None) -> dict:
    return env("frame", {"frame_id": frame_id, "image": image or jpeg_b64(), "width": 16, "height": 12}, ts)


def result_for(frame_id: int, ts: int) -> dict:
    r = copy.deepcopy(STUB_RESULT)
    r.update(frame_id=frame_id, ts_captured=ts, ts_processed=ts, latency_ms=0)
    return r


# --- Fake Coder 2 modules (contract 8.2) ---

class FakeDetector:
    instances: list["FakeDetector"] = []

    def __init__(self, model_path="yolov8n.pt", conf=0.4, classes=None, device="cpu"):
        self.model_path, self.conf = model_path, conf
        FakeDetector.instances.append(self)

    def detect(self, frame_bgr, track=True):
        return []


class FakePipeline:
    instances: list["FakePipeline"] = []
    gate: threading.Event | None = None    # when set, process() waits on it
    started = threading.Event()
    behaviour = "ok"                       # "ok" | "raise" | "invalid"

    def __init__(self, focal_px: float, detector=None):
        self.focal_px, self.detector = focal_px, detector
        self.calls: list[tuple[tuple[int, ...], int, int]] = []
        FakePipeline.instances.append(self)

    def process(self, frame_bgr, frame_id, ts_captured_ms):
        self.calls.append((frame_bgr.shape, frame_id, ts_captured_ms))
        FakePipeline.started.set()
        if FakePipeline.gate is not None:
            FakePipeline.gate.wait(5)
        if FakePipeline.behaviour == "raise":
            raise RuntimeError("model exploded")
        if FakePipeline.behaviour == "invalid":
            return {"frame_id": frame_id}
        return result_for(frame_id, ts_captured_ms)


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    FakeDetector.instances.clear()
    FakePipeline.instances.clear()
    FakePipeline.gate, FakePipeline.behaviour = None, "ok"
    FakePipeline.started = threading.Event()
    det = types.ModuleType("vision.detector")
    det.Detector = FakeDetector
    pipe = types.ModuleType("vision.pipeline")
    pipe.VisionPipeline = FakePipeline
    monkeypatch.setitem(sys.modules, "vision.detector", det)
    monkeypatch.setitem(sys.modules, "vision.pipeline", pipe)
    monkeypatch.setattr(user_ws, "HELLO_TIMEOUT_S", 0.5)


@pytest.fixture
def client(make_client):
    return make_client(pipeline="real", camera_focal_px=612.5, yolo_model="custom.pt")


def new_session(client) -> str:
    return client.post("/api/v1/sessions", json={"user_id": USER}).json()["session_id"]


@contextmanager
def connected(client, sid: str, hello_ts: int | None = None):
    with client.websocket_connect(f"/ws/user/{sid}") as ws:
        ws.send_json(env("hello", {"user_id": USER}, hello_ts))
        assert ws.receive_json()["type"] == "welcome"
        yield ws


def wait_until(predicate, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition not met in time"
        time.sleep(0.01)


def assert_only_pong_left(ws):
    ws.send_json(env("ping"))
    assert ws.receive_json()["type"] == "pong"


# --- Pipeline per session ---

def test_pipeline_created_on_hello_with_settings(client):
    with connected(client, new_session(client)):
        wait_until(lambda: len(FakePipeline.instances) == 1)  # before any frame
    (pipeline,) = FakePipeline.instances
    assert pipeline.focal_px == 612.5
    assert isinstance(pipeline.detector, FakeDetector)
    assert (pipeline.detector.model_path, pipeline.detector.conf) == ("custom.pt", 0.4)


def test_reconnect_reuses_pipeline_and_end_drops_it(client):
    sid = new_session(client)
    with connected(client, sid) as ws:
        ws.send_json(frame(1))
        assert ws.receive_json()["type"] == "frame_result"
    with connected(client, sid) as ws:
        ws.send_json(frame(2))
        assert ws.receive_json()["type"] == "frame_result"
    assert len(FakePipeline.instances) == 1
    client.post(f"/api/v1/sessions/{sid}/end")
    assert client.app.state.hub.state(UUID(sid)).pipeline is None


def test_frame_goes_through_pipeline(client):
    with connected(client, new_session(client)) as ws:
        ts = now_ms()
        ws.send_json(frame(7, ts=ts, image=jpeg_b64(h=24, w=32)))
        msg = ws.receive_json()
    assert msg["type"] == "frame_result"
    assert msg["payload"]["frame_id"] == 7
    assert FakePipeline.instances[0].calls == [((24, 32, 3), 7, ts)]


# --- Latest frame wins and stale frames ---

def test_latest_frame_wins(client):
    FakePipeline.gate = threading.Event()
    with connected(client, new_session(client)) as ws:
        ws.send_json(frame(1))
        assert FakePipeline.started.wait(3)  # frame 1 is in the pipeline
        for i in (2, 3, 4):
            ws.send_json(frame(i))
        ws.send_json(env("ping"))           # handled by the receive loop while frame 1 runs
        assert ws.receive_json()["type"] == "pong"
        FakePipeline.gate.set()
        assert ws.receive_json()["payload"]["frame_id"] == 1
        assert ws.receive_json()["payload"]["frame_id"] == 4
        assert_only_pong_left(ws)
    assert [c[1] for c in FakePipeline.instances[0].calls] == [1, 4]


def test_stale_frame_is_dropped(client):
    with connected(client, new_session(client)) as ws:
        ws.send_json(frame(1, ts=now_ms() - 2000))
        assert_only_pong_left(ws)
        ws.send_json(frame(2))
        assert ws.receive_json()["payload"]["frame_id"] == 2


def test_clock_skew_is_tolerated(client):
    hour = 3_600_000
    with connected(client, new_session(client), hello_ts=now_ms() - hour) as ws:
        ws.send_json(frame(1, ts=now_ms() - hour))  # phone clock 1 h behind, frame is fresh
        msg = ws.receive_json()
    assert (msg["type"], msg["payload"]["frame_id"]) == ("frame_result", 1)


# --- Errors keep the socket open ---

@pytest.mark.parametrize("behaviour", ["raise", "invalid"])
def test_pipeline_failure_is_pipeline_error(client, behaviour, caplog):
    FakePipeline.behaviour = behaviour
    with connected(client, new_session(client)) as ws:
        ws.send_json(frame(5))
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert (msg["payload"]["code"], msg["payload"]["frame_id"]) == ("PIPELINE_ERROR", 5)
        assert_only_pong_left(ws)
    assert any(r.exc_info for r in caplog.records)  # traceback is logged


def test_pipeline_creation_failure(client, monkeypatch):
    class Broken:
        def __init__(self, *a, **k):
            raise RuntimeError("weights missing")

    sys.modules["vision.pipeline"].VisionPipeline = Broken
    with connected(client, new_session(client)) as ws:
        for i in (1, 2):
            ws.send_json(frame(i))
            payload = ws.receive_json()["payload"]
            assert (payload["code"], payload["frame_id"]) == ("PIPELINE_ERROR", i)
        assert_only_pong_left(ws)


def test_undecodable_jpeg_is_invalid_frame(client):
    with connected(client, new_session(client)) as ws:
        ws.send_json(frame(3, image=base64.b64encode(b"not a jpeg").decode()))
        payload = ws.receive_json()["payload"]
        assert (payload["code"], payload["frame_id"]) == ("INVALID_FRAME", 3)
        assert_only_pong_left(ws)


# --- Cache for /ask and /ocr ---

def test_latest_frame_is_cached(client):
    sid = new_session(client)
    image = jpeg_b64()
    with connected(client, sid) as ws:
        ws.send_json(frame(9, image=image))
        ws.receive_json()
        state = client.app.state.hub.state(UUID(sid))
        assert state.latest_jpeg == base64.b64decode(image)
        assert state.latest_result["frame_id"] == 9
        assert abs(state.latest_at_ms - now_ms()) < 5000


# --- Debug frames ---

def test_every_tenth_frame_is_saved(make_client, monkeypatch, tmp_path):
    monkeypatch.setattr(frame_worker, "DEBUG_DIR", tmp_path)
    client = make_client(debug_save_frames=True)  # stub pipeline
    sid = new_session(client)
    with connected(client, sid) as ws:
        for i in range(1, 21):
            ws.send_json(frame(i))
            ws.receive_json()
    folder = tmp_path / sid
    wait_until(lambda: folder.exists() and len(list(folder.iterdir())) == 2)
    assert sorted(p.name for p in folder.iterdir()) == ["000010.jpg", "000020.jpg"]


def test_debug_frames_off_by_default(make_client, monkeypatch, tmp_path):
    monkeypatch.setattr(frame_worker, "DEBUG_DIR", tmp_path)
    client = make_client()
    with connected(client, new_session(client)) as ws:
        for i in range(1, 11):
            ws.send_json(frame(i))
            ws.receive_json()
    assert list(tmp_path.iterdir()) == []


# --- Clean shutdown ---

def test_disconnect_while_processing_is_clean(client, caplog):
    FakePipeline.gate = threading.Event()
    with caplog.at_level(logging.ERROR):
        with connected(client, new_session(client)) as ws:
            ws.send_json(frame(1))
            assert FakePipeline.started.wait(3)
        FakePipeline.gate.set()
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_end_session_while_processing_closes_1000(client):
    from fastapi import WebSocketDisconnect

    FakePipeline.gate = threading.Event()
    sid = new_session(client)
    with connected(client, sid) as ws:
        ws.send_json(frame(1))
        assert FakePipeline.started.wait(3)
        client.post(f"/api/v1/sessions/{sid}/end")
        FakePipeline.gate.set()
        with pytest.raises(WebSocketDisconnect) as exc:
            while True:  # the frame_result may or may not arrive before the close
                ws.receive_json()
        assert exc.value.code == 1000


# --- Stats ---

def test_percentile():
    assert percentile([], 95) == 0.0
    assert percentile([10.0], 95) == 10.0
    values = [float(v) for v in range(1, 101)]
    assert (percentile(values, 50), percentile(values, 95), percentile(values, 100)) == (50.0, 95.0, 100.0)


def test_frame_stats_reports_every_window(caplog):
    t = [0.0]
    stats = FrameStats("session abc", window_s=5.0, clock=lambda: t[0])
    with caplog.at_level(logging.INFO, logger="vision_assistant"):
        for i in range(10):
            t[0] = i * 0.2
            stats.record(i, decode_ms=2, pipeline_ms=100 + i, total_ms=120 + i)
        stats.drop("stale")
        stats.drop("superseded")
        stats.drop("superseded")
        assert not caplog.records  # still inside the 5 s window
        t[0] = 5.0
        stats.record(10, decode_ms=2, pipeline_ms=110, total_ms=130)
    (line,) = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert line.startswith("session abc: 2.2 fps, total p50 125 ms p95 130 ms")
    assert line.endswith("dropped 3 (stale 1, superseded 2)")
    assert stats.total_ms == [] and stats.stale == 0  # new window


# --- Replay tool helpers ---

def test_resize_for_phone():
    assert resize_for_phone(np.zeros((1080, 1920, 3), np.uint8)).shape == (360, 640, 3)
    small = np.zeros((240, 320, 3), np.uint8)
    assert resize_for_phone(small) is small


def test_encode_jpeg_round_trips():
    data = base64.b64decode(encode_jpeg(np.zeros((48, 64, 3), np.uint8)))
    assert cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR).shape == (48, 64, 3)
