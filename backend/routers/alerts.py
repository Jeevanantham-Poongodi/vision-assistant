# backend/routers/alerts.py
"""Emergency and alert REST, contract 7.11-7.13 (BE-10). Owner: Coder 3.
The logic lives in live/alerts.py, shared with the WebSocket paths."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import AwareDatetime

from auth import Auth, allowed_user_ids, require_guardian, require_user
from config import API_PREFIX
from errors import AppError
from live import alerts
from live.hub import to_alert
from schemas import Alert, AlertList, AlertStatus, AlertType, AlertUpdate, EmergencyRequest

router = APIRouter(prefix=API_PREFIX, tags=["alerts"])


@router.post("/emergency", response_model=Alert, status_code=201,
             responses={404: {"description": "SESSION_NOT_FOUND"}})
async def emergency(body: EmergencyRequest, request: Request, p: Auth) -> Alert:
    """REST fallback for the WebSocket emergency message. Guardians get the alert (with a
    snapshot) and the phone gets emergency_ack. snapshot_b64 is WebSocket-only, so null here."""
    session = await request.app.state.repo.get_session(body.session_id)
    if session is not None:  # unknown sessions get 404 from trigger_emergency
        require_user(p, session["user_id"])
    location = body.location.model_dump(mode="json") if body.location else None
    row = await alerts.trigger_emergency(request.app.state.hub, body.session_id, body.trigger,
                                         location=location, note=body.note)
    return to_alert(row)


@router.get("/alerts", response_model=AlertList)
async def list_alerts(request: Request, p: Auth,
                      session_id: UUID | None = None,
                      user_id: UUID | None = None,
                      type: AlertType | None = None,
                      status: AlertStatus | None = None,
                      limit: Annotated[int, Query(ge=1, le=200)] = 50,
                      before: AwareDatetime | None = None) -> AlertList:
    """Newest first. For the next page pass before=<created_at of the last item>."""
    repo = request.app.state.repo
    allowed = await allowed_user_ids(p, repo)  # None when auth is off
    if allowed is not None and user_id is not None and user_id not in allowed:
        raise AppError("FORBIDDEN", "This token is not allowed to see that user's alerts.")
    rows = await repo.list_alerts(session_id, status, user_id=user_id, type=type, before=before,
                                  limit=limit if allowed is None else None)
    if allowed is not None:  # filter before the limit, so a page is never short
        rows = [r for r in rows if r["user_id"] in allowed][:limit]
    return AlertList(items=[to_alert(r) for r in rows], count=len(rows))


@router.patch("/alerts/{alert_id}", response_model=Alert,
              responses={404: {"description": "ALERT_NOT_FOUND"}, 409: {"description": "INVALID_STATUS_TRANSITION"}})
async def update_alert(alert_id: UUID, body: AlertUpdate, request: Request, p: Auth) -> Alert:
    """Pushes alert_updated to guardians; for an emergency leaving "open", emergency_ack to the phone."""
    require_guardian(p, body.guardian_id)
    row = await alerts.update_alert(request.app.state.hub, alert_id, body.status, body.guardian_id)
    return to_alert(row)
