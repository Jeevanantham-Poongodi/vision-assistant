import pytest

from speech.phrases import (
    build_short_text,
    build_warning_message,
    evasive_advice,
    format_distance,
    motion_direction,
    position_direction,
)


GOLDEN_CASES = [
    (
        {
            "class_name": "car",
            "direction": "right",
            "distance_m": 4.2,
            "motion": "approaching",
        },
        "high",
        "R3",
        "Warning. Car approaching from your right, approximately 4 meters away. "
        "Please move slightly to your left.",
    ),
    (
        {
            "class_name": "motorcycle",
            "direction": "left",
            "distance_m": 2.6,
            "motion": "approaching",
        },
        "critical",
        "R2",
        "Warning. Motorcycle approaching from your left, approximately 2 and a half "
        "meters away. Please move slightly to your right.",
    ),
    (
        {
            "class_name": "chair",
            "direction": "center",
            "distance_m": 0.7,
            "motion": "stationary",
        },
        "critical",
        "R1",
        "Stop. Chair about 70 centimeters directly ahead.",
    ),
    (
        {
            "class_name": "person",
            "direction": "center",
            "distance_m": 2.1,
            "motion": "stationary",
        },
        "medium",
        "R6",
        "Person about 2 meters directly ahead.",
    ),
    (
        {
            "class_name": "person",
            "direction": "slight_left",
            "distance_m": 1.4,
            "motion": "stationary",
        },
        "high",
        "R4",
        "Person about 1 and a half meters slightly to your left.",
    ),
    (
        {
            "class_name": "dog",
            "direction": "right",
            "distance_m": 3.8,
            "motion": "stationary",
        },
        "medium",
        "R5",
        "Dog about 4 meters on your right.",
    ),
    (
        {
            "class_name": "bus",
            "direction": "center",
            "distance_m": 2.8,
            "motion": "approaching",
        },
        "critical",
        "R2",
        "Warning. Bus approaching from ahead, approximately 3 meters away. "
        "Please stop and step aside.",
    ),
]


@pytest.mark.parametrize(
    ("det", "risk_level", "rule_id", "expected"),
    GOLDEN_CASES,
)
def test_warning_messages_match_golden_set(
    det: dict, risk_level: str, rule_id: str, expected: str
) -> None:
    message = build_warning_message(det, risk_level, rule_id)

    assert message == expected
    assert len(message.split()) <= 20


@pytest.mark.parametrize(
    ("distance_m", "expected"),
    [
        (None, None),
        (0.08, "10 centimeters"),
        (0.68, "70 centimeters"),
        (0.7, "70 centimeters"),
        (1.0, "1 meter"),
        (1.4, "1 and a half meters"),
        (1.5, "1 and a half meters"),
        (1.6, "1 and a half meters"),
        (2.0, "2 meters"),
        (2.4, "2 and a half meters"),
        (2.5, "2 and a half meters"),
        (2.6, "2 and a half meters"),
        (2.8, "3 meters"),
        (3.0, "3 meters"),
        (3.8, "4 meters"),
        (4.2, "4 meters"),
    ],
)
def test_format_distance_golden_values(
    distance_m: float | None, expected: str | None
) -> None:
    assert format_distance(distance_m) == expected


@pytest.mark.parametrize(
    ("direction", "expected"),
    [
        ("left", "on your left"),
        ("slight_left", "slightly to your left"),
        ("center", "directly ahead"),
        ("slight_right", "slightly to your right"),
        ("right", "on your right"),
        ("invalid", "ahead"),
    ],
)
def test_position_direction_phrases(direction: str, expected: str) -> None:
    assert position_direction(direction) == expected


@pytest.mark.parametrize(
    ("direction", "expected"),
    [
        ("left", "from your left"),
        ("slight_left", "from your left"),
        ("center", "from ahead"),
        ("slight_right", "from your right"),
        ("right", "from your right"),
        ("invalid", "from ahead"),
    ],
)
def test_motion_direction_phrases(direction: str, expected: str) -> None:
    assert motion_direction(direction) == expected


@pytest.mark.parametrize(
    ("direction", "expected"),
    [
        ("right", "move slightly to your left"),
        ("slight_right", "move slightly to your left"),
        ("left", "move slightly to your right"),
        ("slight_left", "move slightly to your right"),
        ("center", "stop and step aside"),
        ("invalid", "stop and step aside"),
    ],
)
def test_evasive_advice(direction: str, expected: str) -> None:
    assert evasive_advice(direction) == expected


@pytest.mark.parametrize(
    ("rule_id", "risk_level", "expected"),
    [
        ("R3", "high", "Warning. Car approaching from your right. Please move slightly to your left."),
        ("R1", "critical", "Stop. Chair directly ahead."),
        ("R6", "medium", "Person directly ahead."),
    ],
)
def test_warning_without_distance(
    rule_id: str, risk_level: str, expected: str
) -> None:
    message = build_warning_message(
        {"class_name": "car", "direction": "right", "distance_m": None}
        if rule_id == "R3"
        else {"class_name": "chair" if rule_id == "R1" else "person",
              "direction": "center",
              "distance_m": None},
        risk_level,
        rule_id,
    )

    assert message == expected
    assert len(message.split()) <= 20


def test_unknown_rule_with_critical_risk_uses_critical_format() -> None:
    assert build_warning_message(
        {"spoken_name": "traffic light", "direction": "slight_right", "distance_m": 1.0},
        "critical",
        "UNKNOWN",
    ) == "Stop. Traffic light about 1 meter slightly to your right."


def test_build_short_text_uses_contract_debug_format() -> None:
    assert build_short_text(
        {
            "spoken_name": "car",
            "direction": "right",
            "distance_m": 4.2,
            "motion": "approaching",
        }
    ) == "Car · right · 4.2 m · approaching"


@pytest.mark.parametrize(
    "det",
    [
        {},
        {"class_name": None, "direction": None, "distance_m": "near", "motion": []},
        None,
        [],
        {"spoken_name": "a very long malformed name", "direction": "sideways", "distance_m": float("nan")},
    ],
)
def test_malformed_or_missing_detection_data_is_safe(det: dict) -> None:
    message = build_warning_message(det, None, None)
    short_text = build_short_text(det)

    assert isinstance(message, str)
    assert isinstance(short_text, str)
    assert message.endswith(".")
    assert len(message.split()) <= 20


@pytest.mark.parametrize(
    "value", ["near", float("inf"), float("nan"), -1.0, True, 10**1000]
)
def test_invalid_distances_are_unavailable(value: object) -> None:
    assert format_distance(value) is None


def test_english_warning_output_is_unchanged_with_default_language() -> None:
    detection = {"class_name": "car", "direction": "right", "distance_m": 4.2}
    expected = (
        "Warning. Car approaching from your right, approximately 4 meters away. "
        "Please move slightly to your left."
    )

    assert build_warning_message(detection, "high", "R3") == expected
    assert build_warning_message(detection, "high", "R3", lang="en-IN") == expected


@pytest.mark.parametrize(
    ("detection", "risk", "rule", "expected_fragments"),
    [
        (
            {"class_name": "car", "direction": "right", "distance_m": 4.2},
            "high",
            "R3",
            ["எச்சரிக்கை", "கார்", "உங்கள் வலப்புறத்திலிருந்து", "4 மீட்டர்", "இடப்புறமாக"],
        ),
        (
            {"class_name": "chair", "direction": "center", "distance_m": 0.7},
            "critical",
            "R1",
            ["நிற்கவும்", "நாற்காலி", "உங்களுக்கு நேராக", "70 சென்டிமீட்டர்"],
        ),
        (
            {"class_name": "person", "direction": "center", "distance_m": 2.1},
            "medium",
            "R6",
            ["நபர்", "உங்களுக்கு நேராக", "2 மீட்டர்"],
        ),
        (
            {"class_name": "dog", "direction": "right", "distance_m": 3.8},
            "medium",
            "R5",
            ["நாய்", "உங்கள் வலப்புறத்தில்", "4 மீட்டர்"],
        ),
        (
            {"class_name": "person", "direction": "slight_left", "distance_m": 2.0},
            "medium",
            "R6",
            ["நபர்", "இடப்புறத்தில் சற்று விலகி", "2 மீட்டர்"],
        ),
    ],
)
def test_tamil_warning_messages_include_name_direction_and_distance(
    detection: dict, risk: str, rule: str, expected_fragments: list[str]
) -> None:
    message = build_warning_message(detection, risk, rule, lang="ta-IN")

    assert message
    for fragment in expected_fragments:
        assert fragment in message


def test_tamil_critical_message_is_short() -> None:
    message = build_warning_message(
        {"class_name": "chair", "direction": "center", "distance_m": 0.7},
        "critical",
        "R1",
        lang="ta-IN",
    )

    assert len(message) <= 100
    assert message.startswith("நிற்கவும்.")
