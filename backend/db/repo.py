# backend/db/repo.py
"""Data access, contract section 10. Owner: Coder 3.
InMemoryRepo is the working copy every request reads from. SupabaseRepo (below) extends it and
also queues each write to Supabase, so routes never change and never wait on the network.
Rows are dicts shaped like the 001_init.sql columns."""
import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timezone
from itertools import takewhile
from typing import Any
from uuid import UUID, uuid4

from config import THRESHOLDS

log = logging.getLogger("vision_assistant")

Row = dict[str, Any]

# Contract 10 seed data: the fixed IDs used by frontend mocks, Postman and the demo.
DEMO_USER_ID = UUID("11111111-1111-1111-1111-111111111111")
DEMO_GUARDIAN_ID = UUID("22222222-2222-2222-2222-222222222222")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class InMemoryRepo:
    def __init__(self) -> None:
        self._users: dict[UUID, Row] = {}
        self._guardian_links: list[Row] = []
        self._sessions: dict[UUID, Row] = {}
        self._alerts: dict[UUID, Row] = {}
        self._locations: dict[UUID, deque[Row]] = {}   # recent stored pings per session
        self._last_location_at: dict[UUID, float] = {}  # time.monotonic() of the last stored ping
        self._seed()

    def _seed(self) -> None:
        for user_id, name, role in ((DEMO_USER_ID, "Arun", "user"), (DEMO_GUARDIAN_ID, "Priya", "guardian")):
            self._users[user_id] = {"id": user_id, "name": name, "role": role, "phone": None, "created_at": _now()}
        self._guardian_links.append(
            {"guardian_id": DEMO_GUARDIAN_ID, "user_id": DEMO_USER_ID, "relation": "sister", "created_at": _now()}
        )

    # --- users ---

    async def get_user(self, user_id: UUID) -> Row | None:
        return self._users.get(user_id)

    # --- sessions ---

    async def create_session(self, user_id: UUID, device_info: dict[str, Any]) -> Row:
        row = {
            "id": uuid4(), "user_id": user_id, "status": "active", "device_info": device_info,
            "started_at": _now(), "ended_at": None,
        }
        self._sessions[row["id"]] = row
        return row

    async def get_session(self, session_id: UUID) -> Row | None:
        return self._sessions.get(session_id)

    async def get_active_session(self, user_id: UUID) -> Row | None:
        return next(
            (s for s in self._sessions.values() if s["user_id"] == user_id and s["status"] == "active"), None
        )

    async def list_sessions(self, user_id: UUID | None = None, status: str | None = None) -> list[Row]:
        rows = [
            s for s in self._sessions.values()
            if (user_id is None or s["user_id"] == user_id) and (status is None or s["status"] == status)
        ]
        return sorted(rows, key=lambda s: s["started_at"], reverse=True)

    async def end_session(self, session_id: UUID) -> Row | None:
        """Marks the session ended. Ending an ended session changes nothing."""
        row = self._sessions.get(session_id)
        if row is not None and row["status"] == "active":
            row["status"] = "ended"
            row["ended_at"] = _now()
        return row

    # --- guardians ---

    async def get_linked_users(self, guardian_id: UUID) -> list[Row]:
        """The guardian's links: rows with user_id and relation."""
        return [link for link in self._guardian_links if link["guardian_id"] == guardian_id]

    # --- alerts ---

    async def create_alert(self, *, session_id: UUID | None, user_id: UUID, type: str, risk_level: str,
                           title: str, message: str, location: dict[str, Any] | None = None,
                           payload: dict[str, Any] | None = None) -> Row:
        loc = location or {}
        row = {
            "id": uuid4(), "session_id": session_id, "user_id": user_id, "type": type,
            "risk_level": risk_level, "title": title, "message": message, "payload": payload or {},
            "lat": loc.get("lat"), "lng": loc.get("lng"), "accuracy_m": loc.get("accuracy_m"),
            "status": "open", "acknowledged_by": None, "acknowledged_at": None, "created_at": _now(),
        }
        self._alerts[row["id"]] = row
        return row

    async def list_alerts(self, session_id: UUID | None = None, status: str | None = None) -> list[Row]:
        rows = [
            a for a in self._alerts.values()
            if (session_id is None or a["session_id"] == session_id) and (status is None or a["status"] == status)
        ]
        return sorted(rows, key=lambda a: a["created_at"], reverse=True)

    async def get_alert(self, alert_id: UUID) -> Row | None:
        return self._alerts.get(alert_id)

    async def update_alert_status(self, alert_id: UUID, status: str, guardian_id: UUID | None) -> Row | None:
        """Sets the status; the first acknowledgement records who and when. Transition rules
        (contract 7.13) are checked by the caller (BE-10)."""
        row = self._alerts.get(alert_id)
        if row is None:
            return None
        row["status"] = status
        if status != "open" and row["acknowledged_at"] is None:
            row["acknowledged_by"], row["acknowledged_at"] = guardian_id, _now()
        return row

    # --- locations ---

    async def insert_location(self, session_id: UUID, location: dict[str, Any]) -> Row | None:
        """Stores at most one ping per 10 s per session (contract 10); returns None when throttled."""
        now = time.monotonic()
        last = self._last_location_at.get(session_id)
        if last is not None and now - last < THRESHOLDS.live.location_ping_interval_ms / 1000:
            return None
        self._last_location_at[session_id] = now
        row = {
            "session_id": session_id, "lat": location["lat"], "lng": location["lng"],
            "accuracy_m": location.get("accuracy_m"), "heading_deg": location.get("heading_deg"),
            "speed_mps": location.get("speed_mps"), "recorded_at": _now(),
        }
        self._locations.setdefault(session_id, deque(maxlen=100)).append(row)
        return row

    # --- lifecycle (no-ops here; SupabaseRepo loads and flushes) ---

    async def start(self) -> None:
        pass

    async def close(self) -> None:
        pass


# --- Supabase (BE-09) ----------------------------------------------------------------------

def to_db(row: Row) -> Row:
    """UUIDs and datetimes as JSON strings, for the Supabase API."""
    return {k: str(v) if isinstance(v, UUID) else v.isoformat() if isinstance(v, datetime) else v
            for k, v in row.items()}


def _uuid(value: Any) -> UUID | None:
    return None if value is None else UUID(str(value))


def _dt(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    text = str(value).replace("Z", "+00:00")
    # Postgres can return 1-6 fractional digits; normalise to 6 for fromisoformat.
    if "." in text:
        head, rest = text.split(".", 1)
        digits = "".join(takewhile(str.isdigit, rest))  # stop at the timezone sign
        tail = rest[len(digits):]
        text = f"{head}.{digits[:6].ljust(6, '0')}{tail}"
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def from_db(row: Row, uuids: tuple[str, ...], datetimes: tuple[str, ...]) -> Row:
    out = dict(row)
    for key in uuids:
        if key in out:
            out[key] = _uuid(out[key])
    for key in datetimes:
        if key in out:
            out[key] = _dt(out[key])
    return out


class SupabaseRepo(InMemoryRepo):
    """Memory stays the working copy; Supabase is the backup. Writes are queued and sent in
    order by one background task (so an alert never reaches the database before its session),
    each in a thread with the client's timeout. A failed write is logged, never raised: the live
    loop and the REST routes keep working while Supabase is down. load() restores users, links,
    active sessions and their open alerts at startup."""

    LOG_EVERY_S = 30.0
    CLOSE_TIMEOUT_S = 5.0

    def __init__(self, client: Any) -> None:
        super().__init__()
        self.client = client
        self._queue: asyncio.Queue[tuple[str, str, Row, Row | None]] = asyncio.Queue()
        self._writer: asyncio.Task | None = None
        self._failures = 0
        self._last_failure_log: float | None = None

    # --- lifecycle ---

    async def start(self) -> None:
        await self.load()
        self._writer = asyncio.create_task(self._write_loop(), name="supabase-writer")

    async def close(self) -> None:
        """Gives queued writes a few seconds to finish, then stops the writer."""
        if self._writer is None:
            return
        try:
            await asyncio.wait_for(self._queue.join(), self.CLOSE_TIMEOUT_S)
        except TimeoutError:
            log.warning("Supabase: %d write(s) not saved at shutdown", self._queue.qsize())
        self._writer.cancel()

    async def load(self) -> None:
        try:
            users = await asyncio.to_thread(self.client.select, "app_users")
            links = await asyncio.to_thread(self.client.select, "guardian_links")
            sessions = await asyncio.to_thread(self.client.select, "sessions", eq={"status": "active"})
            ids = [s["id"] for s in sessions]
            alerts = await asyncio.to_thread(self.client.select, "alerts", eq={"status": "open"},
                                             in_={"session_id": ids}) if ids else []
        except Exception as exc:
            log.warning("Supabase: could not load data at startup, using the built-in demo data (%s)",
                        self._safe(exc))
            return
        if users:
            self._users = {u["id"]: u for u in (from_db(r, ("id",), ("created_at",)) for r in users)}
            self._guardian_links = [from_db(r, ("guardian_id", "user_id"), ("created_at",)) for r in links]
        for r in sessions:
            row = from_db(r, ("id", "user_id"), ("started_at", "ended_at"))
            self._sessions[row["id"]] = row
        for r in alerts:
            row = from_db(r, ("id", "session_id", "user_id", "acknowledged_by"), ("acknowledged_at", "created_at"))
            self._alerts[row["id"]] = row
        log.info("Supabase: loaded %d users, %d active sessions, %d open alerts",
                 len(self._users), len(sessions), len(alerts))

    # --- writes: memory first, then queued for Supabase ---

    def _enqueue(self, op: str, table: str, values: Row, eq: Row | None = None) -> None:
        self._queue.put_nowait((op, table, to_db(values), to_db(eq) if eq else None))

    async def _write_loop(self) -> None:
        while True:
            op, table, values, eq = await self._queue.get()
            try:
                if op == "insert":
                    await asyncio.to_thread(self.client.insert, table, values)
                else:
                    await asyncio.to_thread(self.client.update, table, values, eq)
            except Exception as exc:
                self._log_failure(op, table, exc)
            finally:
                self._queue.task_done()

    def _safe(self, exc: BaseException) -> str:
        safe = getattr(self.client, "safe_error", None)
        return safe(exc) if safe else f"{type(exc).__name__}: {exc}"

    def _log_failure(self, op: str, table: str, exc: BaseException) -> None:
        """At most one warning per 30 s, with a count, so an outage does not flood the log."""
        self._failures += 1
        now = time.monotonic()
        if self._last_failure_log is None or now - self._last_failure_log >= self.LOG_EVERY_S:
            log.warning("Supabase: %d write(s) failed since the last report; latest %s %s: %s. "
                        "The app keeps working from memory.", self._failures, op, table, self._safe(exc))
            self._failures = 0
            self._last_failure_log = now

    async def create_session(self, user_id: UUID, device_info: dict[str, Any]) -> Row:
        row = await super().create_session(user_id, device_info)
        self._enqueue("insert", "sessions", row)
        return row

    async def end_session(self, session_id: UUID) -> Row | None:
        before = self._sessions.get(session_id, {}).get("status")
        row = await super().end_session(session_id)
        if row is not None and before == "active":
            self._enqueue("update", "sessions", {"status": "ended", "ended_at": row["ended_at"]}, {"id": session_id})
        return row

    async def create_alert(self, **fields: Any) -> Row:
        row = await super().create_alert(**fields)
        self._enqueue("insert", "alerts", row)
        return row

    async def update_alert_status(self, alert_id: UUID, status: str, guardian_id: UUID | None) -> Row | None:
        row = await super().update_alert_status(alert_id, status, guardian_id)
        if row is not None:
            self._enqueue("update", "alerts", {"status": row["status"], "acknowledged_by": row["acknowledged_by"],
                                               "acknowledged_at": row["acknowledged_at"]}, {"id": alert_id})
        return row

    async def insert_location(self, session_id: UUID, location: dict[str, Any]) -> Row | None:
        row = await super().insert_location(session_id, location)
        if row is not None:
            self._enqueue("insert", "location_pings", row)  # id is an identity column
        return row
