"""GET /guardians/{guardian_id}/users, contract 7.15 (BE-13)."""
import time

import pytest

from db.repo import DEMO_GUARDIAN_ID, DEMO_USER_ID
from live import user_ws
from schemas import LinkedUserList

USER = str(DEMO_USER_ID)
GUARDIAN = str(DEMO_GUARDIAN_ID)
UNKNOWN = "99999999-9999-4999-8999-999999999999"


def env(type_: str, payload: dict | None = None) -> dict:
    return {"v": 1, "type": type_, "ts": int(time.time() * 1000), "payload": payload or {}}


@pytest.fixture(autouse=True)
def fast_hello(monkeypatch):
    monkeypatch.setattr(user_ws, "HELLO_TIMEOUT_S", 0.5)


@pytest.fixture
def client(make_client):
    return make_client()


def lookup(client, guardian_id=GUARDIAN) -> dict:
    r = client.get(f"/api/v1/guardians/{guardian_id}/users")
    assert r.status_code == 200
    LinkedUserList.model_validate(r.json())
    return r.json()


def test_linked_user_without_a_session(client):
    assert lookup(client) == {"items": [{
        "user_id": USER, "name": "Arun", "relation": "sister",
        "active_session_id": None, "online": False, "last_location": None,
    }]}


def test_linked_user_online_with_location(client):
    sid = client.post("/api/v1/sessions", json={"user_id": USER}).json()["session_id"]
    with client.websocket_connect(f"/ws/user/{sid}") as u:
        u.send_json(env("hello", {"user_id": USER}))
        u.receive_json()
        u.send_json(env("location", {"lat": 11.0168, "lng": 76.9558, "accuracy_m": 12.0, "heading_deg": 90.0,
                                     "ts": int(time.time() * 1000)}))
        u.send_json(env("ping"))
        u.receive_json()
        (item,) = lookup(client)["items"]
        assert (item["active_session_id"], item["online"]) == (sid, True)
        assert item["last_location"] == {"lat": 11.0168, "lng": 76.9558, "accuracy_m": 12.0}
    (item,) = lookup(client)["items"]
    assert (item["active_session_id"], item["online"]) == (sid, False)     # still active, phone gone
    assert item["last_location"]["lat"] == 11.0168


def test_ended_session_is_not_active(client):
    sid = client.post("/api/v1/sessions", json={"user_id": USER}).json()["session_id"]
    client.post(f"/api/v1/sessions/{sid}/end")
    (item,) = lookup(client)["items"]
    assert item["active_session_id"] is None and item["last_location"] is None


@pytest.mark.parametrize("guardian_id", [UNKNOWN, USER], ids=["unknown", "a-user-not-a-guardian"])
def test_unknown_guardian_gets_an_empty_list(client, guardian_id):
    assert lookup(client, guardian_id) == {"items": []}


def test_malformed_guardian_id(client):
    r = client.get("/api/v1/guardians/priya/users")
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_lookup_does_not_create_hub_state(client):
    client.post("/api/v1/sessions", json={"user_id": USER})
    before = len(client.app.state.hub._sessions)
    lookup(client)
    assert len(client.app.state.hub._sessions) == before
