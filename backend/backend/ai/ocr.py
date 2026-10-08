"""Offline OCR extraction using OpenCV preprocessing and Tesseract."""

from __future__ import annotations

import importlib
import math
import os
import re
import sys
import time
from typing import Any


def _empty_result(started_at: float) -> dict[str, Any]:
    return {
        "text": "",
        "lines": [],
        "confidence": 0.0,
        "latency_ms": max(0, int((time.perf_counter() - started_at) * 1000)),
    }


def _clean_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _preprocess(image_bgr: Any, cv2: Any) -> Any:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape[:2]
    if height <= 0 or width <= 0:
        raise ValueError("Image dimensions must be positive")

    if width < 1200:
        scale = min(3.0, max(1.0, 1200.0 / width))
        if scale > 1:
            gray = cv2.resize(
                gray,
                None,
                fx=scale,
                fy=scale,
                interpolation=cv2.INTER_CUBIC,
            )

    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    return cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        11,
    )


def _extract_lines(
    data: dict[str, Any], scale_x: float = 1.0, scale_y: float = 1.0
) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int, int], dict[str, Any]] = {}
    count = len(data.get("text", []))

    for index in range(count):
        text = _clean_text(data["text"][index])
        if not text:
            continue

        try:
            confidence = float(data["conf"][index])
            left = int(data["left"][index])
            top = int(data["top"][index])
            width = int(data["width"][index])
            height = int(data["height"][index])
            line_key = (
                int(data["block_num"][index]),
                int(data["par_num"][index]),
                int(data["line_num"][index]),
            )
        except (KeyError, IndexError, TypeError, ValueError, OverflowError):
            continue

        if confidence < 0 or width <= 0 or height <= 0:
            continue

        line = grouped.setdefault(
            line_key,
            {
                "words": [],
                "confidences": [],
                "x1": left,
                "y1": top,
                "x2": left + width,
                "y2": top + height,
            },
        )
        line["words"].append(text)
        line["confidences"].append(min(100.0, confidence))
        line["x1"] = min(line["x1"], left)
        line["y1"] = min(line["y1"], top)
        line["x2"] = max(line["x2"], left + width)
        line["y2"] = max(line["y2"], top + height)

    lines: list[dict[str, Any]] = []
    for line in grouped.values():
        line_text = " ".join(line["words"]).strip()
        if not line_text:
            continue
        lines.append(
            {
                "text": line_text,
                "confidence": round(
                    sum(line["confidences"]) / len(line["confidences"]), 2
                ),
                "bbox": {
                    "x1": math.floor(line["x1"] / scale_x),
                    "y1": math.floor(line["y1"] / scale_y),
                    "x2": math.ceil(line["x2"] / scale_x),
                    "y2": math.ceil(line["y2"] / scale_y),
                },
            }
        )
    return lines


def read_text(image_bgr: Any) -> dict[str, Any]:
    """Extract cleaned text lines and bounding boxes from a BGR image.

    Missing OCR dependencies, invalid frames, and Tesseract failures produce an
    empty result, keeping optional OCR from disrupting application startup.
    """
    started_at = time.perf_counter()
    if image_bgr is None:
        return _empty_result(started_at)

    try:
        cv2 = importlib.import_module("cv2")
        pytesseract = importlib.import_module("pytesseract")

        configured_command = os.getenv("TESSERACT_CMD", "").strip()
        if configured_command:
            pytesseract.pytesseract.tesseract_cmd = configured_command

        processed = _preprocess(image_bgr, cv2)
        original_height, original_width = image_bgr.shape[:2]
        processed_height, processed_width = processed.shape[:2]
        scale_x = processed_width / original_width
        scale_y = processed_height / original_height
        raw_data = pytesseract.image_to_data(
            processed,
            config="--oem 3 --psm 6",
            output_type=pytesseract.Output.DICT,
        )
        if not isinstance(raw_data, dict):
            return _empty_result(started_at)

        lines = _extract_lines(raw_data, scale_x=scale_x, scale_y=scale_y)
        text = "\n".join(line["text"] for line in lines)
        confidence = (
            round(
                sum(line["confidence"] for line in lines) / len(lines),
                2,
            )
            if lines
            else 0.0
        )
        return {
            "text": text,
            "lines": lines,
            "confidence": confidence,
            "latency_ms": max(0, int((time.perf_counter() - started_at) * 1000)),
        }
    except Exception as exc:
        print(f"OCR unavailable for this frame: {exc}", file=sys.stderr)
        return _empty_result(started_at)


if __name__ == "__main__":
    print("OCR module ready. Pass sample images to ai.ocr_benchmark to validate OCR.")
