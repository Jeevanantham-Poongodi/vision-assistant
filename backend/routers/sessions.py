# backend/routers/sessions.py
"""Sessions REST, contract 7.4-7.7. Owner: Coder 3."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from auth import Auth, allowed_user_ids, require_guardian, require_session_reader, require_user
from config import API_PREFIX
from db.repo import InMemoryRepo, Row
from errors import AppError
from live.hub import SessionHub
from live.messages import send_guardian_message
from schemas import (
    GuardianMessageRequest,
    GuardianMessageResponse,
    Session,
    SessionCreate,
    SessionList,
    SessionStatus,
)

router = APIRouter(prefix=f"{API_PREFIX}/sessions", tags=["sessions"])


def get_repo(request: Request) -> InMemoryRepo:
    return request.app.state.repo


def get_hub(request: Request) -> SessionHub:
    return request.app.state.hub


Repo = Annotated[InMemoryRepo, Depends(get_repo)]
Hub = Annotated[SessionHub, Depends(get_hub)]


def to_session(row: Row, hub: SessionHub) -> Session:
    """Contract 4.7. user_online comes from the hub, never the database."""
    sid = row["id"]
    return Session(
        session_id=sid,
        user_id=row["user_id"],
        status=row["status"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        device_info=row["device_info"],
        user_online=hub.is_online(sid),
        ws_url=f"/ws/user/{sid}",
        guardian_ws_url=f"/ws/guardian/{sid}",
    )


async def _get_or_404(repo: InMemoryRepo, session_id: UUID) -> Row:
    row = await repo.get_session(session_id)
    if row is None:
        raise AppError("SESSION_NOT_FOUND", f"Session {session_id} does not exist.")
    return row


@router.post("", response_model=Session, status_code=201,
             responses={200: {"model": Session, "description": "The user's existing active session"}})
async def create_session(body: SessionCreate, request: Request, response: Response, repo: Repo, hub: Hub,
                         p: Auth) -> Session:
    require_user(p, body.user_id)
    user = await repo.get_user(body.user_id)
    if user is None:
        raise AppError("USER_NOT_FOUND", f"User {body.user_id} does not exist.")
    if user["role"] != "user":
        raise AppError("USER_NOT_FOUND", f"{body.user_id} is a guardian; only users can start a session.")
    # One lock so two requests at once cannot both create an active session.
    async with request.app.state.session_lock:
        row = await repo.get_active_session(body.user_id)
        if row is not None:
            response.status_code = 200
        else:
            row = await repo.create_session(body.user_id, body.device_info)
    return to_session(row, hub)


@router.get("", response_model=SessionList)
async def list_sessions(repo: Repo, hub: Hub, p: Auth, user_id: UUID | None = None,
                        status: SessionStatus | None = None) -> SessionList:
    allowed = await allowed_user_ids(p, repo)  # None when auth is off
    if allowed is not None and user_id is not None and user_id not in allowed:
        raise AppError("FORBIDDEN", "This token is not allowed to see that user's sessions.")
    rows = await repo.list_sessions(user_id=user_id, status=status)
    if allowed is not None:
        rows = [r for r in rows if r["user_id"] in allowed]
    return SessionList(items=[to_session(r, hub) for r in rows], count=len(rows))


@router.get("/{session_id}", response_model=Session)
async def get_session(session_id: UUID, repo: Repo, hub: Hub, p: Auth) -> Session:
    row = await _get_or_404(repo, session_id)
    await require_session_reader(p, repo, row)  # the user or a linked guardian
    return to_session(row, hub)


@router.post("/{session_id}/end", response_model=Session)
async def end_session(session_id: UUID, repo: Repo, hub: Hub, p: Auth) -> Session:
    """Ending an already-ended session returns it unchanged, so clients can retry."""
    require_user(p, (await _get_or_404(repo, session_id))["user_id"])
    row = await repo.end_session(session_id)
    await hub.close_session(session_id)  # closes sockets with 1000 and drops the pipeline
    return to_session(row, hub)


@router.post("/{session_id}/guardian-message", response_model=GuardianMessageResponse, status_code=202,
             responses={404: {"description": "SESSION_NOT_FOUND"}})
async def guardian_message(session_id: UUID, body: GuardianMessageRequest, repo: Repo,
                           hub: Hub, p: Auth) -> GuardianMessageResponse:
    """REST fallback for the guardian socket's guardian_message (contract 7.14). The phone speaks
    "Your guardian says: ..."; delivered is false if it is offline (nothing is queued). Unknown or
    ended session and unlinked guardian all answer 404, so sessions cannot be probed."""
    require_guardian(p, body.guardian_id)
    session = await repo.get_session(session_id)
    linked = session is not None and any(
        link["user_id"] == session["user_id"] for link in await repo.get_linked_users(body.guardian_id))
    if session is None or session["status"] != "active" or not linked:
        raise AppError("SESSION_NOT_FOUND", f"Session {session_id} does not exist or has ended.")
    message_id, delivered = await send_guardian_message(hub, session_id, body.guardian_id, body.text)
    return GuardianMessageResponse(message_id=message_id, delivered=delivered)
