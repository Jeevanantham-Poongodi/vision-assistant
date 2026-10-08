"""Sentence builders for concise, accessible hazard warnings."""

from __future__ import annotations

import math
from typing import Any


_POSITION_PHRASES: dict[str, str] = {
    "left": "on your left",
    "slight_left": "slightly to your left",
    "center": "directly ahead",
    "slight_right": "slightly to your right",
    "right": "on your right",
}

_MOTION_PHRASES: dict[str, str] = {
    "left": "from your left",
    "slight_left": "from your left",
    "center": "from ahead",
    "slight_right": "from your right",
    "right": "from your right",
}

TAMIL_PHRASES: dict[str, str] = {
    "warning": "எச்சரிக்கை",
    "critical_stop": "நிற்கவும்",
    "object": "ஒரு பொருள்",
    "person": "ஒரு நபர்",
    "car": "கார்",
    "motorcycle": "மோட்டார் சைக்கிள்",
    "bicycle": "மிதிவண்டி",
    "bus": "பேருந்து",
    "truck": "லாரி",
    "chair": "நாற்காலி",
    "bench": "பெஞ்ச்",
    "dog": "நாய்",
    "left": "உங்கள் இடப்புறத்தில்",
    "slight_left": "உங்கள் இடப்புறத்தில் சற்று விலகி",
    "center": "உங்களுக்கு நேராக",
    "slight_right": "உங்கள் வலப்புறத்தில் சற்று விலகி",
    "right": "உங்கள் வலப்புறத்தில்",
    "from_left": "உங்கள் இடப்புறத்திலிருந்து",
    "from_center": "முன்புறத்திலிருந்து",
    "from_right": "உங்கள் வலப்புறத்திலிருந்து",
    "move_left": "சற்று இடப்புறமாக நகருங்கள்",
    "move_right": "சற்று வலப்புறமாக நகருங்கள்",
    "step_aside": "நின்று ஓரமாகச் செல்லுங்கள்",
    "about": "சுமார்",
    "meters": "மீட்டர்",
    "centimeters": "சென்டிமீட்டர்",
    "coming": "வருகிறது",
    "is": "தொலைவில் உள்ளது",
    "are": "தொலைவில் இருக்கிறார்",
}


def _direction(value: object) -> str:
    """Return a normalized known direction, or the safe center default."""
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _POSITION_PHRASES:
            return normalized
    return "unknown"


def position_direction(direction: str) -> str:
    """Return the spoken position phrase for a direction."""
    return _POSITION_PHRASES.get(_direction(direction), "ahead")


def motion_direction(direction: str) -> str:
    """Return the spoken 'from' phrase for a direction."""
    return _MOTION_PHRASES.get(_direction(direction), "from ahead")


def evasive_advice(direction: str) -> str:
    """Return a safe action phrase based on which side the hazard occupies."""
    normalized = _direction(direction)
    if normalized in {"right", "slight_right"}:
        return "move slightly to your left"
    if normalized in {"left", "slight_left"}:
        return "move slightly to your right"
    return "stop and step aside"


def _distance_value(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        distance = float(value)
    except OverflowError:
        return None
    if not math.isfinite(distance) or distance < 0:
        return None
    return distance


def format_distance(distance_m: float | None) -> str | None:
    """Format a distance as a short human-spoken phrase."""
    distance = _distance_value(distance_m)
    if distance is None:
        return None

    if distance < 1.0:
        centimeters = math.floor(distance * 10.0 + 0.5) * 10
        return f"{centimeters} centimeters"
    if distance < 3.0:
        half_meters = math.floor(distance * 2.0 + 0.5) / 2.0
        if half_meters.is_integer():
            unit = "meter" if half_meters == 1 else "meters"
            return f"{int(half_meters)} {unit}"
        return f"{int(half_meters)} and a half meters"

    meters = math.floor(distance + 0.5)
    unit = "meter" if meters == 1 else "meters"
    return f"{meters} {unit}"


def _spoken_name(det: dict[str, Any]) -> str:
    value = det.get("spoken_name")
    if not isinstance(value, str) or not value.strip():
        value = det.get("class_name")
    if not isinstance(value, str) or not value.strip():
        return "Object"

    words = value.replace("_", " ").split()
    if not words:
        return "Object"
    # Contract object names are short; cap malformed input to keep messages concise.
    return " ".join(words[:2]).capitalize()


def _detection(det: dict[str, Any]) -> dict[str, Any]:
    return det if isinstance(det, dict) else {}


def _tamil_name(det: dict[str, Any]) -> str:
    raw_name = det.get("class_name")
    if not isinstance(raw_name, str) or not raw_name.strip():
        raw_name = det.get("spoken_name")
    if isinstance(raw_name, str):
        key = raw_name.strip().lower().replace(" ", "_")
        if key in TAMIL_PHRASES:
            return TAMIL_PHRASES[key]
        alias = {
            "traffic_light": "போக்குவரத்து விளக்கு",
            "stop_sign": "நிறுத்தக் குறி",
            "fire_hydrant": "தீயணைப்பு நீர்க்குழாய்",
            "dining_table": "சாப்பாட்டு மேசை",
            "potted_plant": "தொட்டிச் செடி",
            "backpack": "முதுகுப்பை",
            "suitcase": "சூட்கேஸ்",
            "cow": "மாடு",
            "bottle": "பாட்டில்",
        }
        if key in alias:
            return alias[key]
        words = raw_name.replace("_", " ").split()
        if words:
            return " ".join(words[:2])
    return TAMIL_PHRASES["object"]


def _tamil_distance(distance_m: float | None) -> str | None:
    if distance_m is None:
        return None
    if distance_m < 1.0:
        centimeters = math.floor(distance_m * 10.0 + 0.5) * 10
        return f"{centimeters} {TAMIL_PHRASES['centimeters']}"
    if distance_m < 3.0:
        half_meters = math.floor(distance_m * 2.0 + 0.5) / 2.0
        amount = (
            f"{int(half_meters)}"
            if half_meters.is_integer()
            else f"{int(half_meters)}.5"
        )
    else:
        amount = str(math.floor(distance_m + 0.5))
    return f"{amount} {TAMIL_PHRASES['meters']}"


def _tamil_position(direction: str) -> str:
    return TAMIL_PHRASES.get(direction, TAMIL_PHRASES["center"])


def _build_tamil_warning(
    det: dict[str, Any], normalized_rule: str, normalized_risk: str
) -> str:
    name = _tamil_name(det)
    raw_direction = det.get("direction")
    direction = _direction(raw_direction)
    distance = _tamil_distance(_distance_value(det.get("distance_m")))

    if normalized_rule in {"R2", "R3"}:
        from_direction = (
            TAMIL_PHRASES["from_left"]
            if direction in {"left", "slight_left"}
            else TAMIL_PHRASES["from_right"]
            if direction in {"right", "slight_right"}
            else TAMIL_PHRASES["from_center"]
        )
        advice = (
            TAMIL_PHRASES["move_left"]
            if direction in {"right", "slight_right"}
            else TAMIL_PHRASES["move_right"]
            if direction in {"left", "slight_left"}
            else TAMIL_PHRASES["step_aside"]
        )
        distance_clause = (
            f" {TAMIL_PHRASES['about']} {distance} தொலைவில்" if distance else ""
        )
        return (
            f"{TAMIL_PHRASES['warning']}. {name} {from_direction}"
            f"{distance_clause} {TAMIL_PHRASES['coming']}. தயவுசெய்து {advice}."
        )

    position = _tamil_position(direction)
    distance_clause = f" {TAMIL_PHRASES['about']} {distance}" if distance else ""
    if normalized_rule == "R1" or normalized_risk == "critical":
        if distance:
            return (
                f"{TAMIL_PHRASES['critical_stop']}. {name} {position}"
                f"{distance_clause} தொலைவில் உள்ளது."
            )
        return f"{TAMIL_PHRASES['critical_stop']}. {name} {position}."

    if distance:
        ending = TAMIL_PHRASES["are"] if name == TAMIL_PHRASES["person"] else TAMIL_PHRASES["is"]
        return f"{name} {position}{distance_clause} {ending}."
    return f"{name} {position}."


def build_short_text(det: dict) -> str:
    """Build the compact, non-spoken detection label used by the UI."""
    data = _detection(det)
    name = _spoken_name(data)
    direction = _direction(data.get("direction"))
    direction_short = direction if direction != "unknown" else "ahead"
    distance = _distance_value(data.get("distance_m"))
    distance_text = f"{distance:g} m" if distance is not None else "unknown"
    motion = data.get("motion")
    motion_words = motion.strip().lower().split() if isinstance(motion, str) else []
    motion_text = motion_words[0] if motion_words else "unknown"
    return f"{name} · {direction_short} · {distance_text} · {motion_text}"


def build_warning_message(
    det: dict, risk_level: str, rule_id: str, lang: str = "en-IN"
) -> str:
    """Build a short spoken warning, safely falling back for incomplete detections."""
    data = _detection(det)
    normalized_rule = rule_id.strip().upper() if isinstance(rule_id, str) else ""
    normalized_risk = risk_level.strip().lower() if isinstance(risk_level, str) else ""
    if isinstance(lang, str) and lang.lower().replace("_", "-") == "ta-in":
        return _build_tamil_warning(data, normalized_rule, normalized_risk)

    name = _spoken_name(data)
    direction_value = data.get("direction")
    if not isinstance(direction_value, str):
        direction_value = ""
    direction = _direction(direction_value)
    distance = format_distance(data.get("distance_m"))
    if normalized_rule in {"R2", "R3"}:
        advice = evasive_advice(direction_value)
        distance_clause = f", approximately {distance} away" if distance is not None else ""
        return (
            f"Warning. {name} approaching {motion_direction(direction_value)}"
            f"{distance_clause}. Please {advice}."
        )

    position = position_direction(direction_value)
    if normalized_rule == "R1" or normalized_risk == "critical":
        if distance is not None:
            return f"Stop. {name} about {distance} {position}."
        return f"Stop. {name} {position}."

    if distance is not None:
        return f"{name} about {distance} {position}."
    return f"{name} {position}."


def _fallback_detection(detection: object) -> tuple[str, str, float | None, float, int]:
    if not isinstance(detection, dict):
        return "object", "ahead", None, 0.0, 0

    name_value = detection.get("spoken_name", detection.get("class_name", "object"))
    if not isinstance(name_value, str) or not name_value.strip():
        name_value = "object"
    name = " ".join(name_value.replace("_", " ").split()[:3]).lower() or "object"

    direction_value = detection.get("direction")
    direction = position_direction(direction_value) if isinstance(direction_value, str) else "ahead"
    distance = _distance_value(detection.get("distance_m"))

    confidence_value = detection.get("confidence")
    try:
        confidence = (
            float(confidence_value)
            if isinstance(confidence_value, (int, float))
            and not isinstance(confidence_value, bool)
            else 0.0
        )
    except (OverflowError, ValueError):
        confidence = 0.0
    if not math.isfinite(confidence):
        confidence = 0.0
    return name, direction, distance, confidence, 1 if distance is not None else 0


def _describe_detections(detections: object) -> str:
    if not isinstance(detections, list):
        return "I don't see any obstacles ahead."

    valid = [detection for detection in detections if isinstance(detection, dict)]
    if not valid:
        return "I don't see any obstacles ahead."

    decorated = [_fallback_detection(detection) for detection in valid]
    if any(item[3] > 0 for item in decorated):
        decorated.sort(key=lambda item: (-item[3], item[2] if item[2] is not None else math.inf))
    elif any(item[4] for item in decorated):
        decorated.sort(key=lambda item: item[2] if item[2] is not None else math.inf)

    descriptions: list[str] = []
    for name, direction, distance, _, _ in decorated[:2]:
        distance_text = format_distance(distance)
        if distance_text is not None:
            descriptions.append(f"{name} {distance_text} {direction}")
        else:
            descriptions.append(f"{name} {direction}")

    if len(descriptions) == 1:
        return f"There is a {descriptions[0]}."
    return f"There is a {descriptions[0]} and a {descriptions[1]}."


def describe_scene_fallback(
    detections: list[dict],
    mode: str = "describe",
    path_clear: bool = True,
    clear_distance_m: float = 5.0,
) -> str:
    """Create a short deterministic answer when the vision-language model is unavailable."""
    try:
        normalized_mode = mode.strip().lower() if isinstance(mode, str) else "describe"
        if normalized_mode == "path_check":
            if path_clear is True:
                distance = _distance_value(clear_distance_m)
                meters = int(distance) if distance is not None else 5
                return f"The path ahead appears clear for about {meters} meters."
            if not isinstance(detections, list) or not any(
                isinstance(detection, dict) for detection in detections
            ):
                return "I don't see any obstacles ahead."
            summary = _describe_detections(detections)
            return f"The path ahead is not clear. {summary}"

        return _describe_detections(detections)
    except Exception:
        return "I don't see any obstacles ahead."


if __name__ == "__main__":
    assert format_distance(0.7) == "70 centimeters"
    assert format_distance(1.0) == "1 meter"
    assert format_distance(3.6) == "4 meters"
    assert build_warning_message(
        {"class_name": "car", "direction": "right", "distance_m": 4.2},
        "high",
        "R3",
    ) == (
        "Warning. Car approaching from your right, approximately 4 meters away. "
        "Please move slightly to your left."
    )
    print("Speech phrase self-test passed.")
