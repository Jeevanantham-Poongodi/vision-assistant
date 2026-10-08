# backend/vision/pipelines.py
"""Owner: Coder 3 (placed in vision/ by team decision; Coder 2 reviews it).
Not to be confused with Coder 2's vision/pipeline.py, which defines the real VisionPipeline.
This module only picks the pipeline for a session: the contract 13.1 stub or the real one."""
import copy
import json
import time
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from config import OBJECT_CLASSES, THRESHOLDS, Settings
from schemas import FrameResult

FIXTURE = Path(__file__).resolve().parent.parent / "live" / "fixtures" / "frame_result.vehicle_right.json"
STUB_RESULT: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))["payload"]
FrameResult.model_validate(STUB_RESULT)  # a broken fixture fails at import, not on the phone


class Pipeline(Protocol):
    """Contract 8.2: VisionPipeline.process. Synchronous and CPU-bound."""

    def process(self, frame_bgr: np.ndarray, frame_id: int, ts_captured_ms: int) -> dict: ...


class StubPipeline:
    """PIPELINE=stub: the contract 13.1 result with frame_id and timestamps filled in."""

    def process(self, frame_bgr: np.ndarray, frame_id: int, ts_captured_ms: int) -> dict:
        result = copy.deepcopy(STUB_RESULT)
        ts_processed = max(int(time.time() * 1000), ts_captured_ms)
        result.update(frame_id=frame_id, ts_captured=ts_captured_ms, ts_processed=ts_processed,
                      latency_ms=ts_processed - ts_captured_ms)
        return result


def make_pipeline(settings: Settings) -> Pipeline:
    """One per session; call it in a thread (loading YOLO takes a moment)."""
    if settings.pipeline == "stub":
        return StubPipeline()
    from vision.detector import Detector  # Coder 2, contract 8.2
    from vision.pipeline import VisionPipeline

    # One Detector per session: the tracker state lives inside the model object (contract 8.2).
    detector = Detector(model_path=settings.yolo_model, conf=THRESHOLDS.detector_confidence,
                        classes=list(OBJECT_CLASSES))
    return VisionPipeline(focal_px=settings.camera_focal_px, detector=detector)


def make_stateless_pipeline(settings: Settings, detector: Any) -> Pipeline:
    """For POST /detect without a session: a fresh pipeline each call, so motion is always
    "unknown" and there are no cooldowns. It shares the detector loaded at startup."""
    if settings.pipeline == "stub":
        return StubPipeline()
    from vision.pipeline import VisionPipeline

    return VisionPipeline(focal_px=settings.camera_focal_px, detector=detector)
