# backend/live/frame_worker.py
"""Frame loop for one user connection (BE-05). Owner: Coder 3.
Latest frame wins: one pending slot, one processing task, the pipeline runs in a thread."""
import asyncio
import base64
import binascii
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np
from pydantic import ValidationError

from config import THRESHOLDS, Settings
from live.hub import SessionState
from live.stats import FrameStats
from schemas import Envelope, ErrorCode, FramePayload, FrameResult
from vision.pipelines import make_pipeline

log = logging.getLogger("vision_assistant")

DEBUG_DIR = Path(__file__).resolve().parent.parent / "debug_frames"  # git-ignored
DEBUG_EVERY = 10

SendFn = Callable[[str, dict[str, Any]], Awaitable[None]]
ErrorFn = Callable[[ErrorCode, str, int | None], Awaitable[None]]


def now_ms() -> int:
    return int(time.time() * 1000)


class InvalidFrame(Exception):
    pass


def decode_b64(image_b64: str) -> bytes:
    try:
        data = base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidFrame("Image is not valid base64.") from exc
    if len(data) > THRESHOLDS.frame.max_image_bytes:
        raise InvalidFrame("Image is larger than 5 MB.")
    return data


def decode_jpeg(data: bytes) -> np.ndarray:
    import cv2  # installed by ultralytics (requirements/vision.txt)

    frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise InvalidFrame("Image could not be decoded as JPEG.")
    return frame


@dataclass
class PendingFrame:
    frame_id: int
    ts: int  # envelope ts: the client's capture time
    jpeg: bytes
    received_at: float  # time.perf_counter() on the server (monotonic ticks every ~16 ms on Windows)


class FrameWorker:
    def __init__(self, session_id: UUID, state: SessionState, settings: Settings,
                 send: SendFn, send_error: ErrorFn, hello_ts: int) -> None:
        self.session_id = session_id
        self.state = state
        self.settings = settings
        self.send = send
        self.send_error = send_error
        self.stats = FrameStats(f"session {str(session_id)[:8]}")
        # Smallest (server time - client ts) seen; removes phone/laptop clock skew from the age check.
        self.clock_offset = now_ms() - hello_ts
        self.received = 0
        self._pending: PendingFrame | None = None
        self._wakeup = asyncio.Event()
        self._create_failed_logged = False
        self._background: set[asyncio.Task] = set()  # keeps debug-save tasks alive until done
        self._task = asyncio.create_task(self._run(), name=f"frames-{session_id}")

    # --- receive side (called from the socket loop) ---

    async def submit(self, env: Envelope) -> None:
        received_at = time.perf_counter()
        self.clock_offset = min(self.clock_offset, now_ms() - env.ts)
        raw_id = env.payload.get("frame_id")
        try:
            frame = FramePayload.model_validate(env.payload)
        except ValidationError:
            await self.send_error("INVALID_FRAME", "Frame payload needs frame_id, image, width and height.",
                                  raw_id if isinstance(raw_id, int) else None)
            return
        try:
            jpeg = decode_b64(frame.image)
        except InvalidFrame as exc:
            await self.send_error("INVALID_FRAME", str(exc), frame.frame_id)
            return
        self.received += 1
        if self.settings.debug_save_frames and self.received % DEBUG_EVERY == 0:
            task = asyncio.create_task(asyncio.to_thread(self._save_debug_frame, frame.frame_id, jpeg))
            self._background.add(task)
            task.add_done_callback(self._background.discard)
        if self._pending is not None:
            self.stats.drop("superseded")  # latest frame wins
        self._pending = PendingFrame(frame.frame_id, env.ts, jpeg, received_at)
        self._wakeup.set()

    def _save_debug_frame(self, frame_id: int, jpeg: bytes) -> None:
        folder = DEBUG_DIR / str(self.session_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{frame_id:06d}.jpg").write_bytes(jpeg)

    # --- processing side ---

    async def _run(self) -> None:
        async with self.state.pipeline_lock:  # created on hello (reused on reconnect)
            await self._get_pipeline()
        while True:
            await self._wakeup.wait()
            self._wakeup.clear()
            frame, self._pending = self._pending, None
            if frame is None:
                continue
            try:
                await self._process(frame)
            except asyncio.CancelledError:
                raise
            except Exception:
                # The socket is probably gone; the receive loop will notice and close us.
                log.debug("Could not finish frame %d on session %s", frame.frame_id, self.session_id,
                          exc_info=True)

    async def _process(self, frame: PendingFrame) -> None:
        age_ms = now_ms() - frame.ts - self.clock_offset
        if age_ms > THRESHOLDS.frame.max_age_ms:
            self.stats.drop("stale")
            return
        async with self.state.pipeline_lock:
            pipeline = await self._get_pipeline()
            if pipeline is None:
                await self.send_error("PIPELINE_ERROR", "The vision pipeline is not available.", frame.frame_id)
                return
            try:
                result, decode_ms, pipeline_ms = await asyncio.to_thread(
                    self._decode_and_process, pipeline, frame)
            except InvalidFrame as exc:
                await self.send_error("INVALID_FRAME", str(exc), frame.frame_id)
                return
            except Exception:
                log.exception("Vision pipeline failed on frame %d of session %s", frame.frame_id, self.session_id)
                await self.send_error("PIPELINE_ERROR", "Vision failed on this frame.", frame.frame_id)
                return
        try:
            payload = FrameResult.model_validate(result).model_dump(mode="json")
        except ValidationError:
            log.exception("Pipeline result for frame %d does not match FrameResult (contract 4.4)", frame.frame_id)
            await self.send_error("PIPELINE_ERROR", "Vision returned an invalid result.", frame.frame_id)
            return
        await self.send("frame_result", payload)
        self.state.latest_jpeg, self.state.latest_result, self.state.latest_at_ms = frame.jpeg, payload, now_ms()
        total_ms = (time.perf_counter() - frame.received_at) * 1000
        self.stats.record(frame.frame_id, decode_ms, pipeline_ms, total_ms)

    async def _get_pipeline(self) -> Any:
        """Creates the session's pipeline on first use (caller holds pipeline_lock)."""
        if self.state.pipeline is None:
            try:
                self.state.pipeline = await asyncio.to_thread(make_pipeline, self.settings)
            except Exception:
                if not self._create_failed_logged:
                    log.exception("Could not create the vision pipeline for session %s", self.session_id)
                    self._create_failed_logged = True
                return None
        return self.state.pipeline

    @staticmethod
    def _decode_and_process(pipeline: Any, frame: PendingFrame) -> tuple[dict, float, float]:
        t0 = time.perf_counter()
        image = decode_jpeg(frame.jpeg)
        t1 = time.perf_counter()
        result = pipeline.process(image, frame.frame_id, frame.ts)
        t2 = time.perf_counter()
        return result, (t1 - t0) * 1000, (t2 - t1) * 1000

    async def close(self) -> None:
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):
            pass
