# backend/routers/sessions.py
"""Sessions REST, contract 7.4-7.7. Owner: Coder 3."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from config import API_PREFIX
from db.repo import InMemoryRepo, Row
from errors import AppError
from live.hub import SessionHub
from schemas import Session, SessionCreate, SessionList, SessionStatus

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
async def create_session(body: SessionCreate, request: Request, response: Response, repo: Repo, hub: Hub) -> Session:
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
async def list_sessions(repo: Repo, hub: Hub, user_id: UUID | None = None,
                        status: SessionStatus | None = None) -> SessionList:
    rows = await repo.list_sessions(user_id=user_id, status=status)
    return SessionList(items=[to_session(r, hub) for r in rows], count=len(rows))


@router.get("/{session_id}", response_model=Session)
async def get_session(session_id: UUID, repo: Repo, hub: Hub) -> Session:
    return to_session(await _get_or_404(repo, session_id), hub)


@router.post("/{session_id}/end", response_model=Session)
async def end_session(session_id: UUID, repo: Repo, hub: Hub) -> Session:
    """Ending an already-ended session returns it unchanged, so clients can retry."""
    await _get_or_404(repo, session_id)
    row = await repo.end_session(session_id)
    await hub.close_session(session_id)  # closes sockets with 1000 and drops the pipeline
    return to_session(row, hub)
