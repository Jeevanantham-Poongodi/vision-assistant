from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from navigation import maps


ORIGIN = {"lat": 11.0168, "lng": 76.9558}
DESTINATION = {"lat": 11.0175, "lng": 76.958}


def route_fixture() -> dict[str, Any]:
    return {
        "routes": [
            {
                "distance": 240.0,
                "duration": 190.0,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [76.9558, 11.0168],
                        [76.956, 11.017],
                        [76.958, 11.0175],
                    ],
                },
                "legs": [
                    {
                        "steps": [
                            {
                                "distance": 20.0,
                                "instruction": "Head north",
                                "maneuver": {
                                    "type": "depart",
                                    "location": [76.9558, 11.0168],
                                },
                            },
                            {
                                "distance": 30.0,
                                "instruction": "Turn left",
                                "maneuver": {
                                    "type": "turn",
                                    "modifier": "left",
                                    "location": [76.956, 11.017],
                                },
                            },
                            {
                                "distance": 50.0,
                                "instruction": "Turn right",
                                "maneuver": {
                                    "type": "turn",
                                    "modifier": "right",
                                    "location": [76.957, 11.0172],
                                },
                            },
                            {
                                "distance": 0.0,
                                "instruction": "You have arrived",
                                "maneuver": {
                                    "type": "arrive",
                                    "location": [76.958, 11.0175],
                                },
                            },
                        ]
                    }
                ],
            }
        ]
    }


@pytest.fixture
def mocked_mapbox(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, str]]]:
    calls: list[tuple[str, dict[str, str]]] = []

    def fake_request(
        endpoint: str,
        params: dict[str, str],
        token: str,
        timeout_s: float,
    ) -> dict[str, Any]:
        calls.append((endpoint, params))
        assert token == "test-token"
        if endpoint.startswith("/geocoding/"):
            return {
                "features": [
                    {
                        "center": [DESTINATION["lng"], DESTINATION["lat"]],
                        "place_name": "Central Library",
                    }
                ]
            }
        return route_fixture()

    monkeypatch.setenv("MAPBOX_TOKEN", "test-token")
    monkeypatch.setattr(maps, "_request_mapbox", fake_request)
    return calls


def test_place_name_geocodes_and_returns_contract_shape(
    mocked_mapbox: list[tuple[str, dict[str, str]]],
) -> None:
    route = maps.get_walking_route(ORIGIN, "Central Library")

    assert len(mocked_mapbox) == 2
    assert mocked_mapbox[0][0].endswith("/Central%20Library.json")
    assert mocked_mapbox[1][0].startswith("/directions/v5/mapbox/walking/")
    assert mocked_mapbox[1][1]["steps"] == "true"
    assert route["destination_name"] == "Central Library"
    assert set(route) == {
        "route_id",
        "destination_name",
        "total_distance_m",
        "duration_s",
        "steps",
        "geometry",
    }
    UUID(route["route_id"])
    assert route["total_distance_m"] == 240
    assert route["duration_s"] == 190
    assert route["geometry"]["type"] == "LineString"
    assert route["geometry"]["coordinates"][0] == [76.9558, 11.0168]
    assert route["steps"][0] == {
        "index": 0,
        "maneuver": "depart",
        "distance_m": 20,
        "instruction": "Head north",
        "spoken_text": "Start walking straight for about 20 meters.",
        "location": {"lat": 11.0168, "lng": 76.9558},
    }


def test_coordinates_skip_geocoding(
    mocked_mapbox: list[tuple[str, dict[str, str]]],
) -> None:
    route = maps.get_walking_route(ORIGIN, DESTINATION)

    assert len(mocked_mapbox) == 1
    assert mocked_mapbox[0][0].startswith("/directions/v5/mapbox/walking/")
    assert f"{DESTINATION['lng']:.7f}" in mocked_mapbox[0][0]
    assert route["destination_name"] == "Destination"


def test_destination_not_found_raises_expected_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAPBOX_TOKEN", "test-token")
    monkeypatch.setattr(
        maps,
        "_request_mapbox",
        lambda *args, **kwargs: {"features": []},
    )

    with pytest.raises(maps.DestinationNotFoundError) as error:
        maps.get_walking_route(ORIGIN, "Unknown Place")

    assert error.value.code == "DESTINATION_NOT_FOUND"
    assert error.value.status_code == 404


def test_invalid_geocoding_coordinates_raise_destination_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAPBOX_TOKEN", "test-token")
    monkeypatch.setattr(
        maps,
        "_request_mapbox",
        lambda *args, **kwargs: {
            "features": [{"center": [500, 20], "place_name": "Invalid"}]
        },
    )

    with pytest.raises(maps.DestinationNotFoundError) as error:
        maps.get_walking_route(ORIGIN, "Invalid Place")

    assert error.value.code == "DESTINATION_NOT_FOUND"


@pytest.mark.parametrize("destination", ["", "   "])
def test_empty_destination_is_validation_error(
    monkeypatch: pytest.MonkeyPatch, destination: str
) -> None:
    monkeypatch.setenv("MAPBOX_TOKEN", "test-token")

    with pytest.raises(maps.NavigationError) as error:
        maps.get_walking_route(ORIGIN, destination)

    assert error.value.code == "VALIDATION_ERROR"
    assert error.value.status_code == 422


def test_missing_token_raises_safe_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MAPBOX_TOKEN", raising=False)

    with pytest.raises(maps.NavigationProviderError) as error:
        maps.get_walking_route(ORIGIN, "Central Library")

    assert error.value.code == "NAVIGATION_PROVIDER_ERROR"
    assert "token" not in str(error.value).lower()


@pytest.mark.parametrize(
    "failure",
    [TimeoutError("private timeout details"), OSError("private provider response")],
)
def test_network_failures_are_safe_provider_errors(
    monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    monkeypatch.setenv("MAPBOX_TOKEN", "test-token")

    def fail(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise failure

    monkeypatch.setattr(maps, "_request_mapbox", fail)
    with pytest.raises(maps.NavigationProviderError) as error:
        maps.get_walking_route(ORIGIN, DESTINATION)

    assert "private" not in str(error.value)


def test_missing_or_malformed_route_data_is_rejected(
    mocked_mapbox: list[tuple[str, dict[str, str]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_steps(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"routes": [{"distance": 1, "duration": 2}]}

    monkeypatch.setattr(maps, "_request_mapbox", no_steps)

    with pytest.raises(maps.NavigationProviderError):
        maps.get_walking_route(ORIGIN, DESTINATION)


def test_invalid_route_payload_is_rejected(
    mocked_mapbox: list[tuple[str, dict[str, str]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        maps,
        "_request_mapbox",
        lambda *args, **kwargs: {"routes": [{"distance": float("nan")}]},
    )

    with pytest.raises(maps.NavigationProviderError):
        maps.get_walking_route(ORIGIN, DESTINATION)


@pytest.mark.parametrize(
    ("maneuver", "expected"),
    [
        ({"type": "turn", "modifier": "left"}, "Turn left, then continue for about 30 meters."),
        ({"type": "turn", "modifier": "right"}, "Turn right, then continue for about 30 meters."),
        (
            {"type": "turn", "modifier": "slight left"},
            "Turn slightly left, then continue for about 30 meters.",
        ),
        (
            {"type": "turn", "modifier": "slight right"},
            "Turn slightly right, then continue for about 30 meters.",
        ),
        ({"type": "straight"}, "Continue straight for about 30 meters."),
        ({"type": "arrive"}, "You have reached your destination."),
    ],
)
def test_spoken_maneuver_conversions(maneuver: dict[str, str], expected: str) -> None:
    route_step = {
        "distance": 30,
        "maneuver": {
            **maneuver,
            "location": [76.9, 11.0],
        },
    }

    _, spoken_text = maps._spoken_instruction(route_step, 30)

    assert spoken_text == expected


def test_unknown_maneuver_uses_provider_instruction() -> None:
    step = {
        "instruction": "Take the pedestrian path",
        "maneuver": {"type": "use sidewalk", "location": [76.9, 11.0]},
    }

    _, spoken_text = maps._spoken_instruction(step, None)

    assert spoken_text == "Take the pedestrian path."


def test_coordinate_validation_rejects_out_of_range_origin(
    mocked_mapbox: list[tuple[str, dict[str, str]]],
) -> None:
    with pytest.raises(maps.NavigationError) as error:
        maps.get_walking_route({"lat": 91, "lng": 76}, DESTINATION)

    assert error.value.code == "VALIDATION_ERROR"
