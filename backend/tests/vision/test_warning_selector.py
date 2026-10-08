from safety.risk_engine import WarningSelector


def make_detection(
    *,
    track_id=1,
    class_name="person",
    direction="center",
    risk_level="high",
    priority=80,
    distance_m=1.5,
    rule="R4",
):
    return {
        "track_id": track_id,
        "class_name": class_name,
        "spoken_name": class_name,
        "direction": direction,
        "risk_level": risk_level,
        "priority": priority,
        "distance_m": distance_m,
        "rule": rule,
    }


def test_warning_selector_high_cooldown_and_escalation():
    selector = WarningSelector()
    detection = make_detection()

    emitted_at = [
        now_ms
        for now_ms in range(0, 10_000, 200)
        if selector.select([detection], now_ms)
    ]
    assert emitted_at == [0, 3000, 6000, 9000]

    critical = make_detection(risk_level="critical", priority=100, distance_m=0.8, rule="R1")
    warnings = selector.select([critical], 10_000)
    assert len(warnings) == 1
    assert warnings[0]["rule"] == "R1"
    assert warnings[0]["interrupt"] is True


def test_warning_selector_skips_low_and_limits_sorted_warnings_to_two():
    selector = WarningSelector()
    detections = [
        make_detection(track_id=1, risk_level="medium", priority=50),
        make_detection(track_id=2, risk_level="critical", priority=100, rule="R1"),
        make_detection(track_id=3, risk_level="high", priority=80),
        make_detection(track_id=4, risk_level="low", priority=20),
    ]

    warnings = selector.select(detections, 0)

    assert [warning["priority"] for warning in warnings] == [100, 80]
    assert [warning["interrupt"] for warning in warnings] == [True, False]
    assert all(warning["speak"] for warning in warnings)


def test_warning_selector_falls_back_to_class_and_direction_key():
    selector = WarningSelector()
    first = make_detection(track_id=None, class_name="chair", priority=50, risk_level="medium")
    same_key = make_detection(track_id=None, class_name="chair", priority=50, risk_level="medium")

    assert len(selector.select([first], 0)) == 1
    assert selector.select([same_key], 5999) == []
    assert len(selector.select([same_key], 6000)) == 1