"""SupabaseRepo (BE-09): memory first, ordered background writes, startup load, graceful outages."""
import asyncio
import logging
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

import main
from db import client as client_module
from db.client import redact
from db.repo import DEMO_GUARDIAN_ID, DEMO_USER_ID, InMemoryRepo, SupabaseRepo, _dt, to_db
from tests.conftest import make_settings

KEY = "sb_secret_TEST_KEY_123"


class FakeClient:
    """Stands in for db.client.SupabaseClient. Tables hold rows as the API returns them (strings)."""

    def __init__(self, tables: dict | None = None, fail: bool = False, delay_s: float = 0.0):
        self.tables = tables or {}
        self.fail, self.delay_s = fail, delay_s
        self.calls: list[tuple] = []

    def _maybe_fail(self):
        if self.delay_s:
            time.sleep(self.delay_s)
        if self.fail:
            raise ConnectionError(f"could not reach https://abc.supabase.co with apikey={KEY}")

    def safe_error(self, exc):
        return redact(f"{type(exc).__name__}: {exc}", KEY)

    def select(self, table, columns="*", eq=None, in_=None):
        self._maybe_fail()
        rows = self.tables.get(table, [])
        rows = [r for r in rows if all(r.get(k) == v for k, v in (eq or {}).items())]
        return [r for r in rows if all(r.get(k) in vs for k, vs in (in_ or {}).items())]

    def insert(self, table, row):
        self._maybe_fail()
        self.calls.append(("insert", table, row))
        self.tables.setdefault(table, []).append(row)

    def update(self, table, values, eq):
        self._maybe_fail()
        self.calls.append(("update", table, values, eq))


def run(coro):
    return asyncio.run(coro)


async def started(client) -> SupabaseRepo:
    repo = SupabaseRepo(client)
    await repo.start()
    return repo


# --- Writes reach Supabase, in order ---

def test_writes_are_sent_in_order():
    fake = FakeClient()

    async def scenario():
        repo = await started(fake)
        session = await repo.create_session(DEMO_USER_ID, {"platform": "android"})
        alert = await repo.create_alert(session_id=session["id"], user_id=DEMO_USER_ID, type="system",
                                        risk_level="high", title="t", message="m",
                                        location={"lat": 11.0, "lng": 76.9, "accuracy_m": 12.0})
        await repo.update_alert_status(alert["id"], "acknowledged", DEMO_GUARDIAN_ID)
        await repo.insert_location(session["id"], {"lat": 11.0, "lng": 76.9, "ts": 1})
        await repo.end_session(session["id"])
        await repo.close()
        return session, alert

    session, alert = run(scenario())
    assert [(c[0], c[1]) for c in fake.calls] == [
        ("insert", "sessions"), ("insert", "alerts"), ("update", "alerts"),
        ("insert", "location_pings"), ("update", "sessions"),
    ]
    inserted_session = fake.calls[0][2]
    assert inserted_session["id"] == str(session["id"])             # same ID in memory and the DB
    assert inserted_session["user_id"] == str(DEMO_USER_ID)
    assert inserted_session["device_info"] == {"platform": "android"}
    assert datetime.fromisoformat(inserted_session["started_at"]).tzinfo is not None
    inserted_alert = fake.calls[1][2]
    assert (inserted_alert["session_id"], inserted_alert["lat"], inserted_alert["status"]) == (str(session["id"]), 11.0, "open")
    assert fake.calls[2][2]["acknowledged_by"] == str(DEMO_GUARDIAN_ID)
    assert fake.calls[2][3] == {"id": str(alert["id"])}
    assert "id" not in fake.calls[3][2]                              # identity column
    assert fake.calls[4][2]["status"] == "ended" and fake.calls[4][3] == {"id": str(session["id"])}


def test_ending_twice_writes_once():
    fake = FakeClient()

    async def scenario():
        repo = await started(fake)
        session = await repo.create_session(DEMO_USER_ID, {})
        await repo.end_session(session["id"])
        await repo.end_session(session["id"])
        await repo.close()

    run(scenario())
    assert [c[1] for c in fake.calls if c[0] == "update"] == ["sessions"]


def test_location_is_stored_at_most_every_10_s():
    fake = FakeClient()

    async def scenario():
        repo = await started(fake)
        sid = uuid4()
        first = await repo.insert_location(sid, {"lat": 1.0, "lng": 2.0, "ts": 1})
        second = await repo.insert_location(sid, {"lat": 1.1, "lng": 2.1, "ts": 2})
        other = await repo.insert_location(uuid4(), {"lat": 3.0, "lng": 4.0, "ts": 3})  # per session
        await repo.close()
        return first, second, other

    first, second, other = run(scenario())
    assert first is not None and second is None and other is not None
    assert len([c for c in fake.calls if c[1] == "location_pings"]) == 2


def test_alert_acknowledgement_is_recorded_once():
    async def scenario():
        repo = InMemoryRepo()
        alert = await repo.create_alert(session_id=None, user_id=DEMO_USER_ID, type="system",
                                        risk_level="high", title="t", message="m")
        acked = dict(await repo.update_alert_status(alert["id"], "acknowledged", DEMO_GUARDIAN_ID))
        resolved = await repo.update_alert_status(alert["id"], "resolved", uuid4())
        missing = await repo.update_alert_status(uuid4(), "resolved", None)
        return acked, resolved, missing

    acked, resolved, missing = run(scenario())
    assert acked["acknowledged_by"] == DEMO_GUARDIAN_ID and acked["acknowledged_at"] is not None
    assert resolved["status"] == "resolved"
    assert resolved["acknowledged_by"] == DEMO_GUARDIAN_ID                # first acknowledgement kept
    assert resolved["acknowledged_at"] == acked["acknowledged_at"]
    assert missing is None


# --- Outages never reach the caller ---

def test_slow_supabase_never_slows_the_caller():
    fake = FakeClient(delay_s=1.0)

    async def scenario():
        repo = SupabaseRepo(fake)
        repo._writer = asyncio.create_task(repo._write_loop())  # skip the (slow) load
        started_at = time.perf_counter()
        session = await repo.create_session(DEMO_USER_ID, {})
        await repo.create_alert(session_id=session["id"], user_id=DEMO_USER_ID, type="system",
                                risk_level="high", title="t", message="m")
        elapsed = time.perf_counter() - started_at
        found = await repo.get_session(session["id"])
        repo._writer.cancel()
        return elapsed, found

    elapsed, found = run(scenario())
    assert elapsed < 0.1
    assert found is not None


def test_failing_supabase_logs_a_redacted_warning_and_keeps_working(caplog):
    fake = FakeClient(fail=True)

    async def scenario():
        repo = await started(fake)  # load fails too: seed data is used
        sessions = [await repo.create_session(DEMO_USER_ID, {}) for _ in range(3)]
        await repo.close()
        return repo, sessions

    with caplog.at_level(logging.WARNING, logger="vision_assistant"):
        repo, sessions = run(scenario())
    assert run(repo.get_user(DEMO_USER_ID))["name"] == "Arun"               # seed fallback
    assert run(repo.get_session(sessions[-1]["id"])) is not None
    messages = [r.getMessage() for r in caplog.records]
    assert any("could not load data at startup" in m for m in messages)
    write_warnings = [m for m in messages if "write(s) failed" in m]
    assert len(write_warnings) == 1                                          # rate-limited, not 3 lines
    assert all(KEY not in m for m in messages) and any("***" in m for m in messages)


def test_close_does_not_hang_when_supabase_is_stuck(monkeypatch, caplog):
    monkeypatch.setattr(SupabaseRepo, "CLOSE_TIMEOUT_S", 0.2)
    fake = FakeClient(delay_s=2.0)

    async def scenario():
        repo = SupabaseRepo(fake)
        repo._writer = asyncio.create_task(repo._write_loop())
        await repo.create_session(DEMO_USER_ID, {})
        await repo.create_session(DEMO_USER_ID, {})
        started_at = time.perf_counter()
        await repo.close()
        return time.perf_counter() - started_at

    with caplog.at_level(logging.WARNING, logger="vision_assistant"):
        assert run(scenario()) < 1.0
    assert any("not saved at shutdown" in r.getMessage() for r in caplog.records)


# --- Startup load ---

def test_load_restores_users_links_active_sessions_and_open_alerts():
    active, ended = str(uuid4()), str(uuid4())
    open_alert, closed_alert, other_session_alert = str(uuid4()), str(uuid4()), str(uuid4())
    fake = FakeClient(tables={
        "app_users": [
            {"id": str(DEMO_USER_ID), "name": "Arun", "role": "user", "phone": None,
             "created_at": "2026-10-08T10:00:00.12345+00:00"},
            {"id": str(DEMO_GUARDIAN_ID), "name": "Priya", "role": "guardian", "phone": None,
             "created_at": "2026-10-08T10:00:00+00:00"},
        ],
        "guardian_links": [{"guardian_id": str(DEMO_GUARDIAN_ID), "user_id": str(DEMO_USER_ID),
                            "relation": "sister", "created_at": "2026-10-08T10:00:00+00:00"}],
        "sessions": [
            {"id": active, "user_id": str(DEMO_USER_ID), "status": "active", "device_info": {},
             "started_at": "2026-10-08T10:00:00.5+00:00", "ended_at": None},
            {"id": ended, "user_id": str(DEMO_USER_ID), "status": "ended", "device_info": {},
             "started_at": "2026-10-08T09:00:00+00:00", "ended_at": "2026-10-08T09:30:00+00:00"},
        ],
        "alerts": [
            {"id": a, "session_id": s, "user_id": str(DEMO_USER_ID), "type": "system", "risk_level": "high",
             "title": "t", "message": "m", "payload": {}, "lat": None, "lng": None, "accuracy_m": None,
             "status": st, "acknowledged_by": None, "acknowledged_at": None,
             "created_at": "2026-10-08T10:05:00+00:00"}
            for a, s, st in ((open_alert, active, "open"), (closed_alert, active, "resolved"),
                             (other_session_alert, ended, "open"))
        ],
    })

    async def scenario():
        repo = await started(fake)
        result = (await repo.get_active_session(DEMO_USER_ID), await repo.get_session(UUID(ended)),
                  await repo.list_alerts(), await repo.get_linked_users(DEMO_GUARDIAN_ID))
        await repo.close()
        return result

    session, ended_row, alerts, links = run(scenario())
    assert session["id"] == UUID(active)
    assert session["started_at"] == datetime(2026, 10, 8, 10, 0, 0, 500000, tzinfo=timezone.utc)
    assert ended_row is None                                       # only active sessions come back
    assert [a["id"] for a in alerts] == [UUID(open_alert)]         # open alerts of active sessions
    assert links[0]["user_id"] == DEMO_USER_ID


@pytest.mark.parametrize("text, expected", [
    ("2026-10-08T10:00:00+00:00", datetime(2026, 10, 8, 10, 0, tzinfo=timezone.utc)),
    ("2026-10-08T10:00:00.12345+00:00", datetime(2026, 10, 8, 10, 0, 0, 123450, tzinfo=timezone.utc)),
    ("2026-10-08T10:00:00.1Z", datetime(2026, 10, 8, 10, 0, 0, 100000, tzinfo=timezone.utc)),
    ("2026-10-08T10:00:00.123456789+00:00", datetime(2026, 10, 8, 10, 0, 0, 123456, tzinfo=timezone.utc)),
    ("2026-10-08T10:00:00", datetime(2026, 10, 8, 10, 0, tzinfo=timezone.utc)),
])
def test_timestamps_from_postgres(text, expected):
    assert _dt(text) == expected


def test_to_db_serialises_uuids_and_datetimes():
    row = to_db({"id": DEMO_USER_ID, "at": datetime(2026, 1, 1, tzinfo=timezone.utc), "n": 1, "d": {"a": 1}})
    assert row == {"id": str(DEMO_USER_ID), "at": "2026-01-01T00:00:00+00:00", "n": 1, "d": {"a": 1}}


def test_redact():
    assert redact(f"bad apikey={KEY} end", KEY) == "bad apikey=*** end"
    assert redact("nothing to hide", "") == "nothing to hide"


# --- Choosing the repository ---

def test_memory_only_unless_the_flag_and_credentials_are_set(monkeypatch):
    monkeypatch.setattr(client_module, "SupabaseClient", lambda url, key: FakeClient())
    full = {"supabase_url": "https://abc.supabase.co", "supabase_service_role_key": KEY}
    assert type(main.make_repo(make_settings(**full))) is InMemoryRepo                     # flag off
    assert type(main.make_repo(make_settings(feature_alerts_db=True))) is InMemoryRepo      # no credentials
    assert type(main.make_repo(make_settings(feature_alerts_db=True, **full))) is SupabaseRepo


def test_bad_client_config_falls_back_to_memory(monkeypatch, caplog):
    def broken(url, key):
        raise ValueError(f"Invalid URL {url} {key}")

    monkeypatch.setattr(client_module, "SupabaseClient", broken)
    with caplog.at_level(logging.WARNING, logger="vision_assistant"):
        repo = main.make_repo(make_settings(feature_alerts_db=True, supabase_url="nope", supabase_service_role_key=KEY))
    assert type(repo) is InMemoryRepo
    assert all(KEY not in r.getMessage() for r in caplog.records)


def test_app_keeps_working_when_supabase_is_down(make_client, monkeypatch, caplog):
    monkeypatch.setattr(client_module, "SupabaseClient", lambda url, key: FakeClient(fail=True))
    with caplog.at_level(logging.WARNING, logger="vision_assistant"):
        client = make_client(feature_alerts_db=True, supabase_url="https://abc.supabase.co",
                             supabase_service_role_key=KEY)
        r = client.post("/api/v1/sessions", json={"user_id": str(DEMO_USER_ID)})
        assert r.status_code == 201
        sid = r.json()["session_id"]
        with client.websocket_connect(f"/ws/user/{sid}") as ws:
            ws.send_json({"v": 1, "type": "hello", "ts": int(time.time() * 1000), "payload": {"user_id": str(DEMO_USER_ID)}})
            assert ws.receive_json()["type"] == "welcome"
            ws.send_json({"v": 1, "type": "ping", "ts": int(time.time() * 1000), "payload": {}})
            assert ws.receive_json()["type"] == "pong"
        assert client.post(f"/api/v1/sessions/{sid}/end").json()["status"] == "ended"
    assert isinstance(client.app.state.repo, SupabaseRepo)
    assert all(KEY not in r.getMessage() for r in caplog.records)
