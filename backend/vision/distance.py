KNOWN_HEIGHTS_M = {
    "person": 1.65,
    "car": 1.5,
    "bus": 3.0,
    "truck": 3.0,
    "motorcycle": 1.2,
    "bicycle": 1.0,
    "chair": 0.9,
    "bench": 0.85,
    "dining_table": 0.75,
    "potted_plant": 0.6,
    "dog": 0.6,
    "cow": 1.4,
    "fire_hydrant": 0.7,
    "stop_sign": 0.75,
    "traffic_light": 0.9,
    "backpack": 0.5,
    "suitcase": 0.65,
    "bottle": 0.25,
}


def _distance_zone(distance_m: float | None) -> str:
    if distance_m is None:
        return "unknown"
    if distance_m < 1.0:
        return "very_close"
    if distance_m < 2.0:
        return "near"
    if distance_m < 5.0:
        return "medium"
    return "far"


def estimate_distance(
    class_name: str,
    bbox: tuple[int, int, int, int],
    frame_w: int,
    frame_h: int,
    focal_px: float,
) -> tuple[float | None, str, str]:
    x1, y1, x2, y2 = bbox
    bbox_height = y2 - y1
    real_height = KNOWN_HEIGHTS_M.get(class_name)
    if (
        real_height is None
        or bbox_height <= 0
        or frame_w <= 0
        or frame_h <= 0
        or focal_px <= 0
    ):
        return None, "unknown", "none"

    estimate = real_height * focal_px / bbox_height
    touches_top = y1 <= 3
    touches_bottom = frame_h - y2 <= 3
    method = "edge_clipped" if touches_top or touches_bottom else "pinhole"
    if touches_bottom and bbox_height / frame_h > 0.6:
        estimate = min(estimate, 0.9)

    distance_m = round(estimate, 1)
    return distance_m, _distance_zone(distance_m), method


class DistanceSmoother:
    """Apply an exponential moving average independently to each track."""

    def __init__(self, alpha: float = 0.4) -> None:
        if not 0.0 < alpha <= 1.0:
            raise ValueError("alpha must be greater than 0 and at most 1")
        self.alpha = alpha
        self._distances: dict[int, float] = {}

    def update(self, track_id: int | None, distance_m: float | None) -> float | None:
        if track_id is None or distance_m is None:
            return distance_m
        previous = self._distances.get(track_id)
        smoothed = (
            distance_m
            if previous is None
            else self.alpha * distance_m + (1.0 - self.alpha) * previous
        )
        self._distances[track_id] = smoothed
        return round(smoothed, 1)