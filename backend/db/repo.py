# backend/db/repo.py
"""Data access for users and sessions (contract section 10). Owner: Coder 3.
In-memory for now; BE-09 adds a Supabase version with the same async methods,
so routes never change. Rows are dicts shaped like the 001_init.sql columns."""
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

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
