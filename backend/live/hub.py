# backend/live/hub.py
"""In-memory session hub (BE-03/05/08). Owner: Coder 3.
Per session: the user socket, the guardian connections, the vision pipeline, the latest frame,
location and phone status, and whether the user is online. Guardians get their own send queue,
so a slow or dead guardian can never hold up the user's frame loop."""
import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from fastapi import WebSocket

from config import THRESHOLDS
from schemas import Alert, GeoPoint, UserStatusPayload

log = logging.getLogger("vision_assistant")

_live = THRESHOLDS.live
# Module constants (seconds) so tests can shorten them.
RELAY_INTERVAL_S = _live.relay_interval_ms / 1000
STATUS_INTERVAL_S = _live.user_status_interval_ms / 1000
SILENCE_TIMEOUT_S = _live.silence_timeout_ms / 1000
OFFLINE_ALERT_THROTTLE_S = THRESHOLDS.alerts.offline_alert_throttle_ms / 1000
GUARDIAN_QUEUE_SIZE = _live.guardian_queue_size
GUARDIAN_MAX_DROPS = _live.guardian_max_drops
STATS_WINDOW_S = 5.0


def now_ms() -> int:
    return int(time.time() * 1000)


def envelope(type_: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"v": 1, "type": type_, "ts": now_ms(), "payload": payload}


class GuardianConnection:
    """One guardian socket. post() never waits: messages go through a bounded queue drained by a
    writer task. A guardian that falls GUARDIAN_MAX_DROPS messages behind in a row is closed."""

    def __init__(self, ws: WebSocket, guardian_id: UUID) -> None:
        self.ws = ws
        self.guardian_id = guardian_id
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=GUARDIAN_QUEUE_SIZE)
        self.drops = 0
        self.closed = False
        self._writer = asyncio.create_task(self._write(), name=f"guardian-{guardian_id}")

    def post(self, type_: str, payload: dict[str, Any]) -> bool:
        if self.closed:
            return False
        try:
            self.queue.put_nowait(envelope(type_, payload))
        except asyncio.QueueFull:
            self.drops += 1
            if self.drops >= GUARDIAN_MAX_DROPS:
                log.warning("Guardian %s is not keeping up; closing its socket", self.guardian_id)
                asyncio.create_task(self.close(code=1013))  # 1013 = try again later
            return False
        self.drops = 0
        return True

    async def _write(self) -> None:
        while True:
            message = await self.queue.get()
            try:
                await self.ws.send_json(message)
            except Exception:
                self.closed = True  # the socket is gone; the guardian's receive loop cleans up
                return

    async def close(self, code: int | None = None) -> None:
        """Stops the writer; with a code, also closes the socket."""
        self.closed = True
        self._writer.cancel()
        if code is not None:
            try:
                await self.ws.close(code=code)
            except Exception:
                log.debug("Guardian %s socket was already closed", self.guardian_id, exc_info=True)


@dataclass
class SessionState:
    user_ws: WebSocket | None = None
    guardians: set[Any] = field(default_factory=set)  # GuardianConnection
    # One pipeline per session (vision/pipelines.make_pipeline). A reconnect reuses it, so tracking
    # history survives. Pipelines are not thread-safe: hold pipeline_lock to create or run one.
    pipeline: Any = None
    pipeline_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Latest processed frame, for /ask and /ocr (contract 7.9: must be < 3 s old).
    latest_jpeg: bytes | None = None
    latest_result: dict | None = None
    latest_at_ms: int | None = None
    detect_count: int = 0  # frame_id for POST /detect calls on this session
    # Relayed to guardians (BE-08).
    latest_location: dict | None = None
    client_status: dict[str, Any] = field(default_factory=dict)  # last "status" from the phone
    last_relay_at: float = 0.0  # time.perf_counter() of the last snapshot relay
    recent_results: deque = field(default_factory=lambda: deque(maxlen=100))  # (perf_counter, total_ms)
    # The phone's live connection (user_ws.Connection): sends go through its lock (BE-10).
    user_conn: Any = None
    # Alerts (BE-10).
    hazard_last: dict[str, float] = field(default_factory=dict)  # cooldown key -> time.monotonic()
    last_emergency: tuple[UUID, float] | None = None              # (alert_id, time.monotonic())
    low_conf_since: float | None = None   # BE-14: when low_confidence_scene turned true (monotonic)
    assist_raised: bool = False           # BE-14: one assistance_request per low-confidence period
    last_assist_at: float | None = None   # BE-14: throttle (monotonic)
    # Presence.
    last_seen_ms: int | None = None
    silent: bool = False
    offline_task: asyncio.Task | None = None
    offline_alerted: bool = False      # one system alert per offline period
    last_offline_alert_at: float | None = None  # time.monotonic()


def post_all(state: SessionState, type_: str, payload: dict[str, Any]) -> None:
    for guardian in list(state.guardians):
        guardian.post(type_, payload)


def to_alert(row: dict[str, Any]) -> Alert:
    """Contract 4.6 from an alerts row (001_init.sql)."""
    location = None
    if row["lat"] is not None and row["lng"] is not None:
        location = GeoPoint(lat=row["lat"], lng=row["lng"], accuracy_m=row["accuracy_m"])
    return Alert(
        alert_id=row["id"], session_id=row["session_id"], user_id=row["user_id"], type=row["type"],
        risk_level=row["risk_level"], title=row["title"], message=row["message"], location=location,
        snapshot_b64=None, status=row["status"], created_at=row["created_at"],
        acknowledged_by=row["acknowledged_by"], acknowledged_at=row["acknowledged_at"],
    )


class SessionHub:
    def __init__(self, repo: Any = None) -> None:
        self.repo = repo
        self._sessions: dict[UUID, SessionState] = {}

    def state(self, session_id: UUID) -> SessionState:
        return self._sessions.setdefault(session_id, SessionState())

    def latest_location(self, session_id: UUID) -> dict | None:
        """Read-only: does not create state for a session the hub has not seen."""
        s = self._sessions.get(session_id)
        return s.latest_location if s is not None else None

    def is_online(self, session_id: UUID) -> bool:
        s = self._sessions.get(session_id)
        return s is not None and s.user_ws is not None and not s.silent

    # --- guardians ---

    def broadcast(self, session_id: UUID, type_: str, payload: dict[str, Any]) -> None:
        s = self._sessions.get(session_id)
        if s is not None:
            post_all(s, type_, payload)

    async def send_to_user(self, session_id: UUID, type_: str, payload: dict[str, Any]) -> bool:
        """Sends to the phone through its connection's lock; False if it is offline or the send fails."""
        s = self._sessions.get(session_id)
        conn = s.user_conn if s is not None else None
        if conn is None:
            log.info("Session %s: phone offline, %s not delivered", session_id, type_)
            return False
        try:
            await conn.send(type_, payload)
            return True
        except Exception:
            log.debug("Session %s: could not send %s to the phone", session_id, type_, exc_info=True)
            return False

    def user_status(self, session_id: UUID) -> dict[str, Any]:
        s = self.state(session_id)
        cutoff = time.perf_counter() - STATS_WINDOW_S
        recent = [total for t, total in s.recent_results if t >= cutoff]
        return UserStatusPayload(
            online=self.is_online(session_id),
            fps=round(len(recent) / STATS_WINDOW_S, 1),
            latency_ms=round(sum(recent) / len(recent)) if recent else None,
            battery_pct=s.client_status.get("battery_pct"),
            last_seen=s.last_seen_ms,
        ).model_dump(mode="json")

    def broadcast_status(self, session_id: UUID) -> None:
        self.broadcast(session_id, "user_status", self.user_status(session_id))

    # --- user presence ---

    def _back_online(self, s: SessionState) -> None:
        s.silent = False
        s.offline_alerted = False
        if s.offline_task is not None:
            s.offline_task.cancel()
            s.offline_task = None

    def user_connected(self, session_id: UUID) -> None:
        s = self.state(session_id)
        s.last_seen_ms = now_ms()
        self._back_online(s)
        self.broadcast_status(session_id)

    def mark_seen(self, session_id: UUID) -> None:
        """Every message from the phone counts as a sign of life."""
        s = self._sessions.get(session_id)
        if s is None:
            return
        s.last_seen_ms = now_ms()
        if s.silent:
            self._back_online(s)
            self.broadcast_status(session_id)

    def user_disconnected(self, session_id: UUID, ws: WebSocket) -> None:
        """Offline right away; the system alert only if the phone is not back within the timeout."""
        s = self._sessions.get(session_id)
        if s is None or s.user_ws is not ws:  # ended session, or replaced by a newer connection
            return
        s.user_ws = None
        self.broadcast_status(session_id)
        if s.offline_task is None:
            s.offline_task = asyncio.create_task(self._alert_if_still_offline(session_id, SILENCE_TIMEOUT_S))

    def went_silent(self, session_id: UUID) -> None:
        s = self._sessions.get(session_id)
        if s is None or s.silent:
            return
        s.silent = True
        self.broadcast_status(session_id)
        if s.offline_task is None:
            s.offline_task = asyncio.create_task(self._alert_if_still_offline(session_id, 0))

    async def watch_silence(self, session_id: UUID, ws: WebSocket) -> None:
        """Runs while this socket is the session's user socket; flags it silent after the timeout."""
        tick = min(1.0, SILENCE_TIMEOUT_S / 4)
        while True:
            await asyncio.sleep(tick)
            s = self._sessions.get(session_id)
            if s is None or s.user_ws is not ws:
                return
            if not s.silent and s.last_seen_ms is not None and \
                    now_ms() - s.last_seen_ms > SILENCE_TIMEOUT_S * 1000:
                self.went_silent(session_id)

    async def _alert_if_still_offline(self, session_id: UUID, delay_s: float) -> None:
        try:
            await asyncio.sleep(delay_s)
            if not self.is_online(session_id):
                await self.raise_offline_alert(session_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Could not raise the offline alert for session %s", session_id)
        finally:
            s = self._sessions.get(session_id)
            if s is not None and s.offline_task is asyncio.current_task():
                s.offline_task = None

    async def raise_offline_alert(self, session_id: UUID) -> None:
        s = self._sessions.get(session_id)
        if s is None or s.offline_alerted or self.repo is None:
            return
        if s.last_offline_alert_at is not None and \
                time.monotonic() - s.last_offline_alert_at < OFFLINE_ALERT_THROTTLE_S:
            return
        session = await self.repo.get_session(session_id)
        if session is None or session["status"] != "active":  # ended on purpose: not an emergency
            return
        user = await self.repo.get_user(session["user_id"])
        name = user["name"] if user else "The user"
        row = await self.repo.create_alert(
            session_id=session_id, user_id=session["user_id"], type="system", risk_level="high",
            title="User went offline",
            message=f"{name}'s phone has been disconnected for {SILENCE_TIMEOUT_S:.0f} seconds.",
            location=s.latest_location,
        )
        s.offline_alerted = True
        s.last_offline_alert_at = time.monotonic()
        self.broadcast(session_id, "alert", to_alert(row).model_dump(mode="json"))

    # --- ending ---

    async def close_session(self, session_id: UUID, code: int = 1000) -> None:
        """Closes every socket of the session and drops its state, including the pipeline."""
        s = self._sessions.pop(session_id, None)
        if s is None:
            return
        if s.offline_task is not None:
            s.offline_task.cancel()
        for guardian in list(s.guardians):
            try:
                await guardian.close(code=code)
            except Exception:
                log.debug("Guardian of session %s was already closed", session_id, exc_info=True)
        if s.user_ws is not None:
            try:
                await s.user_ws.close(code=code)
            except Exception:
                # Already closed or broken; it must not stop the others from closing.
                log.debug("User socket for session %s was already closed", session_id, exc_info=True)
