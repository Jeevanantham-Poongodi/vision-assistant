from collections import deque


class MotionTracker:
    """Estimate radial motion from each track's recent distance history."""

    def __init__(self, history_ms: int = 1500) -> None:
        self.history_ms = history_ms
        self._history: dict[int, deque[tuple[int, float]]] = {}
        self._last_seen: dict[int, int] = {}

    def update(
        self,
        track_id: int | None,
        distance_m: float | None,
        ts_ms: int,
    ) -> tuple[str, float | None]:
        if track_id is None:
            return "unknown", None

        self._last_seen[track_id] = ts_ms
        history = self._history.setdefault(track_id, deque())
        if distance_m is not None:
            history.append((ts_ms, distance_m))

        cutoff_ms = ts_ms - self.history_ms
        while history and history[0][0] < cutoff_ms:
            history.popleft()

        if len(history) < 3:
            return "unknown", None

        times_s = [(timestamp - history[0][0]) / 1000.0 for timestamp, _ in history]
        distances = [distance for _, distance in history]
        mean_time = sum(times_s) / len(times_s)
        mean_distance = sum(distances) / len(distances)
        denominator = sum((time_s - mean_time) ** 2 for time_s in times_s)
        if denominator == 0:
            return "unknown", None

        distance_slope = sum(
            (time_s - mean_time) * (distance - mean_distance)
            for time_s, distance in zip(times_s, distances)
        ) / denominator
        closing_speed = -distance_slope
        if closing_speed >= 0.5:
            return "approaching", closing_speed
        if closing_speed <= -0.5:
            return "receding", closing_speed
        return "stationary", closing_speed

    def prune(self, now_ms: int, max_age_ms: int = 3000) -> None:
        stale_ids = [
            track_id
            for track_id, last_seen in self._last_seen.items()
            if now_ms - last_seen > max_age_ms
        ]
        for track_id in stale_ids:
            self._last_seen.pop(track_id, None)
            self._history.pop(track_id, None)