# backend/routers/auth.py
"""POST /auth/demo-token (BE-17). Owner: Coder 3.
Demo only: there is no password; anyone can get a token for a seeded user or guardian.
It exists so the frontend can exercise AUTH_REQUIRED=true, not to protect real data."""
from datetime import datetime, timezone

from fastapi import APIRouter, Request

from auth import make_token
from config import API_PREFIX
from errors import AppError
from schemas import DemoTokenRequest, DemoTokenResponse

router = APIRouter(prefix=f"{API_PREFIX}/auth", tags=["auth"])


@router.post("/demo-token", response_model=DemoTokenResponse, responses={404: {"description": "USER_NOT_FOUND"}})
async def demo_token(body: DemoTokenRequest, request: Request) -> DemoTokenResponse:
    """A 12-hour token for that person, with their role (user or guardian) from the database."""
    person = await request.app.state.repo.get_user(body.user_id)
    if person is None:
        raise AppError("USER_NOT_FOUND", f"User {body.user_id} does not exist.")
    token, exp = make_token(request.app.state.auth_secret, body.user_id, person["role"])
    return DemoTokenResponse(token=token, user_id=body.user_id, role=person["role"],
                             expires_at=datetime.fromtimestamp(exp, tz=timezone.utc))
