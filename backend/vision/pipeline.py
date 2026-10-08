_WALKING_CORRIDOR = frozenset({"slight_left", "center", "slight_right"})
_PATH_CLEAR_DISTANCE_M = 3.0


def _calculate_path_clear(detections: list[dict]) -> tuple[bool, float | None]:
    corridor_distances = [
        detection["distance_m"]
        for detection in detections
        if detection.get("direction") in _WALKING_CORRIDOR
        and detection.get("distance_m") is not None
    ]
    nearest_distance = min(corridor_distances, default=None)
    path_clear = not any(
        distance < _PATH_CLEAR_DISTANCE_M for distance in corridor_distances
    )
    return path_clear, nearest_distance