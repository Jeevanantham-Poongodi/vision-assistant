import sys
from types import ModuleType, SimpleNamespace

import numpy as np

from vision.detector import Detector


class FakeModel:
    names = {
        0: "person",
        2: "car",
        9: "traffic light",
        15: "cat",
        60: "dining table",
    }

    def __init__(self):
        self.predict_calls = []
        self.track_calls = []

    def _results(self):
        boxes = SimpleNamespace(
            xyxy=np.array(
                [
                    [1.2, 2.4, 30.6, 40.8],
                    [10, 20, 50, 60],
                    [11, 21, 51, 61],
                    [12, 22, 52, 62],
                    [13, 23, 53, 63],
                ]
            ),
            cls=np.array([0, 9, 60, 15, 2]),
            conf=np.array([0.9, 0.8, 0.7, 0.99, 0.6]),
            id=np.array([1, 2, 3, 4, 5]),
        )
        return [SimpleNamespace(boxes=boxes)]

    def predict(self, frame, **kwargs):
        self.predict_calls.append((frame, kwargs))
        return self._results()

    def track(self, frame, **kwargs):
        self.track_calls.append((frame, kwargs))
        return self._results()


def make_detector(monkeypatch):
    model = FakeModel()
    module = ModuleType("ultralytics")
    module.YOLO = lambda model_path: model
    monkeypatch.setitem(sys.modules, "ultralytics", module)
    detector = Detector()
    return detector, model


def test_detector_warms_once_and_filters_to_contract_classes(monkeypatch):
    detector, model = make_detector(monkeypatch)

    assert len(model.predict_calls) == 1
    warmup_frame, options = model.predict_calls[0]
    assert warmup_frame.shape == (480, 640, 3)
    assert options["conf"] == 0.4

    detections = detector.detect(np.zeros((480, 640, 3), dtype=np.uint8))

    assert [item.class_name for item in detections] == [
        "person",
        "traffic_light",
        "dining_table",
        "car",
    ]
    assert detections[0].bbox == (1, 2, 31, 41)
    assert len(model.predict_calls) == 1


def test_detector_uses_persistent_tracking_and_track_ids(monkeypatch):
    detector, model = make_detector(monkeypatch)

    detections = detector.detect(np.zeros((480, 640, 3), dtype=np.uint8))

    assert [(item.class_name, item.track_id) for item in detections] == [
        ("person", 1),
        ("traffic_light", 2),
        ("dining_table", 3),
        ("car", 5),
    ]
    _, options = model.track_calls[0]
    assert options["persist"] is True
    assert options["tracker"] == "bytetrack.yaml"
    assert options["conf"] == 0.4


def test_detector_can_disable_tracking_and_configure_threshold(monkeypatch):
    model = FakeModel()
    module = ModuleType("ultralytics")
    module.YOLO = lambda model_path: model
    monkeypatch.setitem(sys.modules, "ultralytics", module)
    detector = Detector(conf=0.65, classes=["person"], device="cpu")

    detections = detector.detect(np.zeros((480, 640, 3), dtype=np.uint8), track=False)

    assert [item.class_name for item in detections] == ["person"]
    assert model.predict_calls[-1][1]["conf"] == 0.65
    assert model.predict_calls[-1][1]["classes"] == [0]
    assert model.track_calls == []