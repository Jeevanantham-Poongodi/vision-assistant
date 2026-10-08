"""Mapbox-backed walking routes with provider-independent response data."""

from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any
from uuid import uuid4

_MAPBOX_BASE_URL = "https://api.mapbox.com"
_DEFAULT_TIMEOUT_S = 8.0


class NavigationError(Exception):
    """Safe navigation failure for the API layer to translate."""

    def __init__(self, code: str, status_code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class DestinationNotFoundError(NavigationError):
    def __init__(self) -> None:
        super().__init__(
            "DESTINATION_NOT_FOUND",
            404,
            "The requested destination could not be found.",
        )


class NavigationProviderError(NavigationError):
    def __init__(self) -> None:
        super().__init__(
            "NAVIGATION_PROVIDER_ERROR",
            503,
            "Walking directions are temporarily unavailable.",
        )


def _coordinates(value: object, field_name: str) -> tuple[float, float]:
    if not isinstance(value, dict):
        raise NavigationError(
            "VALIDATION_ERROR", 422, f"{field_name} must contain latitude and longitude."
        )
    latitude = value.get("lat")
    longitude = value.get("lng")
    if (
        isinstance(latitude, bool)
        or isinstance(longitude, bool)
        or not isinstance(latitude, (int, float))
        or not isinstance(longitude, (int, float))
        or not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
    ):
        raise NavigationError(
            "VALIDATION_ERROR", 422, f"{field_name} has invalid coordinates."
        )
    return float(latitude), float(longitude)


def _get_json(url: str, params: dict[str, str], timeout_s: float) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{url}?{query}",
        headers={"Accept": "application/json", "User-Agent": "vision-assistant/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Provider response must be a JSON object")
    return payload


def _request_mapbox(
    endpoint: str, params: dict[str, str], token: str, timeout_s: float
) -> dict[str, Any]:
    return _get_json(
        f"{_MAPBOX_BASE_URL}{endpoint}",
        {**params, "access_token": token},
        timeout_s,
    )


def _geocode_destination(
    destination: str, token: str, timeout_s: float
) -> tuple[float, float, str]:
    encoded_destination = urllib.parse.quote(destination, safe="")
    response = _request_mapbox(
        f"/geocoding/v5/mapbox.places/{encoded_destination}.json",
        {"limit": "1"},
        token,
        timeout_s,
    )
    features = response.get("features")
    if not isinstance(features, list) or not features:
        raise DestinationNotFoundError()

    feature = features[0]
    if not isinstance(feature, dict):
        raise DestinationNotFoundError()
    center = feature.get("center")
    if (
        not isinstance(center, list)
        or len(center) < 2
        or isinstance(center[0], bool)
        or isinstance(center[1], bool)
        or not isinstance(center[0], (int, float))
        or not isinstance(center[1], (int, float))
        or not math.isfinite(center[0])
        or not math.isfinite(center[1])
        or not -180 <= center[0] <= 180
        or not -90 <= center[1] <= 90
    ):
        raise DestinationNotFoundError()

    name_value = feature.get("place_name") or feature.get("text") or destination
    name = name_value.strip() if isinstance(name_value, str) else destination
    return float(center[1]), float(center[0]), name or destination


def format_spoken_distance(distance_m: object) -> str | None:
    """Return a speech-friendly approximate distance, if available."""
    if (
        isinstance(distance_m, bool)
        or not isinstance(distance_m, (int, float))
        or not math.isfinite(distance_m)
        or distance_m < 0
    ):
        return None
    rounded = int(math.floor(distance_m + 0.5))
    if rounded < 1:
        rounded = 1
    return f"about {rounded} meter" if rounded == 1 else f"about {rounded} meters"


def _maneuver_kind(step: dict[str, Any]) -> tuple[str, str]:
    maneuver_data = step.get("maneuver")
    if not isinstance(maneuver_data, dict):
        maneuver_data = {}
    maneuver_type = maneuver_data.get("type")
    modifier = maneuver_data.get("modifier")
    kind = maneuver_type.strip().lower() if isinstance(maneuver_type, str) else ""
    turn = modifier.strip().lower() if isinstance(modifier, str) else ""
    instruction_value = step.get("instruction")
    provider_instruction = (
        instruction_value.strip() if isinstance(instruction_value, str) else ""
    )

    if kind == "arrive":
        return "arrive", "You have reached your destination."
    if kind == "depart":
        return "depart", "Start walking straight"
    if kind in {"turn", "end of road", "fork", "merge", "on ramp", "off ramp"}:
        if turn in {"left", "right"}:
            return f"{kind} {turn}", f"Turn {turn}"
        if turn in {"slight left", "slight right"}:
            return f"{kind} {turn}", f"Turn slightly {turn.split()[-1]}"
        if turn in {"sharp left", "sharp right"}:
            return f"{kind} {turn}", f"Turn {turn.replace('sharp', 'sharply')}"
    if kind in {"straight", "continue"} or turn == "straight":
        return "straight", "Continue straight"

    safe_instruction = " ".join(provider_instruction.split())
    if safe_instruction:
        return kind or "continue", safe_instruction.rstrip(".")
    return kind or "continue", "Continue along the route"


def _spoken_instruction(
    step: dict[str, Any], distance_m: float | None
) -> tuple[str, str]:
    maneuver, phrase = _maneuver_kind(step)
    if maneuver == "arrive":
        return maneuver, phrase

    distance = format_spoken_distance(distance_m)
    if distance is None:
        return maneuver, f"{phrase}."
    if maneuver == "depart":
        return maneuver, f"{phrase} for {distance}."
    if maneuver == "straight":
        return maneuver, f"{phrase} for {distance}."
    if phrase.lower().startswith("turn "):
        return maneuver, f"{phrase}, then continue for {distance}."
    return maneuver, f"{phrase} for {distance}."


def _parse_route(
    route: dict[str, Any], destination_name: str
) -> dict[str, Any]:
    distance = route.get("distance")
    duration = route.get("duration")
    if (
        isinstance(distance, bool)
        or not isinstance(distance, (int, float))
        or not math.isfinite(distance)
        or distance < 0
        or isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration < 0
    ):
        raise NavigationProviderError()

    geometry = route.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") != "LineString":
        raise NavigationProviderError()
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or not coordinates:
        raise NavigationProviderError()
    for coordinate in coordinates:
        if (
            not isinstance(coordinate, (list, tuple))
            or len(coordinate) < 2
            or isinstance(coordinate[0], bool)
            or isinstance(coordinate[1], bool)
            or not isinstance(coordinate[0], (int, float))
            or not isinstance(coordinate[1], (int, float))
            or not math.isfinite(coordinate[0])
            or not math.isfinite(coordinate[1])
            or not -180 <= coordinate[0] <= 180
            or not -90 <= coordinate[1] <= 90
        ):
            raise NavigationProviderError()

    legs = route.get("legs")
    if not isinstance(legs, list) or not legs:
        raise NavigationProviderError()
    raw_steps: list[dict[str, Any]] = []
    for leg in legs:
        if not isinstance(leg, dict) or not isinstance(leg.get("steps"), list):
            raise NavigationProviderError()
        raw_steps.extend(step for step in leg["steps"] if isinstance(step, dict))
    if not raw_steps:
        raise NavigationProviderError()

    steps: list[dict[str, Any]] = []
    for index, step in enumerate(raw_steps):
        step_distance = step.get("distance")
        if (
            isinstance(step_distance, bool)
            or not isinstance(step_distance, (int, float))
            or not math.isfinite(step_distance)
            or step_distance < 0
        ):
            step_distance = None

        maneuver_data = step.get("maneuver")
        location = maneuver_data.get("location") if isinstance(maneuver_data, dict) else None
        if (
            not isinstance(location, (list, tuple))
            or len(location) < 2
            or isinstance(location[0], bool)
            or isinstance(location[1], bool)
            or not isinstance(location[0], (int, float))
            or not isinstance(location[1], (int, float))
            or not math.isfinite(location[0])
            or not math.isfinite(location[1])
            or not -180 <= location[0] <= 180
            or not -90 <= location[1] <= 90
        ):
            raise NavigationProviderError()

        instruction_value = step.get("instruction")
        instruction = (
            instruction_value.strip()
            if isinstance(instruction_value, str) and instruction_value.strip()
            else "Continue along the route"
        )
        maneuver, spoken_text = _spoken_instruction(step, step_distance)
        steps.append(
            {
                "index": index,
                "maneuver": maneuver,
                "distance_m": int(round(step_distance)) if step_distance is not None else 0,
                "instruction": instruction,
                "spoken_text": spoken_text,
                "location": {"lat": float(location[1]), "lng": float(location[0])},
            }
        )

    return {
        "route_id": str(uuid4()),
        "destination_name": destination_name,
        "total_distance_m": int(round(distance)),
        "duration_s": int(round(duration)),
        "steps": steps,
        "geometry": {
            "type": "LineString",
            "coordinates": [
                [float(coordinate[0]), float(coordinate[1])]
                for coordinate in coordinates
            ],
        },
    }


def get_walking_route(
    origin: dict[str, float],
    destination: str | dict[str, float],
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """Get a Mapbox walking route in the provider-independent Contract 7.16 shape.

    Raises ``NavigationError`` with a safe ``code`` and ``status_code`` for the
    API layer to translate. No provider exceptions or fabricated routes escape.
    """
    origin_lat, origin_lng = _coordinates(origin, "origin")
    if isinstance(destination, str):
        place_name = destination.strip()
        if not place_name:
            raise NavigationError("VALIDATION_ERROR", 422, "Destination must not be empty.")
    elif isinstance(destination, dict):
        place_name = ""
    else:
        raise NavigationError("VALIDATION_ERROR", 422, "Destination is invalid.")

    token = os.getenv("MAPBOX_TOKEN", "").strip()
    if not token:
        raise NavigationProviderError()

    timeout = (
        max(0.1, min(float(timeout_s), 60.0))
        if isinstance(timeout_s, (int, float))
        and not isinstance(timeout_s, bool)
        and math.isfinite(timeout_s)
        else _DEFAULT_TIMEOUT_S
    )

    try:
        if isinstance(destination, str):
            destination_lat, destination_lng, destination_name = _geocode_destination(
                place_name, token, timeout
            )
        else:
            destination_lat, destination_lng = _coordinates(destination, "destination")
            destination_name = "Destination"

        route_coordinates = (
            f"{origin_lng:.7f},{origin_lat:.7f};"
            f"{destination_lng:.7f},{destination_lat:.7f}"
        )
        response = _request_mapbox(
            f"/directions/v5/mapbox/walking/{route_coordinates}",
            {
                "steps": "true",
                "geometries": "geojson",
                "overview": "full",
            },
            token,
            timeout,
        )
        routes = response.get("routes")
        if not isinstance(routes, list) or not routes or not isinstance(routes[0], dict):
            raise NavigationProviderError()
        return _parse_route(routes[0], destination_name)
    except NavigationError:
        raise
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
    ) as exc:
        raise NavigationProviderError() from exc
    except Exception as exc:
        raise NavigationProviderError() from exc


if __name__ == "__main__":
    try:
        route = get_walking_route(
            {"lat": 11.0168, "lng": 76.9558},
            "Central Library",
        )
        print(json.dumps(route, indent=2))
    except NavigationError as error:
        print(f"{error.code}: {error}")
