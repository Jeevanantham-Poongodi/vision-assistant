"""Signed demo tokens per role (BE-17)."""
import logging
import time
from uuid import uuid4

import pytest
from fastapi import WebSocketDisconnect

import auth
from auth import InvalidToken, make_token, verify_token
from db.repo import DEMO_GUARDIAN_ID, DEMO_USER_ID
from live import hub as hub_module
from live import user_ws
from tests.conftest import make_settings

USER, GUARDIAN = str(DEMO_USER_ID), str(DEMO_GUARDIAN_ID)
SECRET = "test-secret"


# --- Tokens ---

def test_round_trip():
    token, exp = make_token(SECRET, DEMO_USER_ID, "user", ttl_s=60, now=1000)
    assert exp == 1060
    p = verify_token(SECRET, token, now=1059)
    assert (p.sub, p.role) == (DEMO_USER_ID, "user")


@pytest.mark.parametrize("mutate, message", [
    (lambda t: t[:-2] + ("AA" if not t.endswith("AA") else "BB"), "signature"),
    (lambda t: "x" + t, "signature"),
    (lambda t: t.replace(".", ""), "Malformed"),
    (lambda t: "", "Malformed"),
], ids=["tampered-signature", "tampered-body", "no-dot", "empty"])
def test_tampered_tokens_are_rejected(mutate, message):
    token, _ = make_token(SECRET, DEMO_USER_ID, "user")
    with pytest.raises(InvalidToken, match=message):
        verify_token(SECRET, mutate(token))


def test_wrong_secret_expired_and_bad_role():
    token, _ = make_token(SECRET, DEMO_USER_ID, "user", ttl_s=60, now=1000)
    with pytest.raises(InvalidToken, match="signature"):
        verify_token("other-secret", token, now=1001)
    with pytest.raises(InvalidToken, match="expired"):
        verify_token(SECRET, token, now=1060)
    admin, _ = make_token(SECRET, DEMO_USER_ID, "admin")
    with pytest.raises(InvalidToken, match="role"):
        verify_token(SECRET, admin)


def test_empty_secret_is_random_and_warns(caplog):
    with caplog.at_level(logging.WARNING, logger="vision_assistant"):
        a = auth.resolve_secret(make_settings(auth_required=True))
        b = auth.resolve_secret(make_settings(auth_required=True))
    assert a != b and len(a) > 30
    assert any("AUTH_SECRET is empty" in r.getMessage() for r in caplog.records)
    assert auth.resolve_secret(make_settings(auth_secret="fixed")) == "fixed"


# --- REST with AUTH_REQUIRED=true ---

@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(user_ws, "HELLO_TIMEOUT_S", 0.5)
    monkeypatch.setattr(hub_module, "STATUS_INTERVAL_S", 0.05)


@pytest.fixture
def client(make_client):
    return make_client(auth_required=True, auth_secret=SECRET, feature_guardian=True)


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def token_for(client, person: str) -> str:
    r = client.post("/api/v1/auth/demo-token", json={"user_id": person})
    assert r.status_code == 200
    return r.json()["token"]


@pytest.fixture
def arun(client):
    return bearer(token_for(client, USER))


@pytest.fixture
def priya(client):
    return bearer(token_for(client, GUARDIAN))


@pytest.fixture
def stranger():
    return bearer(make_token(SECRET, uuid4(), "user")[0])  # a valid token for someone unrelated


@pytest.fixture
def sid(client, arun):
    return client.post("/api/v1/sessions", json={"user_id": USER}, headers=arun).json()["session_id"]


def code(r) -> tuple[int, str]:
    return r.status_code, r.json()["error"]["code"]


def test_demo_token(client):
    body = client.post("/api/v1/auth/demo-token", json={"user_id": GUARDIAN}).json()
    assert (body["user_id"], body["role"]) == (GUARDIAN, "guardian")
    assert body["expires_at"].endswith("Z")
    r = client.post("/api/v1/auth/demo-token", json={"user_id": str(uuid4())})
    assert code(r) == (404, "USER_NOT_FOUND")


def test_open_routes_need_no_token(client):
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/config").status_code == 200
    assert client.get("/docs").status_code == 200


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer nope.nope"}, {"Authorization": "Basic abc"}],
                         ids=["missing", "invalid", "wrong-scheme"])
def test_missing_or_bad_token_is_401(client, headers):
    r = client.post("/api/v1/sessions", json={"user_id": USER}, headers=headers)
    assert code(r) == (401, "UNAUTHORIZED")


def test_sessions(client, arun, priya, stranger, sid):
    assert code(client.post("/api/v1/sessions", json={"user_id": USER}, headers=priya)) == (403, "FORBIDDEN")
    assert client.get(f"/api/v1/sessions/{sid}", headers=arun).status_code == 200
    assert client.get(f"/api/v1/sessions/{sid}", headers=priya).status_code == 200     # linked guardian
    assert code(client.get(f"/api/v1/sessions/{sid}", headers=stranger)) == (403, "FORBIDDEN")
    assert client.get("/api/v1/sessions", headers=arun).json()["count"] == 1
    assert client.get("/api/v1/sessions", headers=priya).json()["count"] == 1
    assert client.get("/api/v1/sessions", headers=stranger).json()["count"] == 0
    assert code(client.get("/api/v1/sessions", params={"user_id": USER}, headers=stranger)) == (403, "FORBIDDEN")
    assert code(client.post(f"/api/v1/sessions/{sid}/end", headers=priya)) == (403, "FORBIDDEN")
    assert client.post(f"/api/v1/sessions/{sid}/end", headers=arun).status_code == 200


def test_guardian_actions(client, arun, priya, sid):
    msg = {"guardian_id": GUARDIAN, "text": "Stop."}
    assert code(client.post(f"/api/v1/sessions/{sid}/guardian-message", json=msg, headers=arun)) == (403, "FORBIDDEN")
    assert client.post(f"/api/v1/sessions/{sid}/guardian-message", json=msg, headers=priya).status_code == 202
    assert client.get(f"/api/v1/guardians/{GUARDIAN}/users", headers=priya).status_code == 200
    assert code(client.get(f"/api/v1/guardians/{GUARDIAN}/users", headers=arun)) == (403, "FORBIDDEN")


def test_alerts(client, arun, priya, stranger, sid):
    em = {"session_id": sid, "trigger": "button"}
    assert code(client.post("/api/v1/emergency", json=em, headers=priya)) == (403, "FORBIDDEN")
    alert_id = client.post("/api/v1/emergency", json=em, headers=arun).json()["alert_id"]
    upd = {"status": "acknowledged", "guardian_id": GUARDIAN}
    assert code(client.patch(f"/api/v1/alerts/{alert_id}", json=upd, headers=arun)) == (403, "FORBIDDEN")
    assert client.patch(f"/api/v1/alerts/{alert_id}", json=upd, headers=priya).status_code == 200
    assert client.get("/api/v1/alerts", headers=arun).json()["count"] == 1
    assert client.get("/api/v1/alerts", headers=priya).json()["count"] == 1
    assert client.get("/api/v1/alerts", headers=stranger).json()["count"] == 0
    assert code(client.get("/api/v1/alerts", params={"user_id": USER}, headers=stranger)) == (403, "FORBIDDEN")


def test_vision_and_media_routes(client, arun, priya, sid):
    import cv2
    import numpy as np

    image = cv2.imencode(".jpg", np.zeros((8, 8, 3), np.uint8))[1].tobytes()
    files = {"image": ("f.jpg", image, "image/jpeg")}
    assert code(client.post("/api/v1/detect", files=files)) == (401, "UNAUTHORIZED")
    assert client.post("/api/v1/detect", files=files, headers=priya).status_code == 200      # no session: any token
    assert code(client.post("/api/v1/detect", files=files, data={"session_id": sid}, headers=priya)) == (403, "FORBIDDEN")
    assert client.post("/api/v1/detect", files=files, data={"session_id": sid}, headers=arun).status_code == 200
    assert code(client.post("/api/v1/tts", json={"text": "hi"})) == (401, "UNAUTHORIZED")
    assert code(client.post("/api/v1/tts", json={"text": "hi"}, headers=arun)) == (503, "MODEL_NOT_READY")


# --- WebSockets ---

def env(type_, payload=None):
    return {"v": 1, "type": type_, "ts": int(time.time() * 1000), "payload": payload or {}}


def close_code(ws) -> int:
    with pytest.raises(WebSocketDisconnect) as exc:
        while True:
            ws.receive_json()
    return exc.value.code


@pytest.mark.parametrize("who", ["none", "guardian", "tampered"])
def test_user_socket_rejects_the_wrong_token(client, sid, who):
    token = {"none": "", "guardian": token_for(client, GUARDIAN), "tampered": token_for(client, USER) + "x"}[who]
    with client.websocket_connect(f"/ws/user/{sid}?token={token}") as ws:
        assert close_code(ws) == 4004


def test_user_socket_accepts_the_users_token(client, sid):
    with client.websocket_connect(f"/ws/user/{sid}?token={token_for(client, USER)}") as ws:
        ws.send_json(env("hello", {"user_id": USER}))
        assert ws.receive_json()["type"] == "welcome"


@pytest.mark.parametrize("who", ["none", "user"])
def test_guardian_socket_rejects_the_wrong_token(client, sid, who):
    token = "" if who == "none" else token_for(client, USER)
    with client.websocket_connect(f"/ws/guardian/{sid}?guardian_id={GUARDIAN}&token={token}") as ws:
        assert close_code(ws) == 4004


def test_guardian_socket_accepts_the_guardians_token(client, sid):
    with client.websocket_connect(f"/ws/guardian/{sid}?guardian_id={GUARDIAN}&token={token_for(client, GUARDIAN)}") as ws:
        ws.send_json(env("hello", {"guardian_id": GUARDIAN}))
        assert ws.receive_json()["type"] == "welcome"


# --- Off by default ---

def test_auth_off_needs_no_token(make_client):
    client = make_client(feature_guardian=True)
    assert client.post("/api/v1/sessions", json={"user_id": USER}).status_code == 201
    r = client.post("/api/v1/sessions", json={"user_id": USER}, headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 200  # a token is ignored when auth is off
