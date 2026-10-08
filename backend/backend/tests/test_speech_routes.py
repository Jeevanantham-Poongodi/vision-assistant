from fastapi.testclient import TestClient

import main
from speech import server_audio


client = TestClient(main.app)


def test_openapi_lists_tts_and_stt_routes() -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert "/api/v1/tts" in paths
    assert "/api/v1/stt" in paths


def test_tts_route_returns_mp3(monkeypatch) -> None:
    monkeypatch.setattr(
        server_audio, "text_to_speech", lambda text, lang: (b"mp3-audio", "audio/mpeg")
    )

    response = client.post(
        "/api/v1/tts", json={"text": "Hello", "lang": "en-IN"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == b"mp3-audio"


def test_tts_route_maps_service_errors(monkeypatch) -> None:
    def fail(text: str, lang: str) -> tuple[bytes, str]:
        raise server_audio.SpeechServiceError("VALIDATION_ERROR", 422, "Text must not be empty.")

    monkeypatch.setattr(server_audio, "text_to_speech", fail)

    response = client.post("/api/v1/tts", json={"text": " "})

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALIDATION_ERROR"


def test_stt_route_passes_upload_to_service(monkeypatch) -> None:
    calls: list[tuple[bytes, str, str]] = []

    def transcribe(
        audio: bytes | None,
        content_type: str,
        lang: str,
    ) -> dict[str, str | float]:
        calls.append((audio or b"", content_type, lang))
        return {"transcript": "Take me to the library", "confidence": 0.0}

    monkeypatch.setattr(server_audio, "speech_to_text", transcribe)

    response = client.post(
        "/api/v1/stt",
        files={"audio": ("speech.webm", b"recorded-audio", "audio/webm")},
        data={"lang": "ta-IN"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "text": "Take me to the library",
        "confidence": 0.0,
    }
    assert calls == [(b"recorded-audio", "audio/webm", "ta-IN")]


def test_stt_route_maps_service_errors(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise server_audio.SpeechServiceError(
            "UNSUPPORTED_AUDIO_FORMAT", 415, "Audio format is not supported."
        )

    monkeypatch.setattr(server_audio, "speech_to_text", fail)

    response = client.post(
        "/api/v1/stt",
        files={"audio": ("speech.bin", b"recorded-audio", "application/octet-stream")},
    )

    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "UNSUPPORTED_AUDIO_FORMAT"
