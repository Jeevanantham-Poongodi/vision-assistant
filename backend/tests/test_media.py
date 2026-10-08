"""POST /navigate, /tts, /stt, contract 7.16-7.18 (BE-16). Coder 4's modules are faked via sys.modules."""
import sys
import time
import types

import pytest

import integrations
from db.repo import DEMO_USER_ID
from schemas import NavigateResponse

USER = str(DEMO_USER_ID)
UNKNOWN = "99999999-9999-4999-8999-999999999999"

ROUTE = {
    "destination_name": "Central Library", "total_distance_m": 240, "duration_s": 190,
    "steps": [{"index": 0, "maneuver": "depart", "distance_m": 20, "instruction": "Head north",
               "spoken_text": "Start walking straight for about 20 meters.", "location": {"lat": 11.0168, "lng": 76.9558}}],
    "geometry": {"type": "LineString", "coordinates": [[76.9558, 11.0168], [76.956, 11.017]]},
}


class ProviderError(Exception):  # same shape as Coder 4's NavigationError / SpeechServiceError
    def __init__(self, code, status_code, message):
        super().__init__(message)
        self.code, self.status_code = code, status_code


def install(monkeypatch, name, **functions):
    module = types.ModuleType(name)
    for fn_name, fn in functions.items():
        setattr(module, fn_name, fn)
    monkeypatch.setitem(sys.modules, name, module)


@pytest.fixture
def client(make_client):
    return make_client(feature_navigation=True)


def new_session(client) -> str:
    return client.post("/api/v1/sessions", json={"user_id": USER}).json()["session_id"]


def navigate(client, sid, destination="Central Library"):
    return client.post("/api/v1/navigate", json={"session_id": sid, "origin": {"lat": 11.0168, "lng": 76.9558},
                                                 "destination": destination, "profile": "walking"})


def error(r):
    return r.status_code, r.json()["error"]["code"]


# --- /navigate ---

def test_navigate_returns_the_route(client, monkeypatch):
    seen = {}
    install(monkeypatch, "navigation.maps", get_walking_route=lambda origin, destination, timeout_s=8.0:
            seen.update(origin=origin, destination=destination) or dict(ROUTE))
    r = navigate(client, new_session(client))
    assert r.status_code == 200
    body = r.json()
    NavigateResponse.model_validate(body)
    assert body["destination_name"] == "Central Library" and body["route_id"]      # route_id added
    assert body["steps"][0]["spoken_text"] == "Start walking straight for about 20 meters."
    assert seen == {"origin": {"lat": 11.0168, "lng": 76.9558}, "destination": "Central Library"}


def test_navigate_to_coordinates(client, monkeypatch):
    seen = {}
    install(monkeypatch, "navigation.maps", get_walking_route=lambda origin, destination:
            seen.update(destination=destination) or dict(ROUTE))
    assert navigate(client, new_session(client), {"lat": 11.02, "lng": 76.96}).status_code == 200
    assert seen["destination"] == {"lat": 11.02, "lng": 76.96}


@pytest.mark.parametrize("exc, expected", [
    (ProviderError("DESTINATION_NOT_FOUND", 404, "No place called Narnia."), (404, "DESTINATION_NOT_FOUND")),
    (ProviderError("VALIDATION_ERROR", 422, "Destination is invalid."), (422, "VALIDATION_ERROR")),
    (ProviderError("MAPBOX_DOWN", 502, "Mapbox failed."), (503, "MODEL_NOT_READY")),
    (ProviderError("ODD", 400, "Weird input."), (400, "BAD_REQUEST")),
    (RuntimeError("boom"), (503, "MODEL_NOT_READY")),
], ids=["not-found", "validation", "provider-down", "unknown-4xx", "crash"])
def test_navigation_errors_are_mapped(client, monkeypatch, exc, expected):
    def fail(origin, destination):
        raise exc

    install(monkeypatch, "navigation.maps", get_walking_route=fail)
    assert error(navigate(client, new_session(client))) == expected


def test_navigation_timeout(client, monkeypatch):
    monkeypatch.setattr(integrations, "MEDIA_TIMEOUT_S", 0.2)
    install(monkeypatch, "navigation.maps", get_walking_route=lambda origin, destination: time.sleep(1) or ROUTE)
    r = navigate(client, new_session(client))
    assert error(r) == (503, "MODEL_NOT_READY") and "timed out" in r.json()["error"]["message"]


def test_navigation_invalid_route(client, monkeypatch):
    install(monkeypatch, "navigation.maps", get_walking_route=lambda origin, destination: {"steps": "nope"})
    assert error(navigate(client, new_session(client))) == (503, "MODEL_NOT_READY")


def test_navigation_unavailable_switched_off_and_bad_session(client, make_client):
    assert error(navigate(client, new_session(client))) == (503, "MODEL_NOT_READY")   # no module
    assert error(navigate(client, UNKNOWN)) == (404, "SESSION_NOT_FOUND")
    off = make_client()
    r = navigate(off, new_session(off))
    assert error(r) == (503, "MODEL_NOT_READY") and "FEATURE_NAVIGATION" in r.json()["error"]["message"]


# --- /tts ---

def test_tts_returns_audio(client, monkeypatch):
    install(monkeypatch, "speech.server_audio", text_to_speech=lambda text, lang="en-IN": (b"ID3fake-mp3:" + text.encode(), "audio/mpeg"))
    r = client.post("/api/v1/tts", json={"text": "Hello", "lang": "en-IN"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg" and r.content == b"ID3fake-mp3:Hello"


def test_tts_errors(client, monkeypatch):
    assert error(client.post("/api/v1/tts", json={"text": "Hello"})) == (503, "MODEL_NOT_READY")   # no module
    assert client.post("/api/v1/tts", json={"text": ""}).status_code == 422
    assert client.post("/api/v1/tts", json={"text": "x" * 1001}).status_code == 422

    def bad_lang(text, lang):
        raise ProviderError("VALIDATION_ERROR", 422, "Language code is invalid.")

    install(monkeypatch, "speech.server_audio", text_to_speech=bad_lang)
    assert error(client.post("/api/v1/tts", json={"text": "Hi", "lang": "zz"})) == (422, "VALIDATION_ERROR")


# --- /stt ---

def stt(client, data=b"OggS fake audio", content_type="audio/ogg", lang=None):
    form = {"lang": lang} if lang else {}
    return client.post("/api/v1/stt", files={"audio": ("q.ogg", data, content_type)}, data=form)


def test_stt_transcribes(client, monkeypatch):
    seen = {}
    install(monkeypatch, "speech.server_audio", speech_to_text=lambda audio, content_type="audio/webm", lang="en-IN", timeout_s=6.0:
            seen.update(audio=audio, content_type=content_type, lang=lang) or {"text": "what is in front of me", "confidence": 0.88})
    r = stt(client, content_type="audio/webm;codecs=opus", lang="ta-IN")
    assert r.status_code == 200 and r.json() == {"text": "what is in front of me", "confidence": 0.88}
    assert seen == {"audio": b"OggS fake audio", "content_type": "audio/webm", "lang": "ta-IN"}


@pytest.mark.parametrize("data, content_type", [(b"x", "video/mp4"), (b"", "audio/ogg"),
                                                (b"x" * (10 * 1024 * 1024 + 1), "audio/wav")],
                         ids=["wrong-type", "empty", "over-10mb"])
def test_stt_validation(client, monkeypatch, data, content_type):
    install(monkeypatch, "speech.server_audio", speech_to_text=lambda **kw: pytest.fail("must not be called"))
    assert error(stt(client, data, content_type)) == (422, "VALIDATION_ERROR")


def test_stt_unavailable_or_invalid_result(client, monkeypatch):
    assert error(stt(client)) == (503, "MODEL_NOT_READY")                        # no module
    install(monkeypatch, "speech.server_audio", speech_to_text=lambda audio, content_type, lang: {"text": "hi", "confidence": 7})
    assert error(stt(client)) == (503, "MODEL_NOT_READY")                        # confidence out of range


def test_mapbox_token_reaches_coder4(monkeypatch):
    from tests.conftest import make_settings

    monkeypatch.delenv("MAPBOX_TOKEN", raising=False)
    integrations.export_env(make_settings(mapbox_token="pk.test"))
    import os
    assert os.environ["MAPBOX_TOKEN"] == "pk.test"
    monkeypatch.delenv("MAPBOX_TOKEN")


def test_routes_are_documented(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/api/v1/navigate", "/api/v1/tts", "/api/v1/stt"} <= set(paths)
