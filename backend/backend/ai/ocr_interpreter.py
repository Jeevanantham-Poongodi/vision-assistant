"""Turn OCR output into concise, accessible spoken text."""

from __future__ import annotations

import os
import re
import time
from typing import Any

_NO_TEXT_MESSAGE = (
    "I could not find any readable text. Try holding the camera closer and steady."
)

_SYSTEM_INSTRUCTION = """You turn OCR output into concise, natural spoken language.
Preserve the original meaning and names. Correct only obvious OCR typos; never
invent or omit important text. Use at most two short sentences, with no Markdown,
lists, or decorative symbols. Use an attached image only to verify visible text or
describe a clearly visible directional arrow. Never guess what an unclear sign says.
If uncertain, say: I'm not sure. Please ask your guardian to take a look."""


def _clean_ocr_text(ocr_text: object) -> str:
    if not isinstance(ocr_text, str):
        return ""
    lines = [" ".join(line.split()) for line in ocr_text.splitlines()]
    return "\n".join(line for line in lines if line)


def _response_text(response: Any) -> str:
    text = getattr(response, "text", "")
    return text.strip() if isinstance(text, str) else ""


def _generate_interpretation(
    ocr_text: str, image_jpeg: bytes | None, timeout_s: float
) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        http_options=types.HttpOptions(timeout=max(1, int(timeout_s * 1000))),
    )
    try:
        content: list[Any] = [
            "Make this OCR text natural to hear while preserving its meaning:\n"
            f"{ocr_text}"
        ]
        if image_jpeg is not None:
            content.append(types.Part.from_bytes(data=image_jpeg, mime_type="image/jpeg"))
        response = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "").strip() or "gemini-2.0-flash",
            contents=content,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_INSTRUCTION,
                temperature=0.1,
                max_output_tokens=100,
            ),
        )
        return _response_text(response)
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def _valid_spoken_text(text: str) -> bool:
    cleaned = " ".join(text.split())
    if not cleaned or re.search(r"[*#`]", cleaned):
        return False
    return len(re.findall(r"[.!?](?:['\"\])}]*)?(?:\s|$)", cleaned)) <= 2


def interpret_ocr(
    ocr_text: str,
    image_jpeg: bytes | None = None,
    timeout_s: float = 5.0,
) -> dict[str, str | float | int]:
    """Interpret OCR without raising, returning raw text if Gemini is unavailable."""
    started = time.monotonic()
    cleaned_text = _clean_ocr_text(ocr_text)

    def result(
        spoken_text: str, source: str, confidence: float
    ) -> dict[str, str | float | int]:
        return {
            "spoken_text": spoken_text,
            "source": source,
            "confidence": confidence,
            "latency_ms": max(0, int((time.monotonic() - started) * 1000)),
        }

    if not cleaned_text:
        return result(_NO_TEXT_MESSAGE, "fallback", 0.0)

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return result(cleaned_text, "tesseract", 0.0)

    try:
        timeout = (
            max(0.1, min(float(timeout_s), 60.0))
            if isinstance(timeout_s, (int, float)) and not isinstance(timeout_s, bool)
            else 5.0
        )
        image = image_jpeg if isinstance(image_jpeg, bytes) else None
        interpretation = _generate_interpretation(cleaned_text, image, timeout)
        if not _valid_spoken_text(interpretation):
            return result(cleaned_text, "tesseract", 0.0)
        return result(" ".join(interpretation.split()), "gemini", 0.8)
    except Exception:
        return result(cleaned_text, "tesseract", 0.0)


if __name__ == "__main__":
    sample = interpret_ocr("COMPUTER SCIENCE\nDEPARTMENT")
    print(sample["spoken_text"])
