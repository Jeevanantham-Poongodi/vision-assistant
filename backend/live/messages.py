# backend/live/messages.py
"""Guardian messages to the phone (BE-11). Owner: Coder 3.
Shared by the guardian WebSocket and POST /sessions/{id}/guardian-message."""
from uuid import UUID, uuid4

from live.hub import SessionHub
from schemas import UserGuardianMessage

SPOKEN_PREFIX = "Your guardian says: "


async def send_guardian_message(hub: SessionHub, session_id: UUID, guardian_id: UUID,
                                text: str) -> tuple[UUID, bool]:
    """Forwards the text to the phone, to be spoken. Returns (message_id, delivered).
    Not delivered (phone offline) means dropped: messages are not queued (contract 7.14)."""
    guardian = await hub.repo.get_user(guardian_id)
    message = UserGuardianMessage(
        message_id=uuid4(), guardian_name=guardian["name"] if guardian else "Your guardian",
        text=text, spoken_text=SPOKEN_PREFIX + text,
    )
    delivered = await hub.send_to_user(session_id, "guardian_message", message.model_dump(mode="json"))
    return message.message_id, delivered
