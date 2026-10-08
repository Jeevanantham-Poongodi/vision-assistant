# backend/integrations.py
"""Bridges from the REST routes to Coder 4's Gemini and OCR code (BE-12). Owner: Coder 3.

Contract 8.3 and Coder 4's actual code differ (module paths, sync vs async, tuple vs dict), so
each bridge tries the contract's module first, then Coder 4's, and accepts either shape. When
a module is missing, a built-in fallback keeps /ask answering (it is never an HTTP error)."""
import asyncio
import importlib
import inspect
import logging
import os
from typing import Any

from config import Settings

log = logging.getLogger("vision_assistant")

ASK_TIMEOUT_S = 8.0        # Coder 4 times out Gemini at 6 s; this guards against a hung call
INTERPRET_TIMEOUT_S = 8.0
OCR_TIMEOUT_S = 15.0
ASK_MODULES = ("ai.gemini",)
OCR_MODULES = ("ocr.reader", "ai.ocr")                    # contract 8.3, then Coder 4's
INTERPRET_MODULES = ("ai.gemini", "ai.ocr_interpreter")   # contract 8.3, then Coder 4's
FALLBACK_MODULES = ("speech.phrases",)
NO_TEXT = "I could not find any readable text. Try holding the camera closer and steady."

# Contract 2.3: spoken position per direction.
POSITION = {"left": "on your left", "slight_left": "slightly to your left", "center": "directly ahead",
            "slight_right": "slightly to your right", "right": "on your right"}
CORRIDOR = {"slight_left", "center", "slight_right"}


class ModelNotReady(Exception):
    pass


def export_env(settings: Settings) -> None:
    """Coder 4's code reads os.environ; copy the values from backend/.env once (never logged)."""
    for name, value in (("GEMINI_API_KEY", settings.gemini_api_key), ("GEMINI_MODEL", settings.gemini_model),
                        ("TESSERACT_CMD", settings.tesseract_cmd)):
        if value and not os.environ.get(name):
            os.environ[name] = value


def find(modules: tuple[str, ...], name: str) -> Any:
    for module_name in modules:
        try:
            fn = getattr(importlib.import_module(module_name), name, None)
        except Exception:  # missing module, or one of its own imports is missing
            continue
        if fn is not None:
            return fn
    return None


async def call(fn: Any, timeout_s: float, **kwargs: Any) -> Any:
    """Awaits a coroutine function or runs a sync one in a thread; passes only accepted kwargs."""
    params = inspect.signature(fn).parameters
    if not any(p.kind == p.VAR_KEYWORD for p in params.values()):
        kwargs = {k: v for k, v in kwargs.items() if k in params}
    if inspect.iscoroutinefunction(fn):
        return await asyncio.wait_for(fn(**kwargs), timeout_s)
    return await asyncio.wait_for(asyncio.to_thread(fn, **kwargs), timeout_s)


# --- Ask (contract 7.9) ---

def spoken_distance(distance_m: float | None) -> str:
    """Contract 13.7 rounding: < 1 m in 10 cm steps, 1-3 m to the half meter, else whole meters."""
    if distance_m is None:
        return ""
    if distance_m < 1:
        return f"{max(10, round(distance_m * 10) * 10)} centimeters"
    if distance_m < 3:
        halves = round(distance_m * 2) / 2
        whole = int(halves)
        if halves == whole:
            return "1 meter" if whole == 1 else f"{whole} meters"
        return f"{whole} and a half meters"
    return f"{round(distance_m)} meters"


def builtin_fallback(detections: list[dict], mode: str, path_info: dict | None) -> str:
    """Template answer from our own detections, used when neither Gemini nor Coder 4's fallback runs."""
    def phrase(d: dict) -> str:
        where = POSITION.get(d.get("direction"), "nearby")
        dist = spoken_distance(d.get("distance_m"))
        return f"a {d.get('spoken_name') or d.get('class_name', 'object')} {where}" + (f", about {dist} away" if dist else "")

    by_distance = sorted(detections, key=lambda d: d.get("distance_m") if d.get("distance_m") is not None else 99)
    if mode == "path_check":
        info = path_info or {}
        if info.get("path_clear", not any(d.get("direction") in CORRIDOR for d in detections)):
            dist = info.get("clear_distance_m")
            return f"The path ahead appears clear for about {spoken_distance(dist)}." if dist else "The path ahead appears clear."
        blocking = [d for d in by_distance if d.get("direction") in CORRIDOR]
        return f"The path is not clear. There is {phrase(blocking[0])}." if blocking else "The path is not clear."
    if not detections:
        return "I don't see any obstacles nearby."
    return "I can see " + ", and ".join(phrase(d) for d in by_distance[:3]) + "."


async def fallback_answer(detections: list[dict], mode: str, path_info: dict | None) -> str:
    fn = find(FALLBACK_MODULES, "describe_scene_fallback")
    if fn is not None:
        info = path_info or {}
        try:
            text = await call(fn, ASK_TIMEOUT_S, detections=detections, mode=mode,
                              path_clear=info.get("path_clear", True),
                              clear_distance_m=info.get("clear_distance_m") or 5.0)
            if isinstance(text, str) and text.strip():
                return text.strip()
        except Exception:
            log.warning("describe_scene_fallback failed; using the built-in answer", exc_info=True)
    return builtin_fallback(detections, mode, path_info)


async def ask(question: str, mode: str, detections: list[dict], image_jpeg: bytes | None,
              path_info: dict | None) -> tuple[str, str]:
    """Returns (answer, source) with source "gemini" or "fallback". Never raises."""
    fn = find(ASK_MODULES, "answer_question")
    if fn is not None:
        try:
            out = await call(fn, ASK_TIMEOUT_S, question=question, mode=mode, detections=detections,
                             image_jpeg=image_jpeg, path_info=path_info)
            answer, source = (out.get("answer"), out.get("source")) if isinstance(out, dict) else \
                (out[0], out[1]) if isinstance(out, (tuple, list)) else (out, "gemini")
            if isinstance(answer, str) and answer.strip():
                return answer.strip(), "gemini" if source == "gemini" else "fallback"
        except Exception as exc:
            log.warning("Ask AI: answer_question failed (%s); using the fallback answer", type(exc).__name__)
    return await fallback_answer(detections, mode, path_info), "fallback"


# --- OCR (contract 7.10) ---

def _normalise_line(line: dict) -> dict | None:
    text = " ".join(str(line.get("text", "")).split())
    bbox = line.get("bbox") or {}
    try:
        x1, y1, x2, y2 = (int(bbox[k]) for k in ("x1", "y1", "x2", "y2"))
        confidence = float(line.get("confidence", 0))
    except (KeyError, TypeError, ValueError):
        return None
    if not text or x1 >= x2 or y1 >= y2:
        return None
    if confidence > 1:  # Coder 4 reports Tesseract's 0-100; the contract wants 0-1
        confidence /= 100
    return {"text": text, "confidence": round(min(max(confidence, 0.0), 1.0), 2),
            "bbox": {"x1": max(0, x1), "y1": max(0, y1), "x2": x2, "y2": y2}}


async def read_text(image_bgr: Any) -> dict:
    """Returns {"text", "lines"} in the contract shape. Raises ModelNotReady without an OCR module."""
    fn = find(OCR_MODULES, "read_text")
    if fn is None:
        raise ModelNotReady("OCR is not available on this server yet.")
    out = await call(fn, OCR_TIMEOUT_S, image_bgr=image_bgr)
    lines = [n for n in (_normalise_line(line) for line in (out or {}).get("lines", [])) if n]
    return {"text": "\n".join(line["text"] for line in lines), "lines": lines}


async def interpret(ocr_text: str, image_jpeg: bytes | None) -> tuple[str, str]:
    """Returns (spoken_text, source) with source "tesseract+gemini" or "tesseract". Never raises."""
    plain = " ".join(ocr_text.split())
    fn = find(INTERPRET_MODULES, "interpret_ocr")
    if fn is not None:
        try:
            out = await call(fn, INTERPRET_TIMEOUT_S, ocr_text=ocr_text, image_jpeg=image_jpeg)
            spoken, source = (out.get("spoken_text"), out.get("source")) if isinstance(out, dict) else \
                (out[0], out[1]) if isinstance(out, (tuple, list)) else (out, "gemini")
            if source == "gemini" and isinstance(spoken, str) and spoken.strip():
                return spoken.strip(), "tesseract+gemini"
        except Exception as exc:
            log.warning("OCR: interpret_ocr failed (%s); reading the text as-is", type(exc).__name__)
    return plain, "tesseract"
