# backend/routers/guardians.py
"""GET /guardians/{guardian_id}/users, contract 7.15 (BE-13). Owner: Coder 3.
Links come from the repository; online state and last location from the in-memory hub."""
from uuid import UUID

from fastapi import APIRouter, Request

from config import API_PREFIX
from schemas import GeoPoint, LinkedUser, LinkedUserList

router = APIRouter(prefix=f"{API_PREFIX}/guardians", tags=["guardians"])


@router.get("/{guardian_id}/users", response_model=LinkedUserList)
async def linked_users(guardian_id: UUID, request: Request) -> LinkedUserList:
    """The guardian's linked users with their active session, online state and last location.
    An unknown guardian gets an empty list (not 404), so nobody can probe which IDs exist."""
    repo, hub = request.app.state.repo, request.app.state.hub
    items = []
    for link in await repo.get_linked_users(guardian_id):
        user = await repo.get_user(link["user_id"])
        if user is None:
            continue
        session = await repo.get_active_session(link["user_id"])
        session_id = session["id"] if session else None
        location = hub.latest_location(session_id) if session_id else None
        items.append(LinkedUser(
            user_id=link["user_id"], name=user["name"], relation=link.get("relation"),
            active_session_id=session_id,
            online=hub.is_online(session_id) if session_id else False,
            last_location=GeoPoint(lat=location["lat"], lng=location["lng"],
                                   accuracy_m=location.get("accuracy_m")) if location else None,
        ))
    return LinkedUserList(items=items)
