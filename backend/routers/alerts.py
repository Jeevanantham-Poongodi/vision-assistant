# backend/routers/alerts.py
"""Emergency and alert REST, contract 7.11-7.13 (BE-10). Owner: Coder 3.
The logic lives in live/alerts.py, shared with the WebSocket paths."""
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import AwareDatetime

from config import API_PREFIX
from live import alerts
from live.hub import to_alert
from schemas import Alert, AlertList, AlertStatus, AlertType, AlertUpdate, EmergencyRequest

router = APIRouter(prefix=API_PREFIX, tags=["alerts"])


@router.post("/emergency", response_model=Alert, status_code=201,
             responses={404: {"description": "SESSION_NOT_FOUND"}})
async def emergency(body: EmergencyRequest, request: Request) -> Alert:
    """REST fallback for the WebSocket emergency message. Guardians get the alert (with a
    snapshot) and the phone gets emergency_ack. snapshot_b64 is WebSocket-only, so null here."""
    location = body.location.model_dump(mode="json") if body.location else None
    row = await alerts.trigger_emergency(request.app.state.hub, body.session_id, body.trigger,
                                         location=location, note=body.note)
    return to_alert(row)


@router.get("/alerts", response_model=AlertList)
async def list_alerts(request: Request,
                      session_id: UUID | None = None,
                      user_id: UUID | None = None,
                      type: AlertType | None = None,
                      status: AlertStatus | None = None,
                      limit: Annotated[int, Query(ge=1, le=200)] = 50,
                      before: AwareDatetime | None = None) -> AlertList:
    """Newest first. For the next page pass before=<created_at of the last item>."""
    rows = await request.app.state.repo.list_alerts(session_id, status, user_id=user_id, type=type,
                                                    before=before, limit=limit)
    return AlertList(items=[to_alert(r) for r in rows], count=len(rows))


@router.patch("/alerts/{alert_id}", response_model=Alert,
              responses={404: {"description": "ALERT_NOT_FOUND"}, 409: {"description": "INVALID_STATUS_TRANSITION"}})
async def update_alert(alert_id: UUID, body: AlertUpdate, request: Request) -> Alert:
    """Pushes alert_updated to guardians; for an emergency leaving "open", emergency_ack to the phone."""
    row = await alerts.update_alert(request.app.state.hub, alert_id, body.status, body.guardian_id)
    return to_alert(row)
