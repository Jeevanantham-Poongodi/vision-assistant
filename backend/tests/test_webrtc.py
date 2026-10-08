"""WebRTC signalling relay (BE-15)."""
import time
from contextlib import contextmanager

import pytest

from db.repo import DEMO_GUARDIAN_ID, DEMO_USER_ID
from live import hub as hub_module
from live import user_ws

USER, GUARDIAN = str(DEMO_USER_ID), str(DEMO_GUARDIAN_ID)
OFFER = {"sdp": "v=0\r\no=- 4611 2 IN IP4 127.0.0.1\r\n...", "type": "offer"}
ANSWER = {"sdp": "v=0\r\no=- 9922 2 IN IP4 127.0.0.1\r\n...", "type": "answer"}
ICE = {"candidate": "candidate:1 1 udp 2122260223 192.168.1.5 54321 typ host", "sdpMid": "0", "sdpMLineIndex": 0}


def env(type_, payload=None):
    return {"v": 1, "type": type_, "ts": int(time.time() * 1000), "payload": payload or {}}


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(user_ws, "HELLO_TIMEOUT_S", 0.5)
    monkeypatch.setattr(hub_module, "STATUS_INTERVAL_S", 0.05)


@pytest.fixture
def client(make_client):
    return make_client(feature_guardian=True)


@contextmanager
def session(client):
    sid = client.post("/api/v1/sessions", json={"user_id": USER}).json()["session_id"]
    with client.websocket_connect(f"/ws/user/{sid}") as u:
        u.send_json(env("hello", {"user_id": USER}))
        assert u.receive_json()["type"] == "welcome"
        yield sid, u


@contextmanager
def guardian(client, sid):
    with client.websocket_connect(f"/ws/guardian/{sid}?guardian_id={GUARDIAN}") as g:
        g.send_json(env("hello", {"guardian_id": GUARDIAN}))
        yield g


def read_until(ws, type_, limit=400):
    for _ in range(limit):
        if (msg := ws.receive_json())["type"] == type_:
            return msg
    raise AssertionError(f"no {type_}")


def test_offer_answer_and_ice_round_trip(client):
    with session(client) as (sid, u), guardian(client, sid) as g:
        g.send_json(env("webrtc_offer", OFFER))
        offer = read_until(u, "webrtc_offer")["payload"]
        assert offer == {**OFFER, "guardian_id": GUARDIAN}             # unchanged + who sent it

        u.send_json(env("webrtc_answer", {**ANSWER, "guardian_id": GUARDIAN}))
        assert read_until(g, "webrtc_answer")["payload"] == {**ANSWER, "guardian_id": GUARDIAN}

        g.send_json(env("webrtc_ice", ICE))
        assert read_until(u, "webrtc_ice")["payload"] == {**ICE, "guardian_id": GUARDIAN}
        u.send_json(env("webrtc_ice", ICE))                              # no target: every guardian
        assert read_until(g, "webrtc_ice")["payload"] == ICE


def test_phone_answer_reaches_only_the_named_guardian(client):
    with session(client) as (sid, u), guardian(client, sid) as g:
        u.send_json(env("webrtc_answer", {**ANSWER, "guardian_id": "99999999-9999-4999-8999-999999999999"}))
        g.send_json(env("ping"))
        seen = []
        while (msg := g.receive_json())["type"] != "pong":
            seen.append(msg["type"])
        assert "webrtc_answer" not in seen


def test_guardian_signal_with_the_phone_offline_is_dropped(client):
    sid = client.post("/api/v1/sessions", json={"user_id": USER}).json()["session_id"]
    with guardian(client, sid) as g:
        g.send_json(env("webrtc_offer", OFFER))
        g.send_json(env("ping"))
        assert read_until(g, "pong")                                       # no error, socket open


@pytest.mark.parametrize("side", ["user", "guardian"])
def test_oversized_signal_is_rejected(client, side):
    big = {"sdp": "x" * (64 * 1024 + 1), "type": "offer"}
    with session(client) as (sid, u), guardian(client, sid) as g:
        ws = u if side == "user" else g
        ws.send_json(env("webrtc_offer", big))
        assert read_until(ws, "error")["payload"]["code"] == "UNSUPPORTED_MESSAGE"
