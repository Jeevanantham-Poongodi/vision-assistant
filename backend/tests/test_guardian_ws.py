"""Session hub and guardian WebSocket, contracts 5.2 and 6 (BE-08)."""
import asyncio
import base64
import time
from contextlib import contextmanager
from uuid import UUID

import cv2
import numpy as np
import pytest
from fastapi import WebSocketDisconnect

from db.repo import DEMO_GUARDIAN_ID, DEMO_USER_ID
from live import hub as hub_module
from live import user_ws
from live.hub import GuardianConnection, SessionState, post_all
from schemas import Alert, FrameResult, Session

USER = str(DEMO_USER_ID)
GUARDIAN = str(DEMO_GUARDIAN_ID)
UNKNOWN = "99999999-9999-4999-8999-999999999999"
BASE = "/api/v1/sessions"


def now_ms() -> int:
    return int(time.time() * 1000)


def env(type_: str, payload: dict | None = None) -> dict:
    return {"v": 1, "type": type_, "ts": now_ms(), "payload": payload or {}}


def jpeg_b64() -> str:
    return base64.b64encode(cv2.imencode(".jpg", np.zeros((12, 16, 3), np.uint8))[1].tobytes()).decode()


def frame(frame_id: int, image: str) -> dict:
    return env("frame", {"frame_id": frame_id, "image": image, "width": 16, "height": 12})


@pytest.fixture(autouse=True)
def fast_timers(monkeypatch):
    monkeypatch.setattr(user_ws, "HELLO_TIMEOUT_S", 0.5)
    monkeypatch.setattr(hub_module, "STATUS_INTERVAL_S", 0.05)   # guardian traffic never goes quiet
    monkeypatch.setattr(hub_module, "SILENCE_TIMEOUT_S", 0.4)
    monkeypatch.setattr(hub_module, "RELAY_INTERVAL_S", 0.5)


@pytest.fixture
def client(make_client):
    return make_client(feature_guardian=True)


def new_session(client) -> str:
    return client.post(BASE, json={"user_id": USER}).json()["session_id"]


@contextmanager
def user(client, sid: str):
    with client.websocket_connect(f"/ws/user/{sid}") as ws:
        ws.send_json(env("hello", {"user_id": USER}))
        assert ws.receive_json()["type"] == "welcome"
        yield ws


@contextmanager
def guardian(client, sid: str, guardian_id: str = GUARDIAN):
    """Connects and says hello. The first messages are welcome and user_status."""
    with client.websocket_connect(f"/ws/guardian/{sid}?guardian_id={guardian_id}") as ws:
        ws.send_json(env("hello", {"guardian_id": guardian_id}))
        yield ws


def close_code(ws) -> int:
    with pytest.raises(WebSocketDisconnect) as exc:
        while True:  # guardian traffic may arrive before the close
            ws.receive_json()
    return exc.value.code


def read_until(ws, predicate, limit: int = 300) -> dict:
    for _ in range(limit):
        msg = ws.receive_json()
        if predicate(msg):
            return msg
    raise AssertionError("expected message did not arrive")


def of_type(type_: str, **payload):
    return lambda m: m["type"] == type_ and all(m["payload"].get(k) == v for k, v in payload.items())


def drain(ws, seconds: float) -> list[dict]:
    """Everything the guardian receives for a while (the status ticker keeps messages flowing)."""
    out, end = [], time.monotonic() + seconds
    while time.monotonic() < end:
        out.append(ws.receive_json())
    return out


def drain_alive(g, u, seconds: float) -> list[dict]:
    """Like drain, but the phone keeps pinging, so the silence rule does not fire."""
    out, end = [], time.monotonic() + seconds
    while time.monotonic() < end:
        u.send_json(env("ping"))
        assert u.receive_json()["type"] == "pong"
        out.append(g.receive_json())
    return out


def pong_barrier(ws) -> list[dict]:
    """Messages queued before a ping/pong round trip: the writer is FIFO, so nothing is in flight after it."""
    ws.send_json(env("ping"))
    seen = []
    while (msg := ws.receive_json())["type"] != "pong":
        seen.append(msg)
    return seen


# --- Connecting ---

def test_unknown_session_closes_4001(client):
    with guardian(client, UNKNOWN) as g:
        assert close_code(g) == 4001


def test_ended_session_closes_4001(client):
    sid = new_session(client)
    client.post(f"{BASE}/{sid}/end")
    with guardian(client, sid) as g:
        assert close_code(g) == 4001


@pytest.mark.parametrize("query", [f"?guardian_id={UNKNOWN}", f"?guardian_id={USER}", "?guardian_id=priya", ""],
                         ids=["unknown-guardian", "user-is-not-a-guardian", "malformed-id", "missing-id"])
def test_unlinked_or_missing_guardian_closes_4001(client, query):
    sid = new_session(client)
    with client.websocket_connect(f"/ws/guardian/{sid}{query}") as g:
        assert close_code(g) == 4001


def test_feature_flag_off_closes_4003(make_client):
    client = make_client()  # FEATURE_GUARDIAN defaults to false
    sid = new_session(client)
    with guardian(client, sid) as g:
        assert close_code(g) == 4003


def test_no_hello_closes_4003(client):
    sid = new_session(client)
    with client.websocket_connect(f"/ws/guardian/{sid}?guardian_id={GUARDIAN}") as g:
        assert close_code(g) == 4003


def test_hello_for_another_guardian_closes_4003(client):
    sid = new_session(client)
    with client.websocket_connect(f"/ws/guardian/{sid}?guardian_id={GUARDIAN}") as g:
        g.send_json(env("hello", {"guardian_id": UNKNOWN}))
        assert close_code(g) == 4003


# --- Welcome ---

def test_welcome_then_status(client):
    sid = new_session(client)
    with guardian(client, sid) as g:
        welcome = g.receive_json()
        assert welcome["type"] == "welcome"
        payload = welcome["payload"]
        Session.model_validate(payload["session"])
        assert payload["session"]["session_id"] == sid
        assert payload["user"] == {"user_id": USER, "name": "Arun"}
        assert payload["open_alerts"] == []
        status = g.receive_json()
        assert status["type"] == "user_status"
        assert status["payload"]["online"] is False and status["payload"]["last_seen"] is None


def test_welcome_shows_online_user_and_latest_location(client):
    sid = new_session(client)
    loc = {"lat": 11.0168, "lng": 76.9558, "accuracy_m": 12.0, "heading_deg": 87.0, "speed_mps": 0.9, "ts": now_ms()}
    with user(client, sid) as u:
        u.send_json(env("location", loc))
        u.send_json(env("ping"))
        assert u.receive_json()["type"] == "pong"  # the location was handled before the ping
        with guardian(client, sid) as g:
            assert g.receive_json()["type"] == "welcome"
            assert g.receive_json()["payload"]["online"] is True
            msg = read_until(g, of_type("location"))
            assert msg["payload"] == loc  # a refreshed guardian page is not left empty


# --- Relay ---

def test_snapshot_and_frame_result_are_relayed(client):
    sid = new_session(client)
    image = jpeg_b64()
    with guardian(client, sid) as g, user(client, sid) as u:
        u.send_json(frame(1, image))
        assert u.receive_json()["type"] == "frame_result"
        snap = read_until(g, of_type("snapshot"))
        assert snap["payload"] == {"frame_id": 1, "image": image, "width": 16, "height": 12}
        result = read_until(g, of_type("frame_result"))
        FrameResult.model_validate(result["payload"])
        assert result["payload"]["frame_id"] == 1


def test_relay_is_at_most_two_per_second(client, monkeypatch):
    monkeypatch.setattr(hub_module, "RELAY_INTERVAL_S", 0.5)
    sid = new_session(client)
    with guardian(client, sid) as g, user(client, sid) as u:
        start = time.monotonic()
        for i in range(1, 9):
            u.send_json(frame(i, jpeg_b64()))
            assert u.receive_json()["type"] == "frame_result"
        elapsed = time.monotonic() - start
        seen = pong_barrier(g)
    snapshots = [m for m in seen if m["type"] == "snapshot"]
    assert 1 <= len(snapshots) <= int(elapsed / 0.5) + 1
    assert len(snapshots) < 8


def test_location_is_relayed_unchanged(client):
    sid = new_session(client)
    loc = {"lat": 11.0168, "lng": 76.9558, "accuracy_m": 12.0, "heading_deg": None, "speed_mps": None, "ts": now_ms()}
    with guardian(client, sid) as g, user(client, sid) as u:
        u.send_json(env("location", loc))
        assert read_until(g, of_type("location"))["payload"] == loc


@pytest.mark.parametrize("payload", [{"lat": 91.0, "lng": 0.0, "ts": 1}, {"lat": 1.0}, {}], ids=["bad-lat", "no-lng", "empty"])
def test_invalid_location_is_rejected(client, payload):
    sid = new_session(client)
    with user(client, sid) as u:
        u.send_json(env("location", payload))
        assert u.receive_json()["payload"]["code"] == "UNSUPPORTED_MESSAGE"
        u.send_json(env("ping"))
        assert u.receive_json()["type"] == "pong"


def test_battery_comes_from_the_phone_status(client):
    sid = new_session(client)
    with guardian(client, sid) as g, user(client, sid) as u:
        u.send_json(env("status", {"battery_pct": 64, "fps": 4.8, "camera": "environment"}))
        status = read_until(g, of_type("user_status", battery_pct=64))
        assert status["payload"]["online"] is True
        assert isinstance(status["payload"]["last_seen"], int)


@pytest.mark.parametrize("payload", [{"battery_pct": 150}, {"battery_pct": "full"}], ids=["over-100", "not-a-number"])
def test_invalid_status_is_rejected(client, payload):
    sid = new_session(client)
    with user(client, sid) as u:
        u.send_json(env("status", payload))
        assert u.receive_json()["payload"]["code"] == "UNSUPPORTED_MESSAGE"


def test_user_status_measures_fps_and_latency_on_the_server(client):
    sid = new_session(client)
    with guardian(client, sid) as g, user(client, sid) as u:
        for i in range(1, 6):
            u.send_json(frame(i, jpeg_b64()))
            u.receive_json()
        status = read_until(g, lambda m: m["type"] == "user_status" and m["payload"]["fps"] > 0)
        assert status["payload"]["latency_ms"] is not None and status["payload"]["latency_ms"] >= 0


def test_two_guardians_both_receive_and_closing_one_is_harmless(client):
    sid = new_session(client)
    with user(client, sid) as u:
        with guardian(client, sid) as g1:
            with guardian(client, sid) as g2:
                u.send_json(frame(1, jpeg_b64()))
                u.receive_json()
                read_until(g1, of_type("snapshot"))
                read_until(g2, of_type("snapshot"))
            u.send_json(env("location", {"lat": 1.0, "lng": 2.0, "ts": now_ms()}))
            assert read_until(g1, of_type("location"))["payload"]["lat"] == 1.0  # g2 left, g1 unaffected
        u.send_json(env("ping"))
        assert u.receive_json()["type"] == "pong"


# --- Online / offline ---

def test_offline_status_is_immediate_and_alert_follows(client):
    sid = new_session(client)
    with guardian(client, sid) as g:
        with user(client, sid):
            read_until(g, of_type("user_status", online=True))
        read_until(g, of_type("user_status", online=False))   # right away
        alert = read_until(g, of_type("alert"))                # after the silence timeout
    body = alert["payload"]
    Alert.model_validate(body)
    assert (body["type"], body["risk_level"], body["status"]) == ("system", "high", "open")
    assert body["title"] == "User went offline" and "Arun" in body["message"]
    assert body["session_id"] == sid and body["user_id"] == USER
    with guardian(client, sid) as g2:                          # a guardian joining later sees it
        assert [a["alert_id"] for a in g2.receive_json()["payload"]["open_alerts"]] == [body["alert_id"]]


def test_quick_reconnect_raises_no_alert(client):
    sid = new_session(client)
    with guardian(client, sid) as g:
        with user(client, sid):
            read_until(g, of_type("user_status", online=True))
        with user(client, sid) as u:                            # back before the timeout
            msgs = drain_alive(g, u, 0.8)
    assert not [m for m in msgs if m["type"] == "alert"]
    assert msgs[-1]["type"] == "user_status" and msgs[-1]["payload"]["online"] is True


def test_replaced_connection_never_shows_offline(client):
    sid = new_session(client)
    with guardian(client, sid) as g:
        with user(client, sid) as old:
            read_until(g, of_type("user_status", online=True))
            with user(client, sid) as new:
                with pytest.raises(WebSocketDisconnect) as exc:
                    while True:
                        old.receive_json()
                assert exc.value.code == 4002
                msgs = drain_alive(g, new, 0.8)
    assert all(m["type"] == "user_status" and m["payload"]["online"] is True for m in msgs)


def test_ending_the_session_is_not_an_alert(client):
    sid = new_session(client)
    with guardian(client, sid) as g, user(client, sid):
        read_until(g, of_type("user_status", online=True))
        client.post(f"{BASE}/{sid}/end")
        assert close_code(g) == 1000
    alerts = asyncio.run(client.app.state.repo.list_alerts(UUID(sid)))
    assert alerts == []


def test_silence_marks_the_user_offline_then_online_again(client):
    sid = new_session(client)
    with guardian(client, sid) as g, user(client, sid) as u:
        read_until(g, of_type("user_status", online=True))
        read_until(g, of_type("user_status", online=False))     # nothing from the phone for > 0.4 s
        read_until(g, of_type("alert"))
        assert client.get(f"{BASE}/{sid}").json()["user_online"] is False
        u.send_json(env("ping"))                                 # any message is a sign of life
        assert u.receive_json()["type"] == "pong"
        read_until(g, of_type("user_status", online=True))
        assert client.get(f"{BASE}/{sid}").json()["user_online"] is True


def test_offline_alerts_are_throttled(client):
    sid = new_session(client)
    with guardian(client, sid) as g, user(client, sid) as u:
        read_until(g, of_type("alert"))                          # first silence
        u.send_json(env("ping"))
        u.receive_json()
        read_until(g, of_type("user_status", online=True))
        read_until(g, of_type("user_status", online=False))      # second silence, within 60 s
        msgs = drain(g, 0.6)
    assert not [m for m in msgs if m["type"] == "alert"]
    assert len(asyncio.run(client.app.state.repo.list_alerts(UUID(sid)))) == 1


# --- Guardian receive loop ---

def test_guardian_ping_and_ignored_messages(client):
    sid = new_session(client)
    with guardian(client, sid) as g:
        for type_, payload in (("guardian_message", {"text": "Stop"}), ("ack_alert", {"alert_id": UNKNOWN, "status": "acknowledged"})):
            g.send_json(env(type_, payload))
        assert [m for m in pong_barrier(g) if m["type"] == "error"] == []


@pytest.mark.parametrize("send", [
    lambda g: g.send_json(env("dance")),
    lambda g: g.send_text("{nope"),
    lambda g: g.send_bytes(b"\x00"),
], ids=["unknown-type", "not-json", "binary"])
def test_guardian_bad_messages_get_an_error_and_the_socket_stays_open(client, send):
    sid = new_session(client)
    with guardian(client, sid) as g:
        send(g)
        err = read_until(g, of_type("error"))
        assert err["payload"]["code"] == "UNSUPPORTED_MESSAGE"
        assert pong_barrier(g) is not None


# --- A slow guardian never holds up anyone else ---

class StuckSocket:
    """A guardian whose connection accepts nothing."""
    def __init__(self):
        self.closed_with = None

    async def send_json(self, message):
        await asyncio.sleep(3600)

    async def close(self, code=1000):
        self.closed_with = code


class OpenSocket:
    def __init__(self):
        self.sent = []

    async def send_json(self, message):
        self.sent.append(message)

    async def close(self, code=1000):
        pass


def test_a_stuck_guardian_is_dropped_without_blocking_the_others(monkeypatch):
    monkeypatch.setattr(hub_module, "GUARDIAN_QUEUE_SIZE", 4)
    monkeypatch.setattr(hub_module, "GUARDIAN_MAX_DROPS", 3)

    async def scenario():
        stuck_ws, healthy_ws = StuckSocket(), OpenSocket()
        stuck = GuardianConnection(stuck_ws, UUID(UNKNOWN))
        healthy = GuardianConnection(healthy_ws, UUID(GUARDIAN))
        state = SessionState(guardians={stuck, healthy})
        started = time.monotonic()
        for i in range(40):
            post_all(state, "snapshot", {"frame_id": i})
            await asyncio.sleep(0)             # let the healthy writer run
        assert time.monotonic() - started < 1.0   # post never waited for the stuck guardian
        await asyncio.sleep(0.05)
        return stuck_ws, stuck, healthy_ws

    stuck_ws, stuck, healthy_ws = asyncio.run(scenario())
    assert stuck_ws.closed_with == 1013 and stuck.closed
    assert [m["payload"]["frame_id"] for m in healthy_ws.sent] == list(range(40))


def test_end_session_survives_a_guardian_that_raises_on_close(client):
    sid = new_session(client)

    class Exploding:
        async def close(self, code=1000):
            raise RuntimeError("boom")

    state = client.app.state.hub.state(UUID(sid))
    state.guardians.add(Exploding())
    assert client.post(f"{BASE}/{sid}/end").status_code == 200
