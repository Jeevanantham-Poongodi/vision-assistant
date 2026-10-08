"""Assistance requests when vision is unsure (BE-14)."""
import base64
import copy
import sys
import time
import types
from contextlib import contextmanager

import cv2
import numpy as np
import pytest

from db.repo import DEMO_GUARDIAN_ID, DEMO_USER_ID
from live import assistance
from live import hub as hub_module
from live import user_ws
from live.hub import SessionState
from schemas import Alert
from vision.pipelines import STUB_RESULT

USER, GUARDIAN = str(DEMO_USER_ID), str(DEMO_GUARDIAN_ID)
SPOKEN = "I need assistance to determine the safest direction. I have asked your guardian."


# --- The 3 s rule (unit) ---

class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(assistance.time, "monotonic", c)
    return c


def low(flag: bool) -> dict:
    return {"low_confidence_scene": flag}


def test_needs_3_seconds_of_low_confidence(clock):
    state = SessionState()
    assert assistance.due(state, low(True)) is False        # starts the timer
    clock.t += 2.9
    assert assistance.due(state, low(True)) is False
    clock.t += 0.2
    assert assistance.due(state, low(True)) is True         # 3.1 s
    clock.t += 5
    assert assistance.due(state, low(True)) is False        # once per period


def test_a_good_frame_resets_the_timer(clock):
    state = SessionState()
    assistance.due(state, low(True))
    clock.t += 2.5
    assert assistance.due(state, low(False)) is False
    clock.t += 1
    assert assistance.due(state, low(True)) is False        # timer restarted
    clock.t += 3.1
    assert assistance.due(state, low(True)) is True


def test_at_most_one_per_minute(clock):
    state = SessionState()
    assistance.due(state, low(True))
    clock.t += 3.1
    assert assistance.due(state, low(True)) is True
    assistance.due(state, low(False))                        # new period...
    assistance.due(state, low(True))
    clock.t += 3.1
    assert assistance.due(state, low(True)) is False        # ...but within 60 s
    assistance.due(state, low(False))
    clock.t += 60
    assistance.due(state, low(True))
    clock.t += 3.1
    assert assistance.due(state, low(True)) is True


def test_missing_flag_counts_as_confident(clock):
    state = SessionState()
    assistance.due(state, low(True))
    clock.t += 5
    assert assistance.due(state, {}) is False and state.low_conf_since is None


# --- End to end with a fake pipeline ---

class FakeDetector:
    def __init__(self, *args, **kwargs): ...
    def detect(self, frame_bgr, track=True): return []


class LowConfidencePipeline:
    low = True

    def __init__(self, focal_px, detector=None): ...

    def process(self, frame_bgr, frame_id, ts_captured_ms):
        r = copy.deepcopy(STUB_RESULT)
        r.update(frame_id=frame_id, ts_captured=ts_captured_ms, ts_processed=ts_captured_ms, latency_ms=0,
                 warnings=[], low_confidence_scene=LowConfidencePipeline.low)
        return r


@pytest.fixture
def client(make_client, monkeypatch):
    for name, attr, cls in (("vision.detector", "Detector", FakeDetector),
                            ("vision.pipeline", "VisionPipeline", LowConfidencePipeline)):
        module = types.ModuleType(name)
        setattr(module, attr, cls)
        monkeypatch.setitem(sys.modules, name, module)
    LowConfidencePipeline.low = True
    monkeypatch.setattr(assistance, "ASSIST_AFTER_S", 0.2)
    monkeypatch.setattr(user_ws, "HELLO_TIMEOUT_S", 0.5)
    monkeypatch.setattr(hub_module, "STATUS_INTERVAL_S", 0.05)
    return make_client(pipeline="real", feature_guardian=True)


def env(type_, payload=None):
    return {"v": 1, "type": type_, "ts": int(time.time() * 1000), "payload": payload or {}}


IMAGE = base64.b64encode(cv2.imencode(".jpg", np.full((480, 640, 3), 20, np.uint8))[1].tobytes()).decode()


@contextmanager
def sockets(client):
    sid = client.post("/api/v1/sessions", json={"user_id": USER}).json()["session_id"]
    with client.websocket_connect(f"/ws/guardian/{sid}?guardian_id={GUARDIAN}") as g, \
            client.websocket_connect(f"/ws/user/{sid}") as u:
        g.send_json(env("hello", {"guardian_id": GUARDIAN}))
        u.send_json(env("hello", {"user_id": USER}))
        assert u.receive_json()["type"] == "welcome"
        yield sid, g, u


def stream(u, seconds: float) -> list[dict]:
    """Sends frames for a while; returns every non-frame_result message the phone got."""
    other, end, i = [], time.monotonic() + seconds, 0
    while time.monotonic() < end:
        i += 1
        u.send_json(env("frame", {"frame_id": i, "image": IMAGE, "width": 640, "height": 480}))
        while (msg := u.receive_json())["type"] != "frame_result":
            other.append(msg)
        time.sleep(0.03)
    u.send_json(env("ping"))
    while (msg := u.receive_json())["type"] != "pong":
        other.append(msg)
    return other


def read_until(ws, pred, limit=400):
    for _ in range(limit):
        if pred(msg := ws.receive_json()):
            return msg
    raise AssertionError("not received")


def test_low_confidence_raises_one_assistance_request(client):
    with sockets(client) as (sid, g, u):
        to_phone = stream(u, 0.6)
        alert = read_until(g, lambda m: m["type"] == "alert" and m["payload"]["type"] == "assistance_request")["payload"]
        more = stream(u, 0.4)                                        # same period: nothing new
    (notice,) = [m for m in to_phone if m["type"] == "assistance_requested"]
    assert notice["payload"] == {"alert_id": alert["alert_id"], "spoken_text": SPOKEN}
    Alert.model_validate(alert)
    assert (alert["risk_level"], alert["status"], alert["title"]) == ("high", "open", "Assistance requested")
    assert alert["snapshot_b64"]
    assert not [m for m in more if m["type"] == "assistance_requested"]
    alerts = client.get("/api/v1/alerts", params={"type": "assistance_request"}).json()["items"]
    assert len(alerts) == 1


def test_confident_frames_raise_nothing(client):
    LowConfidencePipeline.low = False
    with sockets(client) as (sid, g, u):
        to_phone = stream(u, 0.5)
    assert not [m for m in to_phone if m["type"] == "assistance_requested"]
    assert client.get("/api/v1/alerts", params={"type": "assistance_request"}).json()["items"] == []


def test_a_short_dip_raises_nothing(client, monkeypatch):
    monkeypatch.setattr(assistance, "ASSIST_AFTER_S", 5)
    with sockets(client) as (sid, g, u):
        assert not [m for m in stream(u, 0.4) if m["type"] == "assistance_requested"]
