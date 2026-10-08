import pytest

from vision.direction import get_direction
from vision.distance import DistanceSmoother, estimate_distance
from vision.pipeline import _calculate_path_clear
from vision.tracking import MotionTracker


@pytest.mark.parametrize(
    ("cx_norm", "expected"),
    [
        (0.0, "left"),
        (0.199, "left"),
        (0.2, "slight_left"),
        (0.4, "center"),
        (0.5, "center"),
        (0.6, "center"),
        (0.6001, "slight_right"),
        (0.8, "slight_right"),
        (1.0, "right"),
    ],
)
def test_direction_contract_boundaries(cx_norm, expected):
    assert get_direction(cx_norm) == expected


@pytest.mark.parametrize(
    ("distance_m", "expected_zone"),
    [
        (0.9, "very_close"),
        (1.0, "near"),
        (1.9, "near"),
        (2.0, "medium"),
        (4.9, "medium"),
        (5.0, "far"),
    ],
)
def test_distance_zones(distance_m, expected_zone):
    bbox_height = round(1.65 * 100 / distance_m)
    result, zone, method = estimate_distance(
        "person", (0, 20, 100, 20 + bbox_height), 640, 480, 100
    )
    assert result is not None
    assert zone == expected_zone
    assert method == "pinhole"


def test_distance_unknown_class_and_zero_height():
    assert estimate_distance("door", (0, 0, 10, 10), 640, 480, 100) == (
        None,
        "unknown",
        "none",
    )
    assert estimate_distance("person", (0, 10, 10, 10), 640, 480, 100) == (
        None,
        "unknown",
        "none",
    )


def test_distance_pinhole_and_edge_clipping():
    assert estimate_distance("person", (0, 20, 100, 120), 640, 480, 100) == (
        1.6,
        "near",
        "pinhole",
    )
    assert estimate_distance("person", (0, 1, 100, 101), 640, 480, 100)[2] == (
        "edge_clipped"
    )
    assert estimate_distance("person", (0, 100, 100, 480), 640, 480, 500) == (
        0.9,
        "very_close",
        "edge_clipped",
    )


def test_distance_smoothing_is_per_track():
    smoother = DistanceSmoother(alpha=0.4)
    assert smoother.update(1, 2.0) == 2.0
    assert smoother.update(1, 1.0) == 1.6
    assert smoother.update(2, 1.0) == 1.0
    assert smoother.update(None, 3.0) == 3.0


def test_motion_requires_three_points_and_reports_closing_speed_positive():
    tracker = MotionTracker()
    assert tracker.update(1, 5.0, 0) == ("unknown", None)
    assert tracker.update(1, 4.6, 400) == ("unknown", None)
    motion, speed = tracker.update(1, 4.2, 800)
    assert motion == "approaching"
    assert speed == pytest.approx(1.0)


def test_motion_classifies_receding_and_stationary():
    tracker = MotionTracker()
    tracker.update(1, 2.0, 0)
    tracker.update(1, 2.4, 400)
    assert tracker.update(1, 2.8, 800)[0] == "receding"

    tracker.update(2, 3.0, 0)
    tracker.update(2, 3.1, 400)
    assert tracker.update(2, 3.0, 800)[0] == "stationary"


def test_motion_history_window_and_prune():
    tracker = MotionTracker()
    tracker.update(1, 5.0, 0)
    tracker.update(1, 4.0, 1000)
    assert tracker.update(1, 3.0, 2000)[0] == "unknown"

    tracker.prune(5001)
    assert tracker.update(1, 1.0, 5100)[0] == "unknown"


def test_path_clear_uses_only_known_corridor_objects_below_three_meters():
    detections = [
        {"direction": "left", "distance_m": 0.5},
        {"direction": "center", "distance_m": 3.0},
        {"direction": "slight_right", "distance_m": 4.2},
    ]
    assert _calculate_path_clear(detections) == (True, 3.0)

    detections.append({"direction": "slight_left", "distance_m": 2.9})
    assert _calculate_path_clear(detections) == (False, 2.9)


def test_path_clear_empty_corridor_and_unknown_distances():
    assert _calculate_path_clear([{"direction": "right", "distance_m": 0.4}]) == (
        True,
        None,
    )
    assert _calculate_path_clear(
        [{"direction": "center", "distance_m": None}]
    ) == (True, None)