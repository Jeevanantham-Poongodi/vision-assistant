from uuid import uuid4


_RISK_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
_COOLDOWN_MS = {"critical": 1500, "high": 3000, "medium": 6000}
_MAX_WARNINGS = 2


class WarningSelector:
    def __init__(self) -> None:
        self._last_spoken: dict[tuple, tuple[int, str]] = {}

    def select(self, detections: list[dict], now_ms: int) -> list[dict]:
        warnings = []
        ordered_detections = sorted(
            detections, key=lambda detection: detection.get("priority", 0), reverse=True
        )

        for detection in ordered_detections:
            risk_level = detection.get("risk_level", "low")
            if risk_level == "low":
                continue

            key = self._cooldown_key(detection)
            previous = self._last_spoken.get(key)
            escalated = previous is not None and (
                _RISK_RANK[risk_level] > _RISK_RANK[previous[1]]
            )
            cooldown_elapsed = previous is None or (
                now_ms - previous[0] >= _COOLDOWN_MS[risk_level]
            )
            if not escalated and not cooldown_elapsed:
                continue

            message, short_text = self._build_text(detection, risk_level)
            warnings.append(
                {
                    "warning_id": str(uuid4()),
                    "track_id": detection.get("track_id"),
                    "class_name": detection["class_name"],
                    "risk_level": risk_level,
                    "priority": detection["priority"],
                    "message": message,
                    "short_text": short_text,
                    "speak": True,
                    "interrupt": risk_level == "critical",
                    "rule": detection.get("rule", detection.get("rule_id", "R7")),
                }
            )
            self._last_spoken[key] = (now_ms, risk_level)
            if len(warnings) == _MAX_WARNINGS:
                break

        return warnings

    @staticmethod
    def _cooldown_key(detection: dict) -> tuple:
        track_id = detection.get("track_id")
        if track_id is not None:
            return ("track", track_id)
        return ("class_direction", detection["class_name"], detection["direction"])

    @staticmethod
    def _build_text(detection: dict, risk_level: str) -> tuple[str, str]:
        try:
            from speech.phrases import build_short_text, build_warning_message
        except ModuleNotFoundError as error:
            if error.name != "speech.phrases":
                raise
            spoken_name = detection.get("spoken_name", detection["class_name"])
            distance = detection.get("distance_m")
            direction = detection["direction"]
            message = f"{spoken_name} {distance} meters {direction}"
            short_text = f"{spoken_name} {direction} {distance} m"
            return message, short_text

        rule_id = detection.get("rule", detection.get("rule_id", "R7"))
        return (
            build_warning_message(detection, risk_level, rule_id),
            build_short_text(detection),
        )