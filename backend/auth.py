# backend/auth.py
"""Signed demo tokens per role (BE-17, P2). Owner: Coder 3.

Off by default (AUTH_REQUIRED=false): every route behaves exactly as the MVP contract, with raw IDs.
With AUTH_REQUIRED=true, REST needs "Authorization: Bearer <token>" and WebSockets "?token=<token>".
Tokens are HMAC-SHA256 signed with AUTH_SECRET (standard library only) and carry the person's ID,
role and expiry: base64url(json) + "." + base64url(signature).
A user may act only on their own sessions; a guardian only on users linked to them."""
import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Request, WebSocket

from errors import AppError

log = logging.getLogger("vision_assistant")

TOKEN_TTL_S = 12 * 3600
ROLES = ("user", "guardian")


class InvalidToken(Exception):
    pass


@dataclass(frozen=True)
class Principal:
    sub: UUID
    role: str


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(secret: str, body: str) -> str:
    return _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())


def make_token(secret: str, sub: UUID, role: str, ttl_s: int = TOKEN_TTL_S, now: float | None = None) -> tuple[str, int]:
    """Returns (token, expiry as unix seconds)."""
    exp = int((now if now is not None else time.time()) + ttl_s)
    body = _b64(json.dumps({"sub": str(sub), "role": role, "exp": exp}, separators=(",", ":")).encode())
    return f"{body}.{_sign(secret, body)}", exp


def verify_token(secret: str, token: str, now: float | None = None) -> Principal:
    try:
        body, signature = token.split(".")
    except (AttributeError, ValueError) as exc:
        raise InvalidToken("Malformed token.") from exc
    if not hmac.compare_digest(signature, _sign(secret, body)):
        raise InvalidToken("Token signature is not valid.")
    try:
        claims = json.loads(_unb64(body))
        sub, role, exp = UUID(claims["sub"]), claims["role"], int(claims["exp"])
    except (ValueError, KeyError, TypeError) as exc:
        raise InvalidToken("Token payload is not valid.") from exc
    if role not in ROLES:
        raise InvalidToken("Token role is not valid.")
    if exp <= (now if now is not None else time.time()):
        raise InvalidToken("Token has expired.")
    return Principal(sub=sub, role=role)


def resolve_secret(settings: Any) -> str:
    if settings.auth_secret:
        return settings.auth_secret
    if settings.auth_required:
        log.warning("AUTH_REQUIRED=true but AUTH_SECRET is empty: using a random secret, "
                    "so tokens stop working when the backend restarts")
    return secrets.token_urlsafe(32)


# --- REST ---

def get_principal(request: Request) -> Principal | None:
    """None when AUTH_REQUIRED=false (everything allowed, as in the MVP contract)."""
    if not request.app.state.settings.auth_required:
        return None
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AppError("UNAUTHORIZED", "Send Authorization: Bearer <token> (POST /api/v1/auth/demo-token).")
    try:
        return verify_token(request.app.state.auth_secret, token.strip())
    except InvalidToken as exc:
        raise AppError("UNAUTHORIZED", str(exc)) from exc


Auth = Annotated[Principal | None, Depends(get_principal)]


def require_user(p: Principal | None, user_id: UUID) -> None:
    """Only that user (their own data)."""
    if p is not None and (p.role != "user" or p.sub != user_id):
        raise AppError("FORBIDDEN", "This token is not allowed to act for that user.")


def require_guardian(p: Principal | None, guardian_id: UUID) -> None:
    """Only that guardian."""
    if p is not None and (p.role != "guardian" or p.sub != guardian_id):
        raise AppError("FORBIDDEN", "This token is not allowed to act for that guardian.")


async def allowed_user_ids(p: Principal | None, repo: Any) -> set[UUID] | None:
    """Users whose data this token may read: itself, or a guardian's linked users. None = all."""
    if p is None:
        return None
    if p.role == "user":
        return {p.sub}
    return {link["user_id"] for link in await repo.get_linked_users(p.sub)}


async def require_session_reader(p: Principal | None, repo: Any, session: dict) -> None:
    """The session's user, or a guardian linked to them."""
    allowed = await allowed_user_ids(p, repo)
    if allowed is not None and session["user_id"] not in allowed:
        raise AppError("FORBIDDEN", "This token is not allowed to see that session.")


# --- WebSockets ---

def socket_principal(ws: WebSocket) -> Principal | None:
    """None when auth is off. Raises InvalidToken for a missing or bad ?token= when it is on."""
    if not ws.app.state.settings.auth_required:
        return None
    token = ws.query_params.get("token")
    if not token:
        raise InvalidToken("Missing ?token=")
    return verify_token(ws.app.state.auth_secret, token)


def socket_allows(ws: WebSocket, role: str, sub: UUID | None) -> bool:
    """True when auth is off, or ?token= is valid and belongs to this role and person."""
    try:
        p = socket_principal(ws)
    except InvalidToken:
        return False
    return p is None or (p.role == role and p.sub == sub)
