"""Provider-isolated server-side TTS and STT fallback services."""

from __future__ import annotations

import io
import os
import re

_MAX_AUDIO_BYTES = 20 * 1024 * 1024
_SUPPORTED_AUDIO_TYPES = {
    "audio/webm": "audio/webm",
    "audio/ogg": "audio/ogg",
    "audio/wav": "audio/wav",
    "audio/x-wav": "audio/wav",
    "audio/mpeg": "audio/mpeg",
    "audio/mp3": "audio/mpeg",
    "audio/mp4": "audio/mp4",
    "audio/aac": "audio/aac",
    "audio/flac": "audio/flac",
}


class SpeechServiceError(Exception):
    """Safe error for Coder 3 to map into HTTP responses."""

    def __init__(self, code: str, status_code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _normalized_language(lang: str) -> str:
    if not isinstance(lang, str) or not re.fullmatch(
        r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?", lang.strip()
    ):
        raise SpeechServiceError("VALIDATION_ERROR", 422, "Language code is invalid.")
    normalized = lang.strip().lower()
    return normalized.split("-", 1)[0]


def text_to_speech(text: str, lang: str = "en-IN") -> tuple[bytes, str]:
    """Generate MP3 bytes in memory using gTTS, without retaining files."""
    if not isinstance(text, str) or not text.strip():
        raise SpeechServiceError("VALIDATION_ERROR", 422, "Text must not be empty.")
    language = _normalized_language(lang)

    try:
        from gtts import gTTS
        from gtts.lang import tts_langs

        if language not in tts_langs():
            raise SpeechServiceError(
                "VALIDATION_ERROR", 422, "Language is not supported for speech output."
            )
        output = io.BytesIO()
        gTTS(text=text.strip(), lang=language).write_to_fp(output)
        audio = output.getvalue()
        if not audio:
            raise RuntimeError("The speech provider returned no audio")
        return audio, "audio/mpeg"
    except SpeechServiceError:
        raise
    except Exception as exc:
        raise SpeechServiceError(
            "SPEECH_PROVIDER_ERROR", 503, "Speech generation is temporarily unavailable."
        ) from exc


def _transcribe_with_gemini(
    audio: bytes, mime_type: str, language: str, timeout_s: float
) -> tuple[str, float]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise SpeechServiceError(
            "SPEECH_PROVIDER_UNAVAILABLE", 503, "Speech recognition is not configured."
        )

    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=max(1, int(timeout_s * 1000))),
    )
    try:
        response = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "").strip() or "gemini-2.0-flash",
            contents=[
                f"Transcribe the speech in this audio exactly using language {language}. "
                "Return only the transcript.",
                types.Part.from_bytes(data=audio, mime_type=mime_type),
            ],
            config=types.GenerateContentConfig(
                temperature=0,
                max_output_tokens=256,
            ),
        )
        transcript = response.text.strip() if isinstance(response.text, str) else ""
        return transcript, 0.0
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def speech_to_text(
    audio: bytes | None,
    content_type: str = "audio/webm",
    lang: str = "en-IN",
    timeout_s: float = 6.0,
) -> dict[str, str | float]:
    """Transcribe uploaded audio without parsing intents or raising provider errors."""
    if audio is None:
        raise SpeechServiceError("VALIDATION_ERROR", 422, "Audio is required.")
    if not isinstance(audio, bytes) or not audio:
        raise SpeechServiceError("VALIDATION_ERROR", 422, "Audio must not be empty.")
    if len(audio) > _MAX_AUDIO_BYTES:
        raise SpeechServiceError("VALIDATION_ERROR", 422, "Audio file is too large.")

    mime_type = (
        content_type.split(";", 1)[0].strip().lower()
        if isinstance(content_type, str)
        else ""
    )
    mime_type = _SUPPORTED_AUDIO_TYPES.get(mime_type, "")
    if not mime_type:
        raise SpeechServiceError(
            "UNSUPPORTED_AUDIO_FORMAT", 415, "Audio format is not supported."
        )
    language = _normalized_language(lang)

    try:
        timeout = (
            min(60.0, max(0.1, float(timeout_s)))
            if isinstance(timeout_s, (int, float)) and not isinstance(timeout_s, bool)
            else 6.0
        )
        transcript, confidence = _transcribe_with_gemini(
            audio, mime_type, language, timeout
        )
    except SpeechServiceError:
        raise
    except Exception as exc:
        raise SpeechServiceError(
            "SPEECH_PROVIDER_ERROR", 503, "Speech recognition is temporarily unavailable."
        ) from exc

    cleaned = " ".join(transcript.split()) if isinstance(transcript, str) else ""
    if not cleaned:
        raise SpeechServiceError(
            "TRANSCRIPT_EMPTY", 422, "No speech could be recognized in the audio."
        )
    safe_confidence = (
        float(confidence)
        if isinstance(confidence, (int, float))
        and not isinstance(confidence, bool)
        else 0.0
    )
    if not 0.0 <= safe_confidence <= 1.0:
        safe_confidence = 0.0
    return {
        "transcript": cleaned,
        "confidence": safe_confidence,
    }
