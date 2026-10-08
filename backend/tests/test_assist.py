"""POST /ask and POST /ocr, contract 7.9-7.10 (BE-12). Coder 4's modules are faked via sys.modules."""
import asyncio
import base64
import copy
import sys
import time
import types
from uuid import UUID

import cv2
import numpy as np
import pytest

import integrations
from db.repo import DEMO_USER_ID
from schemas import AskResponse, OcrResponse
from vision.pipelines import STUB_RESULT

USER = str(DEMO_USER_ID)
UNKNOWN = "99999999-9999-4999-8999-999999999999"


def jpeg(h: int = 48, w: int = 64) -> bytes:
    return cv2.imencode(".jpg", np.full((h, w, 3), 90, np.uint8))[1].tobytes()


def install(monkeypatch, name: str, **functions) -> types.ModuleType:
    module = types.ModuleType(name)
    for fn_name, fn in functions.items():
        setattr(module, fn_name, fn)
    monkeypatch.setitem(sys.modules, name, module)
    return module


@pytest.fixture
def client(make_client):
    return make_client(feature_ask=True, feature_ocr=True, tesseract_cmd=sys.executable)  # "available"


def new_session(client) -> str:
    return client.post("/api/v1/sessions", json={"user_id": USER}).json()["session_id"]


def cache_frame(client, sid: str, age_ms: int = 0) -> bytes:
    """What the socket loop leaves behind after a processed frame (BE-05)."""
    state = client.app.state.hub.state(UUID(sid))
    data = jpeg()
    state.latest_jpeg, state.latest_result = data, copy.deepcopy(STUB_RESULT)
    state.latest_at_ms = int(time.time() * 1000) - age_ms
    return data


def ask(client, sid, question="Is there a vehicle near me?", mode="question", image=None):
    return client.post("/api/v1/ask", json={"session_id": sid, "question": question, "mode": mode, "image": image})


# --- /ask: grounding and the image ---

def test_ask_uses_coder4_style_gemini_with_cached_detections(client, monkeypatch):
    seen = {}

    def answer_question(question, mode="question", detections=None, image_jpeg=None, path_info=None, timeout_s=6.0):
        seen.update(question=question, mode=mode, detections=detections, image=image_jpeg, path_info=path_info)
        return {"answer": "Yes. A car is about 4 meters away on your right.", "source": "gemini", "latency_ms": 900}

    install(monkeypatch, "ai.gemini", answer_question=answer_question)
    sid = new_session(client)
    image = cache_frame(client, sid)
    r = ask(client, sid)
    assert r.status_code == 200
    body = r.json()
    AskResponse.model_validate(body)
    assert (body["answer"], body["spoken_text"], body["source"]) == (
        "Yes. A car is about 4 meters away on your right.", "Yes. A car is about 4 meters away on your right.", "gemini")
    assert body["grounded_on"] == {"frame_id": 1042, "detection_count": 2}
    assert seen["detections"] == STUB_RESULT["detections"] and seen["image"] == image
    assert seen["path_info"] == {"path_clear": False, "clear_distance_m": 2.1}
    assert body["question"] == "Is there a vehicle near me?" and body["mode"] == "question"


def test_ask_accepts_the_contract_shape_async_tuple(client, monkeypatch):
    calls = []

    async def answer_question(question, mode, detections, image_jpeg, timeout_s=6.0):  # contract 8.3
        calls.append(len(detections))
        return "The path ahead appears clear.", "gemini"

    install(monkeypatch, "ai.gemini", answer_question=answer_question)
    sid = new_session(client)
    cache_frame(client, sid)
    body = ask(client, sid, mode="path_check").json()
    assert (body["answer"], body["source"], calls) == ("The path ahead appears clear.", "gemini", [2])


def test_image_in_the_request_is_used_without_a_fresh_frame(client, monkeypatch):
    seen = {}
    install(monkeypatch, "ai.gemini", answer_question=lambda question, mode, detections, image_jpeg, path_info=None:
            seen.update(image=image_jpeg, detections=detections, path_info=path_info) or {"answer": "A wall.", "source": "gemini"})
    sid = new_session(client)
    data = jpeg()
    body = ask(client, sid, image=base64.b64encode(data).decode()).json()
    assert body["answer"] == "A wall."
    assert seen == {"image": data, "detections": [], "path_info": None}     # no stale detections
    assert body["grounded_on"] == {"frame_id": None, "detection_count": 0}


@pytest.mark.parametrize("age_ms", [None, 5000], ids=["never", "stale"])
def test_no_recent_frame(client, age_ms):
    sid = new_session(client)
    if age_ms is not None:
        cache_frame(client, sid, age_ms=age_ms)
    r = ask(client, sid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "NO_RECENT_FRAME"


@pytest.mark.parametrize("image", ["@@not-base64@@", base64.b64encode(b"not an image").decode()],
                         ids=["bad-base64", "not-an-image"])
def test_bad_image_in_the_request(client, image):
    r = ask(client, new_session(client), image=image)
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_FRAME"


def test_unknown_or_ended_session(client):
    assert ask(client, UNKNOWN).status_code == 404
    sid = new_session(client)
    client.post(f"/api/v1/sessions/{sid}/end")
    r = ask(client, sid)
    assert r.status_code == 404 and r.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_ask_switched_off(make_client):
    client = make_client()  # FEATURE_ASK=false
    r = ask(client, new_session(client))
    assert r.status_code == 503 and "FEATURE_ASK" in r.json()["error"]["message"]


# --- /ask: Gemini failures are never HTTP errors ---

def boom(**kwargs):
    raise RuntimeError("quota exceeded")


def hang(**kwargs):
    time.sleep(2)
    return {"answer": "too late", "source": "gemini"}


@pytest.mark.parametrize("fake", [boom, hang, lambda **kw: {"answer": "x", "source": "fallback"}, None],
                         ids=["raises", "hangs", "says-fallback", "missing-module"])
def test_gemini_failures_fall_back(client, monkeypatch, fake):
    monkeypatch.setattr(integrations, "ASK_TIMEOUT_S", 0.3)
    if fake is not None:
        install(monkeypatch, "ai.gemini", answer_question=fake)
    sid = new_session(client)
    cache_frame(client, sid)
    r = ask(client, sid, mode="describe")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "fallback"
    if fake is not None and fake is not boom and fake is not hang:
        assert body["answer"] == "x"  # Coder 4 already produced its own fallback text
    else:
        assert body["answer"] == ("I can see a person directly ahead, about 2 meters away, "
                                  "and a car on your right, about 4 meters away.")


def test_coder4_describe_scene_fallback_is_preferred(client, monkeypatch):
    install(monkeypatch, "speech.phrases",
            describe_scene_fallback=lambda detections, mode="describe", path_clear=True, clear_distance_m=5.0:
            f"Coder 4 fallback: {mode}, {len(detections)} objects, clear={path_clear}.")
    sid = new_session(client)
    cache_frame(client, sid)
    body = ask(client, sid, mode="path_check").json()
    assert body == {**body, "answer": "Coder 4 fallback: path_check, 2 objects, clear=False.", "source": "fallback"}


@pytest.mark.parametrize("mode, path_info, detections, expected", [
    ("path_check", {"path_clear": True, "clear_distance_m": 5.0}, [], "The path ahead appears clear for about 5 meters."),
    ("path_check", {"path_clear": True, "clear_distance_m": None}, [], "The path ahead appears clear."),
    ("path_check", {"path_clear": False, "clear_distance_m": 0.7},
     [{"spoken_name": "chair", "direction": "center", "distance_m": 0.7}],
     "The path is not clear. There is a chair directly ahead, about 70 centimeters away."),
    ("describe", None, [], "I don't see any obstacles nearby."),
])
def test_builtin_fallback(mode, path_info, detections, expected):
    assert integrations.builtin_fallback(detections, mode, path_info) == expected


@pytest.mark.parametrize("distance, spoken", [(0.7, "70 centimeters"), (1.0, "1 meter"), (1.4, "1 and a half meters"),
                                              (2.6, "2 and a half meters"), (2.8, "3 meters"), (3.8, "4 meters"),
                                              (4.2, "4 meters"), (None, "")])
def test_spoken_distance_follows_contract_13_7(distance, spoken):
    assert integrations.spoken_distance(distance) == spoken


# --- /ocr ---

def ocr(client, data: bytes | None = None, **form):
    files = {"image": ("sign.jpg", jpeg() if data is None else data, "image/jpeg")}
    return client.post("/api/v1/ocr", files=files, data={k: str(v).lower() if isinstance(v, bool) else v
                                                         for k, v in form.items()})


CODER4_LINES = {"text": "COMPUTER SCIENCE\nDEPARTMENT", "confidence": 90.5, "latency_ms": 40, "lines": [
    {"text": "COMPUTER  SCIENCE", "confidence": 92.0, "bbox": {"x1": 80, "y1": 120, "x2": 560, "y2": 180}},
    {"text": "DEPARTMENT", "confidence": 89.0, "bbox": {"x1": 150, "y1": 190, "x2": 490, "y2": 240}},
    {"text": "noise", "confidence": 50.0, "bbox": {"x1": 9, "y1": 9, "x2": 1, "y2": 1}},   # invalid box: dropped
]}


def test_ocr_with_interpretation(client, monkeypatch):
    install(monkeypatch, "ai.ocr", read_text=lambda image_bgr: CODER4_LINES)
    seen = {}
    install(monkeypatch, "ai.ocr_interpreter", interpret_ocr=lambda ocr_text, image_jpeg=None, timeout_s=5.0:
            seen.update(text=ocr_text) or {"spoken_text": "The sign says Computer Science Department.",
                                            "source": "gemini", "confidence": 0.8, "latency_ms": 900})
    r = ocr(client)
    assert r.status_code == 200
    body = r.json()
    OcrResponse.model_validate(body)
    assert body["text"] == "COMPUTER SCIENCE\nDEPARTMENT" and seen["text"] == body["text"]
    assert body["lines"] == [
        {"text": "COMPUTER SCIENCE", "confidence": 0.92, "bbox": {"x1": 80, "y1": 120, "x2": 560, "y2": 180}},
        {"text": "DEPARTMENT", "confidence": 0.89, "bbox": {"x1": 150, "y1": 190, "x2": 490, "y2": 240}},
    ]
    assert (body["spoken_text"], body["source"], body["interpreted"]) == (
        "The sign says Computer Science Department.", "tesseract+gemini", True)


def test_ocr_without_interpretation(client, monkeypatch):
    install(monkeypatch, "ai.ocr", read_text=lambda image_bgr: CODER4_LINES)
    install(monkeypatch, "ai.ocr_interpreter", interpret_ocr=lambda **kw: pytest.fail("must not be called"))
    body = ocr(client, interpret=False).json()
    assert (body["spoken_text"], body["source"], body["interpreted"]) == (
        "COMPUTER SCIENCE DEPARTMENT", "tesseract", False)


def test_ocr_when_gemini_is_unavailable(client, monkeypatch):
    install(monkeypatch, "ai.ocr", read_text=lambda image_bgr: CODER4_LINES)
    install(monkeypatch, "ai.ocr_interpreter", interpret_ocr=lambda ocr_text, image_jpeg=None:
            {"spoken_text": ocr_text, "source": "tesseract"})
    body = ocr(client).json()
    assert (body["spoken_text"], body["source"], body["interpreted"]) == (
        "COMPUTER SCIENCE DEPARTMENT", "tesseract", False)


def test_ocr_no_text(client, monkeypatch):
    install(monkeypatch, "ai.ocr", read_text=lambda image_bgr: {"text": "", "lines": [], "confidence": 0.0})
    body = ocr(client).json()
    assert body["text"] == "" and body["lines"] == []
    assert body["spoken_text"] == "I could not find any readable text. Try holding the camera closer and steady."


def test_contract_module_path_is_preferred(client, monkeypatch):
    install(monkeypatch, "ocr.reader", read_text=lambda image_bgr: {"text": "EXIT", "lines": [
        {"text": "EXIT", "confidence": 0.97, "bbox": {"x1": 1, "y1": 1, "x2": 9, "y2": 9}}]})
    install(monkeypatch, "ai.ocr", read_text=lambda image_bgr: pytest.fail("contract path should win"))
    body = ocr(client, interpret=False).json()
    assert body["lines"][0]["confidence"] == 0.97 and body["spoken_text"] == "EXIT"


def test_ocr_unavailable(client, make_client):
    r = ocr(client)                                           # no OCR module at all
    assert r.status_code == 503 and r.json()["error"]["code"] == "MODEL_NOT_READY"
    no_tesseract = make_client(feature_ocr=True, tesseract_cmd="definitely-not-installed")
    assert ocr(no_tesseract).json()["error"]["message"].startswith("OCR is not available: Tesseract")


def test_ocr_switched_off(make_client):
    r = ocr(make_client(tesseract_cmd=sys.executable))
    assert r.status_code == 503 and "FEATURE_OCR" in r.json()["error"]["message"]


def test_ocr_bad_input(client, monkeypatch):
    install(monkeypatch, "ai.ocr", read_text=lambda image_bgr: CODER4_LINES)
    assert ocr(client, b"not an image").json()["error"]["code"] == "INVALID_FRAME"
    assert ocr(client, session_id=UNKNOWN).json()["error"]["code"] == "SESSION_NOT_FOUND"
    assert ocr(client, session_id=new_session(client)).status_code == 200


# --- Settings hand-off and docs ---

def test_export_env_does_not_override(monkeypatch):
    from tests.conftest import make_settings

    monkeypatch.setenv("GEMINI_MODEL", "already-set")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    integrations.export_env(make_settings(gemini_api_key="k-123", gemini_model="from-dotenv"))
    import os
    assert os.environ["GEMINI_API_KEY"] == "k-123" and os.environ["GEMINI_MODEL"] == "already-set"
    monkeypatch.delenv("GEMINI_API_KEY")


def test_call_runs_sync_in_a_thread_and_filters_kwargs():
    def sync_fn(a):
        return a * 2

    async def async_fn(a, b=1):
        return a + b

    assert asyncio.run(integrations.call(sync_fn, 1, a=2, extra="ignored")) == 4
    assert asyncio.run(integrations.call(async_fn, 1, a=2, b=3, extra="ignored")) == 5


def test_routes_are_documented(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/api/v1/ask", "/api/v1/ocr", "/api/v1/guardians/{guardian_id}/users",
            "/api/v1/sessions/{session_id}/guardian-message"} <= set(paths)
