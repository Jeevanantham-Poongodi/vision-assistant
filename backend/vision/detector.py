from dataclasses import dataclass
import re
from typing import Any

import numpy as np


COCO_CLASSES = frozenset(
    {
        "person",
        "bicycle",
        "car",
        "motorcycle",
        "bus",
        "truck",
        "traffic_light",
        "stop_sign",
        "fire_hydrant",
        "bench",
        "chair",
        "dining_table",
        "potted_plant",
        "backpack",
        "suitcase",
        "dog",
        "cow",
        "bottle",
    }
)


@dataclass
class RawDetection:
    track_id: int | None
    class_name: str
    confidence: float
    bbox: tuple[int, int, int, int]


def _snake_case(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")


def _as_numpy(value: Any) -> np.ndarray:
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    return np.asarray(value)


class Detector:
    """YOLOv8 COCO-subset detector; create one instance per tracking session."""

    def __init__(
        self,
        model_path: str = "yolov8n.pt",
        conf: float = 0.4,
        classes: list[str] | None = None,
        device: str = "cpu",
    ) -> None:
        if not 0.0 <= conf <= 1.0:
            raise ValueError("conf must be between 0.0 and 1.0")

        requested_classes = COCO_CLASSES if classes is None else frozenset(classes)
        unsupported_classes = requested_classes - COCO_CLASSES
        if unsupported_classes:
            raise ValueError(f"Unsupported COCO classes: {sorted(unsupported_classes)}")

        from ultralytics import YOLO

        self.conf = conf
        self.device = device
        self._classes = requested_classes
        self.model = YOLO(model_path)
        self._class_ids = [
            class_id
            for class_id, label in self._model_names().items()
            if _snake_case(label) in self._classes
        ]
        self._predict_options = {
            "conf": self.conf,
            "classes": self._class_ids,
            "device": self.device,
            "verbose": False,
        }

        self.model.predict(
            np.zeros((480, 640, 3), dtype=np.uint8), **self._predict_options
        )

    def _model_names(self) -> dict[int, str]:
        names = self.model.names
        if isinstance(names, dict):
            return {int(class_id): str(label) for class_id, label in names.items()}
        return dict(enumerate(map(str, names)))

    def detect(self, frame_bgr: np.ndarray, track: bool = True) -> list[RawDetection]:
        if frame_bgr.ndim != 3 or frame_bgr.shape[2] != 3:
            raise ValueError("frame_bgr must be a 3-channel image")

        if track:
            results = self.model.track(
                frame_bgr,
                persist=True,
                tracker="bytetrack.yaml",
                **self._predict_options,
            )
        else:
            results = self.model.predict(frame_bgr, **self._predict_options)

        detections: list[RawDetection] = []
        if not results:
            return detections

        boxes = results[0].boxes
        if boxes is None:
            return detections

        coordinates = _as_numpy(boxes.xyxy)
        if len(coordinates) == 0:
            return detections
        class_ids = _as_numpy(boxes.cls).reshape(-1)
        confidences = _as_numpy(boxes.conf).reshape(-1)
        track_ids = None if boxes.id is None else _as_numpy(boxes.id).reshape(-1)
        names = self._model_names()

        for index, (coordinate, class_id, confidence) in enumerate(
            zip(coordinates, class_ids, confidences)
        ):
            label = names.get(int(class_id))
            if label is None:
                continue
            class_name = _snake_case(label)
            if class_name not in self._classes:
                continue
            track_id = None if track_ids is None else int(track_ids[index])
            bbox = tuple(int(round(float(value))) for value in coordinate)
            detections.append(
                RawDetection(
                    track_id=track_id,
                    class_name=class_name,
                    confidence=float(confidence),
                    bbox=bbox,
                )
            )

        return detections