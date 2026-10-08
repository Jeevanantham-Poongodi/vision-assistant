"""Hazard and emergency alerts, acknowledgement and GET /alerts (BE-10)."""
import asyncio
import base64
import sys
import time
import types
from contextlib import contextmanager
from datetime import timedelta
from uuid import UUID

import cv2
import numpy as np
import pytest
from fastapi import WebSocketDisconnect

from db.repo import DEMO_GUARDIAN_ID, DEMO_USER_ID
from live import alerts
from live import hub as hub_module
from live import user_ws
from live.hub import SessionState
from schemas import Alert, ErrorResponse

USER = str(DEMO_USER_ID)
GUARDIAN = str(DEMO_GUARDIAN_ID)
UNKNOWN = "99999999-9999-4999-8999-999999999999"
LOCATION = {"lat": 11.0168, "lng": 76.9558, "accuracy_m": 12.0, "ts": 1759900530000}


def now_ms() -> int:
    return int(time.time() * 1000)


def env(type_: str, payload: dict | None = None) -> dict:
    return {"v": 1, "type": type_, "ts": now_ms(), "payload": payload or {}}


def jpeg_b64(h: int = 480, w: int = 640) -> str:
    return base64.b64encode(cv2.imencode(".jpg", np.full((h, w, 3), 90, np.uint8))[1].tobytes()).decode()


def frame(frame_id: int) -> dict:
    return env("frame", {"frame_id": frame_id, "image": jpeg_b64(), "width": 640, "height": 480})


def image_size(b64: str) -> tuple[int, int]:
    img = cv2.imdecode(np.frombuffer(base64.b64decode(b64), np.uint8), cv2.IMREAD_COLOR)
    return img.shape[1], img.shape[0]


@pytest.fixture(autouse=True)
def fast_timers(monkeypatch):
    monkeypatch.setattr(user_ws, "HELLO_TIMEOUT_S", 0.5)
    monkeypatch.setattr(hub_module, "STATUS_INTERVAL_S", 0.05)  # guardian traffic never goes quiet


@pytest.fixture
def client(make_client):
    return make_client(feature_guardian=True)


def new_session(client) -> str:
    return client.post("/api/v1/sessions", json={"user_id": USER}).json()["session_id"]


@contextmanager
def user(client, sid):
    with client.websocket_connect(f"/ws/user/{sid}") as ws:
        ws.send_json(env("hello", {"user_id": USER}))
        assert ws.receive_json()["type"] == "welcome"
        yield ws


@contextmanager
def guardian(client, sid, guardian_id=GUARDIAN):
    with client.websocket_connect(f"/ws/guardian/{sid}?guardian_id={guardian_id}") as ws:
        ws.send_json(env("hello", {"guardian_id": guardian_id}))
        yield ws


def read_until(ws, predicate, limit: int = 400) -> dict:
    for _ in range(limit):
        msg = ws.receive_json()
        if predicate(msg):
            return msg
    raise AssertionError("expected message did not arrive")


def alert_of(type_: str):
    return lambda m: m["type"] == "alert" and m["payload"]["type"] == type_


def user_reply(u, type_: str) -> dict:
    """Next message of this type on the phone socket (frame results may be in between)."""
    return read_until(u, lambda m: m["type"] == type_, limit=50)


def stored(client, **query) -> list[dict]:
    return client.get("/api/v1/alerts", params=query).json()["items"]


# --- Hazards (contract 3.3) ---

def test_high_warning_raises_a_hazard_alert_with_snapshot(client):
    sid = new_session(client)
    with guardian(client, sid) as g, user(client, sid) as u:
        u.send_json(env("location", LOCATION))
        u.send_json(frame(1))
        user_reply(u, "frame_result")
        alert = read_until(g, alert_of("hazard"))["payload"]
    Alert.model_validate(alert)
    assert (alert["risk_level"], alert["status"]) == ("high", "open")   # the stub's car warning (R3)
    assert alert["title"] == "Car · right · 4.2 m · approaching"
    assert alert["message"].startswith("Warning. Car approaching from your right")
    assert alert["location"] == {"lat": 11.0168, "lng": 76.9558, "accuracy_m": 12.0}
    assert image_size(alert["snapshot_b64"]) == (320, 240)              # max 320 px wide
    (row,) = stored(client, type="hazard")
    assert row["alert_id"] == alert["alert_id"] and row["snapshot_b64"] is None  # never stored
    raw = asyncio.run(client.app.state.repo.get_alert(UUID(alert["alert_id"])))
    assert raw["payload"]["detection"]["track_id"] == 7                 # the triggering Detection
    assert raw["payload"]["warning"]["rule"] == "R3" and raw["payload"]["frame_id"] == 1


def test_hazard_alerts_are_throttled_per_key(client, monkeypatch):
    sid = new_session(client)
    with user(client, sid) as u:
        for i in range(1, 6):
            u.send_json(frame(i))
            user_reply(u, "frame_result")
        time.sleep(0.2)
        assert len(stored(client, type="hazard")) == 1                  # 5 frames, one alert per 10 s
        monkeypatch.setattr(alerts, "HAZARD_THROTTLE_S", 0.1)
        time.sleep(0.15)
        u.send_json(frame(6))
        user_reply(u, "frame_result")
        time.sleep(0.2)
    assert len(stored(client, type="hazard")) == 2


def result_with(*warnings: dict, detections: list[dict] | None = None) -> dict:
    return {"warnings": list(warnings), "detections": detections or []}


def warning(level: str, track_id=1, class_name="car") -> dict:
    return {"risk_level": level, "track_id": track_id, "class_name": class_name, "short_text": "x", "message": "y"}


def test_only_critical_and_high_warnings_alert():
    state = SessionState()
    due = alerts.due_hazards(state, result_with(warning("medium", 1), warning("low", 2),
                                                warning("high", 3), warning("critical", 4)))
    assert [w["track_id"] for w, _ in due] == [3, 4]


def test_cooldown_key_without_track_uses_class_and_direction():
    det_left = {"track_id": None, "class_name": "chair", "risk_level": "critical", "direction": "left"}
    det_center = {**det_left, "direction": "center"}
    assert alerts.cooldown_key(warning("critical", None, "chair"), det_left) == "chair:left"
    state = SessionState()
    w = warning("critical", None, "chair")
    assert len(alerts.due_hazards(state, result_with(w, detections=[det_left]))) == 1
    assert alerts.due_hazards(state, result_with(w, detections=[det_left])) == []        # same key
    assert len(alerts.due_hazards(state, result_with(w, detections=[det_center]))) == 1  # other key


def test_coder2_make_thumbnail_is_used_when_present(monkeypatch):
    module = types.ModuleType("vision.thumbnail")
    module.make_thumbnail = lambda frame_bgr, detections: f"coder2:{len(detections)}"
    monkeypatch.setitem(sys.modules, "vision.thumbnail", module)
    assert alerts.make_snapshot(np.zeros((480, 640, 3), np.uint8), [{}, {}]) == "coder2:2"


def test_broken_make_thumbnail_falls_back_to_plain(monkeypatch):
    module = types.ModuleType("vision.thumbnail")
    module.make_thumbnail = lambda frame_bgr, detections: 1 / 0
    monkeypatch.setitem(sys.modules, "vision.thumbnail", module)
    assert image_size(alerts.make_snapshot(np.zeros((100, 200, 3), np.uint8), [])) == (200, 100)  # not upscaled
    assert alerts.make_snapshot(None, []) is None


# --- Emergencies over the phone socket (contract 5.2) ---

def test_emergency_button(client):
    sid = new_session(client)
    with guardian(client, sid) as g, user(client, sid) as u:
        u.send_json(env("location", LOCATION))
        u.send_json(frame(1))
        user_reply(u, "frame_result")
        u.send_json(env("emergency", {"trigger": "button", "note": None}))
        ack = user_reply(u, "emergency_ack")["payload"]
        alert = read_until(g, alert_of("emergency"))["payload"]
    assert ack == {"alert_id": alert["alert_id"], "status": "open", "spoken_text": "Your guardian has been notified."}
    assert (alert["risk_level"], alert["title"]) == ("critical", "Emergency triggered")
    assert alert["message"] == "Arun pressed the emergency button."
    assert alert["location"]["lat"] == 11.0168
    assert image_size(alert["snapshot_b64"]) == (320, 240)             # from the latest frame


def test_voice_emergency_without_a_frame(client):
    sid = new_session(client)
    with guardian(client, sid) as g, user(client, sid) as u:
        u.send_json(env("emergency", {"trigger": "voice"}))
        user_reply(u, "emergency_ack")
        alert = read_until(g, alert_of("emergency"))["payload"]
    assert alert["message"] == "Arun asked for help by voice."
    assert alert["snapshot_b64"] is None and alert["location"] is None


def test_repeated_presses_within_10_s_reuse_the_open_emergency(client):
    sid = new_session(client)
    with user(client, sid) as u:
        ids = []
        for _ in range(3):
            u.send_json(env("emergency", {"trigger": "button"}))
            ids.append(user_reply(u, "emergency_ack")["payload"]["alert_id"])
        assert len(set(ids)) == 1
        assert len(stored(client, type="emergency")) == 1
        client.patch(f"/api/v1/alerts/{ids[0]}", json={"status": "resolved", "guardian_id": GUARDIAN})
        user_reply(u, "emergency_ack")                                    # the "responding" ack
        u.send_json(env("emergency", {"trigger": "button"}))             # resolved: a new emergency
        assert user_reply(u, "emergency_ack")["payload"]["alert_id"] != ids[0]
    assert len(stored(client, type="emergency")) == 2


@pytest.mark.parametrize("payload", [{"trigger": "shake"}, {}, {"trigger": "button", "note": "x" * 201}],
                         ids=["bad-trigger", "missing-trigger", "note-too-long"])
def test_invalid_emergency_message(client, payload):
    sid = new_session(client)
    with user(client, sid) as u:
        u.send_json(env("emergency", payload))
        assert user_reply(u, "error")["payload"]["code"] == "UNSUPPORTED_MESSAGE"
    assert stored(client, type="emergency") == []


# --- POST /emergency (contract 7.11) ---

def test_rest_emergency(client):
    sid = new_session(client)
    with guardian(client, sid) as g, user(client, sid) as u:
        r = client.post("/api/v1/emergency", json={
            "session_id": sid, "trigger": "button",
            "location": {"lat": 12.5, "lng": 77.5, "accuracy_m": 5.0}, "note": "fell down"})
        assert r.status_code == 201
        body = r.json()
        Alert.model_validate(body)
        assert (body["type"], body["risk_level"], body["status"]) == ("emergency", "critical", "open")
        assert body["location"] == {"lat": 12.5, "lng": 77.5, "accuracy_m": 5.0}
        assert body["snapshot_b64"] is None                               # WebSocket only
        assert read_until(g, alert_of("emergency"))["payload"]["alert_id"] == body["alert_id"]
        assert user_reply(u, "emergency_ack")["payload"]["status"] == "open"
    raw = asyncio.run(client.app.state.repo.get_alert(UUID(body["alert_id"])))
    assert raw["payload"] == {"trigger": "button", "note": "fell down"}


def test_rest_emergency_with_the_phone_offline(client):
    r = client.post("/api/v1/emergency", json={"session_id": new_session(client), "trigger": "voice"})
    assert r.status_code == 201


@pytest.mark.parametrize("ended", [False, True], ids=["unknown", "ended"])
def test_rest_emergency_session_not_found(client, ended):
    sid = new_session(client) if ended else UNKNOWN
    if ended:
        client.post(f"/api/v1/sessions/{sid}/end")
    r = client.post("/api/v1/emergency", json={"session_id": sid, "trigger": "button"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_rest_emergency_validation(client):
    r = client.post("/api/v1/emergency", json={"session_id": new_session(client), "trigger": "shake"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


# --- Acknowledging (contract 7.13 and 6.1) ---

def emergency_id(client, sid) -> str:
    return client.post("/api/v1/emergency", json={"session_id": sid, "trigger": "button"}).json()["alert_id"]


def patch(client, alert_id, status, guardian_id=GUARDIAN):
    return client.patch(f"/api/v1/alerts/{alert_id}", json={"status": status, "guardian_id": guardian_id})


def test_acknowledge_then_resolve_an_emergency(client):
    sid = new_session(client)
    with guardian(client, sid) as g, user(client, sid) as u:
        aid = emergency_id(client, sid)
        user_reply(u, "emergency_ack")                                    # "notified"
        r = patch(client, aid, "acknowledged")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "acknowledged" and body["acknowledged_by"] == GUARDIAN
        assert body["acknowledged_at"] is not None
        updated = read_until(g, lambda m: m["type"] == "alert_updated")["payload"]
        assert (updated["alert_id"], updated["status"]) == (aid, "acknowledged")
        ack = user_reply(u, "emergency_ack")["payload"]
        assert ack == {"alert_id": aid, "status": "acknowledged",
                       "spoken_text": "Your guardian has seen your emergency and is responding."}
        assert patch(client, aid, "resolved").json()["status"] == "resolved"
        assert read_until(g, lambda m: m["type"] == "alert_updated")["payload"]["status"] == "resolved"
        u.send_json(env("ping"))                                          # no second emergency_ack
        assert u.receive_json()["type"] == "pong"


def test_resolving_an_open_emergency_also_tells_the_phone(client):
    sid = new_session(client)
    with user(client, sid) as u:
        aid = emergency_id(client, sid)
        user_reply(u, "emergency_ack")
        assert patch(client, aid, "resolved").status_code == 200
        assert user_reply(u, "emergency_ack")["payload"]["status"] == "acknowledged"


def test_acknowledging_a_hazard_does_not_speak(client):
    sid = new_session(client)
    with user(client, sid) as u:
        u.send_json(frame(1))
        user_reply(u, "frame_result")
        time.sleep(0.2)
        (hazard,) = stored(client, type="hazard")
        assert patch(client, hazard["alert_id"], "acknowledged").status_code == 200
        u.send_json(env("ping"))
        assert u.receive_json()["type"] == "pong"                          # nothing queued before it


@pytest.mark.parametrize("first, second", [("resolved", "acknowledged"), ("acknowledged", "acknowledged"),
                                           ("resolved", "resolved")])
def test_invalid_transitions(client, first, second):
    aid = emergency_id(client, new_session(client))
    assert patch(client, aid, first).status_code == 200
    r = patch(client, aid, second)
    assert r.status_code == 409
    ErrorResponse.model_validate(r.json())
    assert r.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
    assert r.json()["error"]["details"]["to"] == second


def test_open_is_never_a_target(client):
    aid = emergency_id(client, new_session(client))
    assert patch(client, aid, "open").status_code == 422


@pytest.mark.parametrize("alert, guardian_id", [(UNKNOWN, GUARDIAN), ("real", UNKNOWN), ("real", USER)],
                         ids=["unknown-alert", "unknown-guardian", "not-a-guardian"])
def test_unknown_alert_or_unlinked_guardian_is_not_found(client, alert, guardian_id):
    aid = emergency_id(client, new_session(client)) if alert == "real" else alert
    r = patch(client, aid, "acknowledged", guardian_id)
    assert r.status_code == 404 and r.json()["error"]["code"] == "ALERT_NOT_FOUND"


def test_guardian_socket_ack_alert(client):
    sid = new_session(client)
    with guardian(client, sid) as g, user(client, sid) as u:
        aid = emergency_id(client, sid)
        g.send_json(env("ack_alert", {"alert_id": aid, "status": "acknowledged"}))
        updated = read_until(g, lambda m: m["type"] == "alert_updated")["payload"]
        assert (updated["status"], updated["acknowledged_by"]) == ("acknowledged", GUARDIAN)
        assert user_reply(u, "emergency_ack")["payload"]["status"] == "open"
        assert user_reply(u, "emergency_ack")["payload"]["status"] == "acknowledged"


@pytest.mark.parametrize("payload, code", [
    ({"alert_id": UNKNOWN, "status": "acknowledged"}, "ALERT_NOT_FOUND"),
    ({"alert_id": "real", "status": "open"}, "UNSUPPORTED_MESSAGE"),
    ({"status": "acknowledged"}, "UNSUPPORTED_MESSAGE"),
    ({"alert_id": "resolved-twice", "status": "resolved"}, "INVALID_STATUS_TRANSITION"),
], ids=["unknown-alert", "open-target", "missing-id", "bad-transition"])
def test_guardian_socket_ack_errors(client, payload, code):
    sid = new_session(client)
    aid = emergency_id(client, sid)
    if payload.get("alert_id") == "resolved-twice":
        patch(client, aid, "resolved")
    if payload.get("alert_id") in ("real", "resolved-twice"):
        payload = {**payload, "alert_id": aid}
    with guardian(client, sid) as g:
        g.send_json(env("ack_alert", payload))
        assert read_until(g, lambda m: m["type"] == "error")["payload"]["code"] == code
        g.send_json(env("ping"))
        read_until(g, lambda m: m["type"] == "pong")                      # socket stays open


# --- GET /alerts (contract 7.12) ---

def make_alerts(client, sid, n: int, type_: str = "hazard") -> list[dict]:
    repo = client.app.state.repo
    rows = [asyncio.run(repo.create_alert(session_id=UUID(sid), user_id=DEMO_USER_ID, type=type_,
                                          risk_level="high", title=f"#{i}", message="m")) for i in range(n)]
    base = rows[0]["created_at"]
    for i, row in enumerate(rows):                                          # distinct, increasing times
        row["created_at"] = base + timedelta(seconds=i)
    return rows


def test_list_alerts_filters_newest_first(client):
    s1, s2 = new_session(client), None
    make_alerts(client, s1, 3, "hazard")
    client.post(f"/api/v1/sessions/{s1}/end")
    s2 = new_session(client)
    make_alerts(client, s2, 2, "system")
    body = client.get("/api/v1/alerts").json()
    assert body["count"] == 5
    times = [a["created_at"] for a in body["items"]]
    assert times == sorted(times, reverse=True)
    assert {a["session_id"] for a in stored(client, session_id=s1)} == {s1}
    assert {a["type"] for a in stored(client, type="system")} == {"system"}
    assert len(stored(client, user_id=USER)) == 5 and stored(client, user_id=GUARDIAN) == []
    assert len(stored(client, status="open")) == 5 and stored(client, status="resolved") == []


def test_list_alerts_paging(client):
    sid = new_session(client)
    make_alerts(client, sid, 5)
    page1 = client.get("/api/v1/alerts", params={"limit": 2}).json()["items"]
    page2 = client.get("/api/v1/alerts", params={"limit": 2, "before": page1[-1]["created_at"]}).json()["items"]
    page3 = client.get("/api/v1/alerts", params={"limit": 2, "before": page2[-1]["created_at"]}).json()["items"]
    titles = [a["title"] for a in page1 + page2 + page3]
    assert titles == ["#4", "#3", "#2", "#1", "#0"]


@pytest.mark.parametrize("query", [{"limit": 0}, {"limit": 201}, {"type": "fire"}, {"status": "closed"},
                                   {"before": "2026-10-08T10:00:00"}, {"session_id": "abc"}],
                         ids=["limit-0", "limit-201", "bad-type", "bad-status", "naive-before", "bad-session"])
def test_list_alerts_validation(client, query):
    r = client.get("/api/v1/alerts", params=query)
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_routes_are_documented(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "post" in paths["/api/v1/emergency"]
    assert "get" in paths["/api/v1/alerts"]
    assert "patch" in paths["/api/v1/alerts/{alert_id}"]
