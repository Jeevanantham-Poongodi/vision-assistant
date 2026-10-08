from __future__ import annotations

import io
import sys
from types import ModuleType
from typing import Any

import pytest

from speech import server_audio


class FakeGTTS:
    calls: list[dict[str, str]] = []
    failure: Exception | None = None

    def __init__(self, *, text: str, lang: str) -> None:
        self.calls.append({"text": text, "lang": lang})
        if self.failure:
            raise self.failure

    def write_to_fp(self, output: io.BytesIO) -> None:
        output.write(b"fake-mp3")


@pytest.fixture(autouse=True)
def reset_gtts(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeGTTS.calls = []
    FakeGTTS.failure = None
    gtts = ModuleType("gtts")
    gtts.gTTS = FakeGTTS
    language_module = ModuleType("gtts.lang")
    language_module.tts_langs = lambda: {"en": "English", "ta": "Tamil"}
    monkeypatch.setitem(sys.modules, "gtts", gtts)
    monkeypatch.setitem(sys.modules, "gtts.lang", language_module)


@pytest.mark.parametrize(
    ("language", "expected_provider_language"),
    [("en-IN", "en"), ("ta-IN", "ta")],
)
def test_text_to_speech_returns_mp3_bytes(
    language: str, expected_provider_language: str
) -> None:
    data, content_type = server_audio.text_to_speech("Hello", language)

    assert data == b"fake-mp3"
    assert content_type == "audio/mpeg"
    assert FakeGTTS.calls == [{"text": "Hello", "lang": expected_provider_language}]


def test_text_to_speech_rejects_empty_text() -> None:
    with pytest.raises(server_audio.SpeechServiceError) as error:
        server_audio.text_to_speech("  ")

    assert error.value.code == "VALIDATION_ERROR"
    assert error.value.status_code == 422


def test_text_to_speech_rejects_invalid_language() -> None:
    with pytest.raises(server_audio.SpeechServiceError) as error:
        server_audio.text_to_speech("Hello", "bad language!")

    assert error.value.code == "VALIDATION_ERROR"


def test_text_to_speech_rejects_well_formed_unsupported_language() -> None:
    with pytest.raises(server_audio.SpeechServiceError) as error:
        server_audio.text_to_speech("Hello", "xx-ZZ")

    assert error.value.code == "VALIDATION_ERROR"
    assert error.value.status_code == 422


def test_text_to_speech_hides_provider_failure() -> None:
    FakeGTTS.failure = RuntimeError("sensitive provider detail")

    with pytest.raises(server_audio.SpeechServiceError) as error:
        server_audio.text_to_speech("Hello")

    assert error.value.code == "SPEECH_PROVIDER_ERROR"
    assert "sensitive" not in str(error.value)


def test_speech_to_text_returns_clean_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        server_audio,
        "_transcribe_with_gemini",
        lambda audio, mime, language, timeout: (" Take me  home ", 0.0),
    )

    assert server_audio.speech_to_text(b"audio bytes", "audio/webm;codecs=opus") == {
        "transcript": "Take me home",
        "confidence": 0.0,
    }


def test_speech_to_text_rejects_missing_and_empty_audio() -> None:
    for audio in (None, b""):
        with pytest.raises(server_audio.SpeechServiceError) as error:
            server_audio.speech_to_text(audio)
        assert error.value.code == "VALIDATION_ERROR"


def test_speech_to_text_rejects_unsupported_format() -> None:
    with pytest.raises(server_audio.SpeechServiceError) as error:
        server_audio.speech_to_text(b"data", "application/octet-stream")

    assert error.value.code == "UNSUPPORTED_AUDIO_FORMAT"
    assert error.value.status_code == 415


def test_speech_to_text_rejects_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: Any, **kwargs: Any) -> tuple[str, float]:
        raise TimeoutError("secret details")

    monkeypatch.setattr(server_audio, "_transcribe_with_gemini", fail)
    with pytest.raises(server_audio.SpeechServiceError) as error:
        server_audio.speech_to_text(b"audio")

    assert error.value.code == "SPEECH_PROVIDER_ERROR"
    assert "secret" not in str(error.value)


def test_speech_to_text_rejects_empty_recognition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server_audio, "_transcribe_with_gemini", lambda *args: ("  ", 0.0))

    with pytest.raises(server_audio.SpeechServiceError) as error:
        server_audio.speech_to_text(b"audio")

    assert error.value.code == "TRANSCRIPT_EMPTY"


def test_speech_to_text_requires_gemini_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(server_audio.SpeechServiceError) as error:
        server_audio._transcribe_with_gemini(b"audio", "audio/webm", "en", 1.0)

    assert error.value.code == "SPEECH_PROVIDER_UNAVAILABLE"
