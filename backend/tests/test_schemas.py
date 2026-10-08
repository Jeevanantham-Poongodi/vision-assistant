"""schemas.py must accept the contract's examples (sections 4, 7, 13) and reject bad payloads."""
import copy
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from schemas import (
    Alert,
    AlertUpdate,
    AskRequest,
    AskResponse,
    BBox,
    Detection,
    EmergencyRequest,
    FrameResult,
    GuardianMessageRequest,
    LinkedUserList,
    Location,
    NavigateRequest,
    NavigateResponse,
    OcrResponse,
    Session,
    SessionCreate,
)

USER_ID = "11111111-1111-1111-1111-111111111111"
GUARDIAN_ID = "22222222-2222-2222-2222-222222222222"
SESSION_ID = "5d0e2b7c-8f6a-4f1e-9a43-0c6f6d1b2a10"

# Contract 13.1 payload.
CAR = {
    "track_id": 7, "class_name": "car", "spoken_name": "car", "category": "vehicle",
    "confidence": 0.91, "bbox": {"x1": 520, "y1": 190, "x2": 636, "y2": 300}, "cx_norm": 0.903,
    "direction": "right", "distance_m": 4.2, "distance_zone": "medium", "distance_method": "pinhole",
    "motion": "approaching", "approach_speed_mps": 1.4, "risk_level": "high", "risk_score": 0.86,
}
PERSON = {
    "track_id": 3, "class_name": "person", "spoken_name": "person", "category": "person",
    "confidence": 0.88, "bbox": {"x1": 290, "y1": 60, "x2": 360, "y2": 420}, "cx_norm": 0.508,
    "direction": "center", "distance_m": 2.1, "distance_zone": "medium", "distance_method": "pinhole",
    "motion": "stationary", "approach_speed_mps": 0.0, "risk_level": "medium", "risk_score": 0.52,
}
CAR_WARNING = {
    "warning_id": "6c1f3a8e-6a0b-4a52-9b0e-6a1fd2b7a001", "track_id": 7, "class_name": "car",
    "risk_level": "high", "priority": 80,
    "message": "Warning. Car approaching from your right, approximately 4 meters away. Please move slightly to your left.",
    "short_text": "Car · right · 4.2 m · approaching", "speak": True, "interrupt": False, "rule": "R3",
}
PERSON_WARNING = {
    "warning_id": "6c1f3a8e-6a0b-4a52-9b0e-6a1fd2b7a002", "track_id": 3, "class_name": "person",
    "risk_level": "medium", "priority": 50, "message": "Person about 2 meters directly ahead.",
    "short_text": "Person · ahead · 2.1 m", "speak": True, "interrupt": False, "rule": "R6",
}
VEHICLE_RIGHT = {
    "frame_id": 1042, "frame_size": {"width": 640, "height": 480},
    "ts_captured": 1759900530120, "ts_processed": 1759900530310, "latency_ms": 190, "inference_ms": 74,
    "detections": [CAR, PERSON], "warnings": [CAR_WARNING, PERSON_WARNING],
    "path_clear": False, "clear_distance_m": 2.1, "low_confidence_scene": False,
}
# Contract 13.3.
CLEAR = {
    "frame_id": 1200, "frame_size": {"width": 640, "height": 480},
    "ts_captured": 1759900560000, "ts_processed": 1759900560140, "latency_ms": 140, "inference_ms": 66,
    "detections": [], "warnings": [], "path_clear": True, "clear_distance_m": None, "low_confidence_scene": False,
}
# Contract 4.6.
ALERT = {
    "alert_id": "0b8d6a41-31b0-4d0e-9c8e-6b9c0f3e8f11", "session_id": SESSION_ID, "user_id": USER_ID,
    "type": "emergency", "risk_level": "critical", "title": "Emergency triggered",
    "message": "Arun pressed the emergency button.",
    "location": {"lat": 11.0168, "lng": 76.9558, "accuracy_m": 12.0},
    "snapshot_b64": None, "status": "open", "created_at": "2026-10-08T10:15:30.120Z",
    "acknowledged_by": None, "acknowledged_at": None,
}
# Contract 4.7.
SESSION = {
    "session_id": SESSION_ID, "user_id": USER_ID, "status": "active",
    "started_at": "2026-10-08T10:00:00.000Z", "ended_at": None,
    "device_info": {"user_agent": "Mozilla/5.0 ...", "platform": "android"}, "user_online": True,
    "ws_url": f"/ws/user/{SESSION_ID}", "guardian_ws_url": f"/ws/guardian/{SESSION_ID}",
}


def with_changes(base: dict, **changes) -> dict:
    data = copy.deepcopy(base)
    data.update(changes)
    return data


def without(base: dict, key: str) -> dict:
    data = copy.deepcopy(base)
    del data[key]
    return data


# --- Valid payloads from the contract ---

def test_frame_result_vehicle_right_round_trips():
    result = FrameResult.model_validate(VEHICLE_RIGHT)
    assert result.warnings[0].rule == "R3"
    assert result.model_dump(mode="json") == VEHICLE_RIGHT


def test_frame_result_critical_obstacle():
    chair = with_changes(
        CAR, track_id=12, class_name="chair", spoken_name="chair", category="obstacle", confidence=0.79,
        bbox={"x1": 230, "y1": 210, "x2": 420, "y2": 480}, cx_norm=0.507, direction="center",
        distance_m=0.7, distance_zone="very_close", distance_method="edge_clipped", motion="stationary",
        approach_speed_mps=0.0, risk_level="critical", risk_score=1.0,
    )
    warning = with_changes(
        CAR_WARNING, track_id=12, class_name="chair", risk_level="critical", priority=100,
        message="Stop. Chair about 70 centimeters directly ahead.", short_text="Chair · ahead · 0.7 m",
        interrupt=True, rule="R1",
    )
    result = FrameResult.model_validate(with_changes(VEHICLE_RIGHT, detections=[chair], warnings=[warning]))
    assert result.warnings[0].interrupt is True


def test_frame_result_clear_path():
    assert FrameResult.model_validate(CLEAR).path_clear is True


def test_detection_with_unknown_distance():
    det = Detection.model_validate(with_changes(
        CAR, track_id=None, distance_m=None, distance_zone="unknown", distance_method="none",
        motion="unknown", approach_speed_mps=None, risk_level="low", risk_score=0.2,
    ))
    assert det.distance_m is None


def test_alert_round_trips_with_iso_ms_timestamp():
    alert = Alert.model_validate(ALERT)
    assert alert.created_at == datetime(2026, 10, 8, 10, 15, 30, 120000, tzinfo=timezone.utc)
    assert alert.model_dump(mode="json") == ALERT


def test_session_round_trips():
    assert Session.model_validate(SESSION).model_dump(mode="json") == SESSION


def test_location_heading_and_speed_are_optional():
    loc = Location.model_validate({"lat": 11.0168, "lng": 76.9558, "accuracy_m": 12.0, "ts": 1759900530000})
    assert loc.heading_deg is None and loc.speed_mps is None


@pytest.mark.parametrize("model, payload", [
    (SessionCreate, {"user_id": USER_ID, "device_info": {"user_agent": "Mozilla/5.0", "platform": "android"}}),
    (SessionCreate, {"user_id": USER_ID}),
    (AskRequest, {"session_id": SESSION_ID, "question": "Is there a vehicle near me?", "mode": "question", "image": None}),
    (EmergencyRequest, {"session_id": SESSION_ID, "trigger": "button",
                        "location": {"lat": 11.0168, "lng": 76.9558, "accuracy_m": 12.0}, "note": None}),
    (AlertUpdate, {"status": "acknowledged", "guardian_id": GUARDIAN_ID}),
    (AlertUpdate, {"status": "resolved", "guardian_id": GUARDIAN_ID}),
    (GuardianMessageRequest, {"guardian_id": GUARDIAN_ID, "text": "Stop and wait."}),
    (NavigateRequest, {"session_id": SESSION_ID, "origin": {"lat": 11.0168, "lng": 76.9558},
                       "destination": "Central Library", "profile": "walking"}),
    (NavigateRequest, {"session_id": SESSION_ID, "origin": {"lat": 11.0168, "lng": 76.9558},
                       "destination": {"lat": 11.02, "lng": 76.96}}),
])
def test_valid_request_bodies(model, payload):
    model.model_validate(payload)


def test_ask_response_example():
    AskResponse.model_validate({
        "answer_id": "a3e1c2d4-0000-4000-8000-000000000000", "question": "Is there a vehicle near me?",
        "answer": "Yes. A car is approximately 4 meters away on your right, and it is coming closer.",
        "spoken_text": "Yes. A car is approximately 4 meters away on your right, and it is coming closer.",
        "mode": "question", "source": "gemini", "grounded_on": {"frame_id": 1042, "detection_count": 2},
        "latency_ms": 1850,
    })


def test_ocr_response_example():
    OcrResponse.model_validate({
        "text": "COMPUTER SCIENCE\nDEPARTMENT",
        "lines": [
            {"text": "COMPUTER SCIENCE", "confidence": 0.92, "bbox": {"x1": 80, "y1": 120, "x2": 560, "y2": 180}},
            {"text": "DEPARTMENT", "confidence": 0.89, "bbox": {"x1": 150, "y1": 190, "x2": 490, "y2": 240}},
        ],
        "spoken_text": "The sign says Computer Science Department. There is an arrow pointing left.",
        "interpreted": True, "source": "tesseract+gemini", "latency_ms": 2100,
    })


def test_linked_users_example():
    LinkedUserList.model_validate({"items": [{
        "user_id": USER_ID, "name": "Arun", "relation": "brother", "active_session_id": SESSION_ID,
        "online": True, "last_location": {"lat": 11.0168, "lng": 76.9558, "accuracy_m": 12.0},
    }]})


def test_navigate_response_example():
    NavigateResponse.model_validate({
        "route_id": "0b8d6a41-31b0-4d0e-9c8e-6b9c0f3e8f12", "destination_name": "Central Library",
        "total_distance_m": 240, "duration_s": 190,
        "steps": [{"index": 0, "maneuver": "depart", "distance_m": 20, "instruction": "Head north",
                   "spoken_text": "Start walking straight for about 20 meters.",
                   "location": {"lat": 11.0168, "lng": 76.9558}}],
        "geometry": {"type": "LineString", "coordinates": [[76.9558, 11.0168], [76.9560, 11.0170]]},
    })


# --- Invalid payloads ---

@pytest.mark.parametrize("bad", [
    with_changes(CAR, direction="ahead"),             # not a Direction
    with_changes(CAR, class_name="staircase"),        # not in contract 2.1 (P2 custom class)
    with_changes(CAR, category="building"),
    with_changes(CAR, distance_zone="close"),
    with_changes(CAR, distance_method="lidar"),
    with_changes(CAR, motion="moving"),
    with_changes(CAR, risk_level="severe"),
    with_changes(CAR, confidence=1.5),
    with_changes(CAR, cx_norm=-0.1),
    with_changes(CAR, risk_score=1.01),
    with_changes(CAR, distance_m=-1.0),
    with_changes(CAR, extra_field=1),                  # unknown fields are rejected
    without(CAR, "track_id"),                          # nullable but still required
    without(CAR, "risk_score"),
])
def test_invalid_detection(bad):
    with pytest.raises(ValidationError):
        Detection.model_validate(bad)


@pytest.mark.parametrize("box", [
    {"x1": 600, "y1": 100, "x2": 500, "y2": 200},  # x1 > x2
    {"x1": 100, "y1": 200, "x2": 200, "y2": 200},  # y1 == y2
    {"x1": -5, "y1": 0, "x2": 10, "y2": 10},       # negative pixel
])
def test_invalid_bbox(box):
    with pytest.raises(ValidationError):
        BBox.model_validate(box)


@pytest.mark.parametrize("bad", [
    with_changes(VEHICLE_RIGHT, warnings=[CAR_WARNING, PERSON_WARNING, CAR_WARNING]),  # max 2 (3.2)
    with_changes(VEHICLE_RIGHT, warnings=[with_changes(CAR_WARNING, rule="R8")]),
    with_changes(VEHICLE_RIGHT, warnings=[with_changes(CAR_WARNING, warning_id="9a7e...")]),
    with_changes(VEHICLE_RIGHT, frame_size={"width": 0, "height": 480}),
    without(VEHICLE_RIGHT, "path_clear"),
])
def test_invalid_frame_result(bad):
    with pytest.raises(ValidationError):
        FrameResult.model_validate(bad)


@pytest.mark.parametrize("bad", [
    with_changes(ALERT, type="fire"),
    with_changes(ALERT, status="closed"),
    with_changes(ALERT, user_id="arun"),
    with_changes(ALERT, created_at="2026-10-08T10:15:30"),  # no timezone
    with_changes(ALERT, location={"lat": 91.0, "lng": 76.9558}),
])
def test_invalid_alert(bad):
    with pytest.raises(ValidationError):
        Alert.model_validate(bad)


@pytest.mark.parametrize("model, payload", [
    (SessionCreate, {"user_id": "not-a-uuid"}),
    (SessionCreate, {}),
    (AskRequest, {"session_id": SESSION_ID, "question": "hi", "mode": "chat"}),
    (EmergencyRequest, {"session_id": SESSION_ID, "trigger": "shake"}),
    (AlertUpdate, {"status": "open", "guardian_id": GUARDIAN_ID}),  # open is never a target (7.13)
    (GuardianMessageRequest, {"guardian_id": GUARDIAN_ID, "text": ""}),
    (GuardianMessageRequest, {"guardian_id": GUARDIAN_ID, "text": "x" * 201}),
    (NavigateRequest, {"session_id": SESSION_ID, "origin": {"lat": 11.0, "lng": 76.9},
                       "destination": "Library", "profile": "driving"}),
    (Location, {"lat": 11.0, "lng": 181.0, "ts": 1759900530000}),
    (Location, {"lat": 11.0, "lng": 76.9, "heading_deg": 360.0, "ts": 1759900530000}),
])
def test_invalid_request_bodies(model, payload):
    with pytest.raises(ValidationError):
        model.model_validate(payload)
