from __future__ import annotations

from typing import Any

import pytest

from ai import ocr_interpreter


def test_empty_ocr_returns_contract_message_without_gemini(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    result = ocr_interpreter.interpret_ocr(" \n\t ")

    assert result["spoken_text"] == (
        "I could not find any readable text. Try holding the camera closer and steady."
    )
    assert result["source"] == "fallback"
    assert result["confidence"] == 0.0
    assert isinstance(result["latency_ms"], int)


def test_no_key_returns_cleaned_ocr_as_tesseract_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    result = ocr_interpreter.interpret_ocr("  MAIN   STREET \n\n  BUS STOP ")

    assert result["spoken_text"] == "MAIN STREET\nBUS STOP"
    assert result["source"] == "tesseract"
    assert result["confidence"] == 0.0


def test_gemini_interpretation_passes_ocr_image_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    called: dict[str, Any] = {}

    def generate(text: str, image: bytes | None, timeout: float) -> str:
        called.update(text=text, image=image, timeout=timeout)
        return "The sign says Main Street. An arrow points left."

    monkeypatch.setattr(ocr_interpreter, "_generate_interpretation", generate)
    result = ocr_interpreter.interpret_ocr(
        "MAlN STREET", image_jpeg=b"jpeg", timeout_s=3.5
    )

    assert result["spoken_text"] == "The sign says Main Street. An arrow points left."
    assert result["source"] == "gemini"
    assert result["confidence"] == 0.8
    assert called == {"text": "MAlN STREET", "image": b"jpeg", "timeout": 3.5}


def test_gemini_failure_returns_raw_clean_ocr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def fail(*args: Any, **kwargs: Any) -> str:
        raise TimeoutError("request timed out")

    monkeypatch.setattr(ocr_interpreter, "_generate_interpretation", fail)
    result = ocr_interpreter.interpret_ocr("OPEN 24  HOURS")

    assert result["spoken_text"] == "OPEN 24 HOURS"
    assert result["source"] == "tesseract"
    assert result["confidence"] == 0.0


@pytest.mark.parametrize("generated", ["", "**markdown**", "One. Two. Three."])
def test_invalid_gemini_output_uses_tesseract_text(
    monkeypatch: pytest.MonkeyPatch, generated: str
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        ocr_interpreter, "_generate_interpretation", lambda *args: generated
    )

    result = ocr_interpreter.interpret_ocr("EXIT")

    assert result["spoken_text"] == "EXIT"
    assert result["source"] == "tesseract"
