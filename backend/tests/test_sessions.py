"""Sessions REST, contract 7.4-7.7 (BE-03)."""
from uuid import UUID

import pytest

from db.repo import DEMO_GUARDIAN_ID, DEMO_USER_ID
from schemas import Session

USER = str(DEMO_USER_ID)
GUARDIAN = str(DEMO_GUARDIAN_ID)
UNKNOWN = "99999999-9999-4999-8999-999999999999"
BASE = "/api/v1/sessions"


class FakeSocket:
    def __init__(self, broken: bool = False):
        self.broken = broken
        self.closed_with: int | None = None

    async def close(self, code: int = 1000):
        if self.broken:
            raise RuntimeError("socket already gone")
        self.closed_with = code


@pytest.fixture
def client(make_client):
    return make_client()


def start(client, user_id: str = USER, **device_info):
    return client.post(BASE, json={"user_id": user_id, "device_info": device_info})


def error_code(r) -> str:
    return r.json()["error"]["code"]


# --- POST /sessions (7.4) ---

def test_create_session(client):
    r = start(client, platform="android")
    assert r.status_code == 201
    body = r.json()
    Session.model_validate(body)
    sid = body["session_id"]
    assert body["user_id"] == USER
    assert body["status"] == "active"
    assert body["ended_at"] is None
    assert body["user_online"] is False
    assert body["device_info"] == {"platform": "android"}
    assert body["ws_url"] == f"/ws/user/{sid}"
    assert body["guardian_ws_url"] == f"/ws/guardian/{sid}"
    assert body["started_at"].endswith("Z")


def test_device_info_is_optional(client):
    r = client.post(BASE, json={"user_id": USER})
    assert r.status_code == 201
    assert r.json()["device_info"] == {}


def test_existing_active_session_is_returned_with_200(client):
    first = start(client).json()
    r = start(client)
    assert r.status_code == 200
    assert r.json()["session_id"] == first["session_id"]


@pytest.mark.parametrize("user_id", [UNKNOWN, GUARDIAN])
def test_unknown_user_or_guardian_is_user_not_found(client, user_id):
    r = start(client, user_id)
    assert r.status_code == 404
    assert error_code(r) == "USER_NOT_FOUND"


def test_malformed_user_id_is_validation_error(client):
    r = start(client, "arun")
    assert r.status_code == 422
    assert error_code(r) == "VALIDATION_ERROR"


# --- GET /sessions/{id} (7.6) ---

def test_get_session(client):
    sid = start(client).json()["session_id"]
    r = client.get(f"{BASE}/{sid}")
    assert r.status_code == 200
    assert r.json()["session_id"] == sid


def test_get_unknown_session(client):
    r = client.get(f"{BASE}/{UNKNOWN}")
    assert r.status_code == 404
    assert error_code(r) == "SESSION_NOT_FOUND"


# --- GET /sessions (7.5) ---

def test_list_sessions_filters_and_order(client):
    old = start(client).json()["session_id"]
    client.post(f"{BASE}/{old}/end")
    new = start(client).json()["session_id"]

    body = client.get(BASE, params={"user_id": USER}).json()
    assert body["count"] == 2
    assert [s["session_id"] for s in body["items"]] == [new, old]  # newest first

    active = client.get(BASE, params={"user_id": USER, "status": "active"}).json()
    assert (active["count"], active["items"][0]["session_id"]) == (1, new)
    ended = client.get(BASE, params={"status": "ended"}).json()
    assert (ended["count"], ended["items"][0]["session_id"]) == (1, old)

    assert client.get(BASE, params={"user_id": GUARDIAN}).json() == {"items": [], "count": 0}


def test_list_sessions_rejects_unknown_status(client):
    r = client.get(BASE, params={"status": "paused"})
    assert r.status_code == 422
    assert error_code(r) == "VALIDATION_ERROR"


def test_each_client_starts_empty(make_client):
    start(make_client())
    assert make_client().get(BASE).json()["count"] == 0


# --- POST /sessions/{id}/end (7.7) ---

def test_end_session(client):
    sid = start(client).json()["session_id"]
    r = client.post(f"{BASE}/{sid}/end")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ended"
    assert body["ended_at"].endswith("Z")

    again = client.post(f"{BASE}/{sid}/end")
    assert again.status_code == 200
    assert again.json()["ended_at"] == body["ended_at"]  # unchanged


def test_end_unknown_session(client):
    r = client.post(f"{BASE}/{UNKNOWN}/end")
    assert r.status_code == 404
    assert error_code(r) == "SESSION_NOT_FOUND"


def test_new_session_after_ending(client):
    old = start(client).json()["session_id"]
    client.post(f"{BASE}/{old}/end")
    r = start(client)
    assert r.status_code == 201
    assert r.json()["session_id"] != old


# --- Hub: user_online and closing sockets ---

def test_user_online_comes_from_hub(client):
    sid = start(client).json()["session_id"]
    hub = client.app.state.hub
    hub.state(UUID(sid)).user_ws = FakeSocket()
    assert client.get(f"{BASE}/{sid}").json()["user_online"] is True


def test_end_closes_sockets_and_drops_pipeline(client):
    sid = start(client).json()["session_id"]
    state = client.app.state.hub.state(UUID(sid))
    user, guardian, broken = FakeSocket(), FakeSocket(), FakeSocket(broken=True)
    state.user_ws, state.guardians, state.pipeline = user, {guardian, broken}, object()

    body = client.post(f"{BASE}/{sid}/end").json()
    assert user.closed_with == 1000
    assert guardian.closed_with == 1000  # a broken socket does not stop the others
    assert body["user_online"] is False
    assert client.app.state.hub.is_online(UUID(sid)) is False
    assert client.app.state.hub.state(UUID(sid)).pipeline is None  # fresh state, pipeline gone


# --- Docs ---

def test_routes_are_documented(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/api/v1/sessions", "/api/v1/sessions/{session_id}", "/api/v1/sessions/{session_id}/end"} <= set(paths)
    assert set(paths["/api/v1/sessions"]) == {"get", "post"}
