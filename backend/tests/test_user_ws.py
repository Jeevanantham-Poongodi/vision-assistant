"""User WebSocket, contract section 5 (BE-04, stub pipeline)."""
import base64
import json
import sys
import types
from contextlib import contextmanager

import cv2
import numpy as np
import pytest
from fastapi import WebSocketDisconnect

from db.repo import DEMO_USER_ID
from live import user_ws
from schemas import FrameResult
from vision import pipelines

USER = str(DEMO_USER_ID)
UNKNOWN = "99999999-9999-4999-8999-999999999999"
TS = 1759900530120


def env(type_: str, payload: dict | None = None, ts: int = TS) -> dict:
    return {"v": 1, "type": type_, "ts": ts, "payload": payload or {}}


def tiny_jpeg() -> str:
    ok, buf = cv2.imencode(".jpg", np.zeros((8, 8, 3), dtype=np.uint8))
    assert ok
    return base64.b64encode(buf.tobytes()).decode()


def frame(frame_id: int = 1, image: str | None = None, ts: int = TS) -> dict:
    return env("frame", {"frame_id": frame_id, "image": image or tiny_jpeg(), "width": 8, "height": 8}, ts)


@pytest.fixture(autouse=True)
def fast_hello_timeout(monkeypatch):
    monkeypatch.setattr(user_ws, "HELLO_TIMEOUT_S", 0.2)


@pytest.fixture
def client(make_client):
    return make_client()


def new_session(client) -> str:
    return client.post("/api/v1/sessions", json={"user_id": USER}).json()["session_id"]


@contextmanager
def connected(client, sid: str):
    """Opens the socket and sends hello; always exits it, or TestClient waits forever at teardown."""
    with client.websocket_connect(f"/ws/user/{sid}") as ws:
        ws.send_json(env("hello", {"user_id": USER, "device_info": {"platform": "android"}}))
        assert ws.receive_json()["type"] == "welcome"
        yield ws


def close_code(ws) -> int:
    with pytest.raises(WebSocketDisconnect) as exc:
        ws.receive_json()
    return exc.value.code


def error_of(msg: dict) -> dict:
    assert msg["type"] == "error"
    return msg["payload"]


# --- Connecting (5.4) ---

def test_unknown_session_closes_4001(client):
    with client.websocket_connect(f"/ws/user/{UNKNOWN}") as ws:
        assert close_code(ws) == 4001


def test_ended_session_closes_4001(client):
    sid = new_session(client)
    client.post(f"/api/v1/sessions/{sid}/end")
    with client.websocket_connect(f"/ws/user/{sid}") as ws:
        assert close_code(ws) == 4001


def test_no_hello_in_time_closes_4003(client):
    with client.websocket_connect(f"/ws/user/{new_session(client)}") as ws:
        assert close_code(ws) == 4003


@pytest.mark.parametrize("first", [
    env("ping"),
    env("hello", {"user_id": UNKNOWN}),           # not this session's user
    env("hello", {"user_id": "not-a-uuid"}),
    {"type": "hello", "payload": {"user_id": USER}},  # no v / ts
])
def test_bad_first_message_closes_4003(client, first):
    with client.websocket_connect(f"/ws/user/{new_session(client)}") as ws:
        ws.send_json(first)
        assert close_code(ws) == 4003


def test_welcome(client):
    sid = new_session(client)
    with client.websocket_connect(f"/ws/user/{sid}") as ws:
        ws.send_json(env("hello", {"user_id": USER}))
        msg = ws.receive_json()
    assert msg["v"] == 1 and msg["type"] == "welcome" and isinstance(msg["ts"], int)
    assert msg["payload"] == {
        "session_id": sid,
        "config": {"target_fps": 5, "max_width": 640, "jpeg_quality": 0.65},
    }


def test_user_online_while_connected(client):
    sid = new_session(client)
    with connected(client, sid):
        assert client.get(f"/api/v1/sessions/{sid}").json()["user_online"] is True
    assert client.get(f"/api/v1/sessions/{sid}").json()["user_online"] is False


# --- Frames (stub pipeline) ---

def test_frame_returns_stub_result(client):
    with connected(client, new_session(client)) as ws:
        ws.send_json(frame(frame_id=7))
        msg = ws.receive_json()
        assert msg["type"] == "frame_result"
        result = msg["payload"]
        FrameResult.model_validate(result)
        assert result["frame_id"] == 7
        assert result["ts_captured"] == TS
        assert result["latency_ms"] == result["ts_processed"] - result["ts_captured"]
        assert result["detections"] == pipelines.STUB_RESULT["detections"]
        assert result["warnings"] == pipelines.STUB_RESULT["warnings"]


def test_stub_fixture_is_contract_13_1():
    fixture = json.loads(pipelines.FIXTURE.read_text(encoding="utf-8"))
    assert fixture["type"] == "frame_result"
    assert fixture["payload"]["frame_id"] == 1042
    assert [w["rule"] for w in fixture["payload"]["warnings"]] == ["R3", "R6"]


def test_frames_in_a_row(client):
    with connected(client, new_session(client)) as ws:
        for i in (1, 2, 3):
            ws.send_json(frame(frame_id=i))
            assert ws.receive_json()["payload"]["frame_id"] == i


def test_ping_pong(client):
    with connected(client, new_session(client)) as ws:
        ws.send_json(env("ping"))
        msg = ws.receive_json()
        assert (msg["type"], msg["payload"]) == ("pong", {})


# --- Errors keep the socket open ---

def assert_still_open(ws):
    ws.send_json(env("ping"))
    assert ws.receive_json()["type"] == "pong"


@pytest.mark.parametrize("image, reason", [
    ("@@not base64@@", "base64"),
    (base64.b64encode(b"definitely not a jpeg").decode(), "decoded"),
    (base64.b64encode(b"\xff" * (5 * 1024 * 1024 + 1)).decode(), "5 MB"),
], ids=["bad-base64", "not-a-jpeg", "over-5mb"])
def test_bad_image_is_invalid_frame(client, image, reason):
    with connected(client, new_session(client)) as ws:
        ws.send_json(frame(frame_id=42, image=image))
        err = error_of(ws.receive_json())
        assert (err["code"], err["frame_id"]) == ("INVALID_FRAME", 42)
        assert reason in err["message"]
        assert_still_open(ws)


def test_frame_without_image_is_invalid_frame(client):
    with connected(client, new_session(client)) as ws:
        ws.send_json(env("frame", {"frame_id": 9, "width": 8, "height": 8}))
        err = error_of(ws.receive_json())
        assert (err["code"], err["frame_id"]) == ("INVALID_FRAME", 9)
        assert_still_open(ws)


@pytest.mark.parametrize("send", [
    lambda ws: ws.send_json(env("dance")),
    lambda ws: ws.send_text("{not json"),
    lambda ws: ws.send_json({"type": "ping"}),  # missing v and ts
    lambda ws: ws.send_bytes(b"\x00\x01"),
])
def test_unsupported_messages(client, send):
    with connected(client, new_session(client)) as ws:
        send(ws)
        err = error_of(ws.receive_json())
        assert err["code"] == "UNSUPPORTED_MESSAGE"
        assert err["frame_id"] is None
        assert_still_open(ws)


@pytest.mark.parametrize("type_", ["emergency", "hello"])  # location and status are handled since BE-08
def test_later_message_types_are_accepted_silently(client, type_):
    with connected(client, new_session(client)) as ws:
        ws.send_json(env(type_, {"user_id": USER}))
        assert_still_open(ws)  # the next reply is the pong, not an error


# --- Replacement and ending (5.4, BE-03) ---

def test_new_connection_replaces_old_with_4002(client):
    sid = new_session(client)
    with connected(client, sid) as old, connected(client, sid) as new:
        assert close_code(old) == 4002
        assert_still_open(new)
        assert client.get(f"/api/v1/sessions/{sid}").json()["user_online"] is True


def test_ending_session_closes_socket_1000(client):
    sid = new_session(client)
    with connected(client, sid) as ws:
        client.post(f"/api/v1/sessions/{sid}/end")
        assert close_code(ws) == 1000


# --- Real pipeline without Coder 2's VisionPipeline ---

def test_real_pipeline_unavailable_reports_pipeline_error(make_client, monkeypatch):
    class FakeDetector:
        def __init__(self, *args, **kwargs): ...
        def detect(self, frame_bgr, track=True): return []

    module = types.ModuleType("vision.detector")
    module.Detector = FakeDetector
    monkeypatch.setitem(sys.modules, "vision.detector", module)
    client = make_client(pipeline="real")
    with connected(client, new_session(client)) as ws:
        ws.send_json(frame(frame_id=3))
        err = error_of(ws.receive_json())
        assert (err["code"], err["frame_id"]) == ("PIPELINE_ERROR", 3)
