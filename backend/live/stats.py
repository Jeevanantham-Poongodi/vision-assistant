# backend/live/stats.py
"""Per-session frame timing: a DEBUG line per frame and an INFO summary every 5 s (BE-05)."""
import logging
import math
import time
from collections.abc import Callable

log = logging.getLogger("vision_assistant")


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile; 0.0 for an empty list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


class FrameStats:
    def __init__(self, label: str, window_s: float = 5.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.label = label
        self.window_s = window_s
        self.clock = clock
        self._reset(clock())

    def _reset(self, now: float) -> None:
        self.window_start = now
        self.decode_ms: list[float] = []
        self.pipeline_ms: list[float] = []
        self.total_ms: list[float] = []
        self.stale = 0
        self.superseded = 0

    def record(self, frame_id: int, decode_ms: float, pipeline_ms: float, total_ms: float) -> None:
        log.debug("%s frame %d: decode_ms=%.1f pipeline_ms=%.1f total_ms=%.1f",
                  self.label, frame_id, decode_ms, pipeline_ms, total_ms)
        self.decode_ms.append(decode_ms)
        self.pipeline_ms.append(pipeline_ms)
        self.total_ms.append(total_ms)
        self.maybe_report()

    def drop(self, reason: str) -> None:
        if reason == "stale":
            self.stale += 1
        else:
            self.superseded += 1
        self.maybe_report()

    def summary(self, now: float) -> str:
        elapsed = max(now - self.window_start, 1e-9)
        return (
            f"{self.label}: {len(self.total_ms) / elapsed:.1f} fps, "
            f"total p50 {percentile(self.total_ms, 50):.0f} ms p95 {percentile(self.total_ms, 95):.0f} ms, "
            f"decode p95 {percentile(self.decode_ms, 95):.0f} ms, "
            f"pipeline p95 {percentile(self.pipeline_ms, 95):.0f} ms, "
            f"dropped {self.stale + self.superseded} (stale {self.stale}, superseded {self.superseded})"
        )

    def maybe_report(self) -> None:
        now = self.clock()
        if now - self.window_start >= self.window_s:
            log.info(self.summary(now))
            self._reset(now)
