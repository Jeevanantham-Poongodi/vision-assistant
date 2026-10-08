"""Guardian messages to the phone, contract 6.1/6.2/7.14 (BE-11)."""
import time
from contextlib import contextmanager

import pytest

from db.repo import DEMO_GUARDIAN_ID, DEMO_USER_ID
from live import hub as hub_module
from live import user_ws

USER = str(DEMO_USER_ID)
GUARDIAN = str(DEMO_GUARDIAN_ID)
UNKNOWN = "99999999-9999-4999-8999-999999999999"


def env(type_: str, payload: dict | None = None) -> dict:
    return {"v": 1, "type": type_, "ts": int(time.time() * 1000), "payload": payload or {}}


@pytest.fixture(autouse=True)
def fast_timers(monkeypatch):
    monkeypatch.setattr(user_ws, "HELLO_TIMEOUT_S", 0.5)
    monkeypatch.setattr(hub_module, "STATUS_INTERVAL_S", 0.05)


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
def guardian(client, sid):
    with client.websocket_connect(f"/ws/guardian/{sid}?guardian_id={GUARDIAN}") as ws:
        ws.send_json(env("hello", {"guardian_id": GUARDIAN}))
        yield ws


def read_until(ws, type_: str, limit: int = 300) -> dict:
    for _ in range(limit):
        msg = ws.receive_json()
        if msg["type"] == type_:
            return msg
    raise AssertionError(f"no {type_}")


def post_message(client, sid, text, guardian_id=GUARDIAN):
    return client.post(f"/api/v1/sessions/{sid}/guardian-message", json={"guardian_id": guardian_id, "text": text})


# --- Guardian socket ---

def test_guardian_message_is_spoken_on_the_phone(client):
    sid = new_session(client)
    with guardian(client, sid) as g, user(client, sid) as u:
        g.send_json(env("guardian_message", {"text": "  Turn right and continue straight.  "}))
        to_phone = read_until(u, "guardian_message")["payload"]
        delivered = read_until(g, "message_delivered")["payload"]
    assert to_phone["guardian_name"] == "Priya"
    assert to_phone["text"] == "Turn right and continue straight."          # trimmed
    assert to_phone["spoken_text"] == "Your guardian says: Turn right and continue straight."
    assert delivered == {"message_id": to_phone["message_id"], "text": to_phone["text"], "delivered": True}


def test_phone_offline_is_not_delivered(client):
    sid = new_session(client)
    with guardian(client, sid) as g:
        g.send_json(env("guardian_message", {"text": "Stop."}))
        assert read_until(g, "message_delivered")["payload"]["delivered"] is False


@pytest.mark.parametrize("payload", [{"text": ""}, {"text": "    "}, {"text": "x" * 201}, {}],
                         ids=["empty", "blank", "too-long", "missing"])
def test_invalid_guardian_message(client, payload):
    sid = new_session(client)
    with guardian(client, sid) as g, user(client, sid) as u:
        g.send_json(env("guardian_message", payload))
        assert read_until(g, "error")["payload"]["code"] == "UNSUPPORTED_MESSAGE"
        u.send_json(env("ping"))
        assert u.receive_json()["type"] == "pong"                           # nothing reached the phone


# --- REST (contract 7.14) ---

def test_rest_message_is_delivered(client):
    sid = new_session(client)
    with user(client, sid) as u:
        r = post_message(client, sid, "Stop and wait.")
        assert r.status_code == 202
        body = r.json()
        assert body["delivered"] is True
        to_phone = read_until(u, "guardian_message")["payload"]
    assert to_phone["message_id"] == body["message_id"]
    assert to_phone["spoken_text"] == "Your guardian says: Stop and wait."


def test_rest_message_with_the_phone_offline(client):
    r = post_message(client, new_session(client), "Stop and wait.")
    assert r.status_code == 202 and r.json()["delivered"] is False


@pytest.mark.parametrize("case", ["unknown-session", "ended-session", "unknown-guardian", "user-not-guardian"])
def test_rest_message_not_found(client, case):
    sid = new_session(client)
    if case == "ended-session":
        client.post(f"/api/v1/sessions/{sid}/end")
    guardian_id = {"unknown-guardian": UNKNOWN, "user-not-guardian": USER}.get(case, GUARDIAN)
    r = post_message(client, UNKNOWN if case == "unknown-session" else sid, "Stop.", guardian_id)
    assert r.status_code == 404 and r.json()["error"]["code"] == "SESSION_NOT_FOUND"


@pytest.mark.parametrize("text", ["", "   ", "x" * 201])
def test_rest_message_validation(client, text):
    r = post_message(client, new_session(client), text)
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
