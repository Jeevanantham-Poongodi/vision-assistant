from __future__ import annotations

from typing import Any

import pytest

from ai import gemini, prompts
from speech.phrases import describe_scene_fallback


def test_prompt_contains_grounding_and_mode_rules() -> None:
    prompt = prompts.build_system_prompt("path_check")

    assert "ONLY from the provided structured detections" in prompt
    assert "Never estimate" in prompt
    assert "at most two short sentences" in prompt
    assert "path_clear and clear_distance_m" in prompt
    assert "current mode is: path_check" in prompt


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("question", "question"),
        ("describe", "describe"),
        ("path_check", "path_check"),
        ("unsupported", "question"),
    ],
)
def test_system_prompt_selects_supported_mode(mode: str, expected: str) -> None:
    assert prompts.build_system_prompt(mode).endswith(
        f"The current mode is: {expected}."
    )


def test_describe_fallback_summarizes_top_two_by_confidence() -> None:
    answer = describe_scene_fallback(
        [
            {
                "class_name": "person",
                "direction": "right",
                "distance_m": 2.0,
                "confidence": 0.6,
            },
            {
                "class_name": "chair",
                "direction": "center",
                "distance_m": 1.0,
                "confidence": 0.95,
            },
            {
                "class_name": "dog",
                "direction": "left",
                "distance_m": 0.5,
                "confidence": 0.1,
            },
        ]
    )

    assert answer == "There is a chair 1 meter directly ahead and a person 2 meters on your right."


def test_describe_fallback_uses_nearest_when_confidence_missing() -> None:
    answer = describe_scene_fallback(
        [
            {"class_name": "person", "direction": "right", "distance_m": 2.0},
            {"class_name": "chair", "direction": "center", "distance_m": 0.7},
            {"class_name": "dog", "direction": "left", "distance_m": 4.0},
        ]
    )

    assert answer == "There is a chair 70 centimeters directly ahead and a person 2 meters on your right."


@pytest.mark.parametrize(
    ("detections", "expected"),
    [
        ([], "I don't see any obstacles ahead."),
        ([None, "not a detection"], "I don't see any obstacles ahead."),
    ],
)
def test_empty_or_malformed_fallback_is_safe(
    detections: list[Any], expected: str
) -> None:
    assert describe_scene_fallback(detections) == expected


def test_path_fallback_uses_structured_clearance() -> None:
    assert describe_scene_fallback(
        [], mode="path_check", path_clear=True, clear_distance_m=5.9
    ) == "The path ahead appears clear for about 5 meters."


def test_path_fallback_reports_obstacles_when_not_clear() -> None:
    assert describe_scene_fallback(
        [{"class_name": "chair", "direction": "center", "distance_m": 1.0}],
        mode="path_check",
        path_clear=False,
    ) == "The path ahead is not clear. There is a chair 1 meter directly ahead."


def test_fallback_never_raises_for_malformed_arguments() -> None:
    assert describe_scene_fallback(None, mode=None, path_clear="yes", clear_distance_m=object()) == (
        "I don't see any obstacles ahead."
    )


def test_no_api_key_returns_fallback_without_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(
        gemini,
        "_request_gemini",
        lambda **kwargs: pytest.fail("request must not run without an API key"),
    )

    result = gemini.answer_question(
        "Is there anything nearby?",
        detections=[{"class_name": "person", "direction": "left", "distance_m": 2.0}],
    )

    assert result["source"] == "fallback"
    assert result["answer"] == "There is a person 2 meters on your left."
    assert isinstance(result["latency_ms"], int)


def test_gemini_receives_only_grounding_fields_and_optional_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    captured: dict[str, Any] = {}

    def fake_request(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "A chair is directly ahead."

    monkeypatch.setattr(gemini, "_request_gemini", fake_request)
    result = gemini.answer_question(
        "What is nearby?",
        detections=[
            {
                "class_name": "chair",
                "direction": "center",
                "distance_m": 1.2,
                "confidence": 0.9,
                "bbox": {"x1": 1, "y1": 2},
            }
        ],
        image_jpeg=b"jpeg-bytes",
        path_info={"path_clear": False, "clear_distance_m": 1.5},
    )

    assert result["source"] == "gemini"
    assert result["answer"] == "A chair is directly ahead."
    assert captured["api_key"] == "test-key"
    assert captured["image_jpeg"] == b"jpeg-bytes"
    assert captured["timeout_s"] == 6.0
    assert "bbox" not in captured["user_content"]
    assert '"direction": "center"' in captured["user_content"]
    assert '"path_clear": false' in captured["user_content"]
    assert "current mode is: question" in captured["system_instruction"]


@pytest.mark.parametrize(
    "generated",
    [
        "",
        "First sentence. Second sentence. Third sentence.",
        "**Markdown** response.",
        "This answer is much too long " * 10,
    ],
)
def test_invalid_model_outputs_use_uncertainty_fallback(
    monkeypatch: pytest.MonkeyPatch, generated: str
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(gemini, "_request_gemini", lambda **kwargs: generated)

    result = gemini.answer_question("Question")

    assert result["answer"] == "I'm not sure. Please ask your guardian to take a look."
    assert result["source"] == "fallback"
    assert isinstance(result["latency_ms"], int)


def test_api_failure_returns_deterministic_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def fail_request(**kwargs: Any) -> str:
        raise TimeoutError("request timed out")

    monkeypatch.setattr(gemini, "_request_gemini", fail_request)
    result = gemini.answer_question(
        "Describe the scene",
        mode="describe",
        detections=[{"class_name": "dog", "direction": "left", "distance_m": 3.8}],
    )

    assert result["source"] == "fallback"
    assert result["answer"] == "There is a dog 4 meters on your left."
