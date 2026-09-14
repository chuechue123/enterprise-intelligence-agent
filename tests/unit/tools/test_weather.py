"""Unit tests for the keyless Open-Meteo adapter."""

from typing import Any

import pytest

from bizinsight.tools.weather import OpenMeteoWeatherService


def test_resolve_location_returns_bounded_structured_candidates() -> None:
    def fetch(url: str, params: dict[str, Any]) -> dict[str, Any]:
        assert "geocoding-api" in url
        assert params["name"] == "上海"
        return {
            "results": [
                {
                    "name": "上海",
                    "admin1": "上海",
                    "country": "中国",
                    "country_code": "CN",
                    "latitude": 31.22222,
                    "longitude": 121.45806,
                    "timezone": "Asia/Shanghai",
                }
            ]
        }

    result = OpenMeteoWeatherService(fetch).resolve_location("上海")

    assert result["candidates"][0]["timezone"] == "Asia/Shanghai"
    assert result["source"] == "Open-Meteo Geocoding API"


def test_get_weather_adds_human_readable_descriptions() -> None:
    def fetch(url: str, params: dict[str, Any]) -> dict[str, Any]:
        assert "forecast" in url
        assert params["forecast_days"] == 2
        return {
            "latitude": 31.22,
            "longitude": 121.46,
            "timezone": "Asia/Shanghai",
            "current": {
                "time": "2026-09-11T10:00",
                "temperature_2m": 28.1,
                "apparent_temperature": 30.0,
                "relative_humidity_2m": 71,
                "precipitation": 0,
                "weather_code": 2,
                "wind_speed_10m": 8.2,
            },
            "daily": {
                "time": ["2026-09-11", "2026-09-12"],
                "weather_code": [2, 61],
                "temperature_2m_max": [31, 29],
                "temperature_2m_min": [24, 23],
                "precipitation_probability_max": [20, 70],
            },
        }

    result = OpenMeteoWeatherService(fetch).get_weather(
        latitude=31.22,
        longitude=121.46,
        timezone="Asia/Shanghai",
    )

    assert result["current"]["weather_description"] == "局部多云"
    assert result["daily"][1]["weather_description"] == "小雨"
    assert result["daily"][1]["precipitation_probability_max_percent"] == 70


@pytest.mark.parametrize(
    ("latitude", "longitude", "days"),
    [(91, 0, 2), (0, 181, 2), (0, 0, 8)],
)
def test_get_weather_rejects_unbounded_inputs(
    latitude: float,
    longitude: float,
    days: int,
) -> None:
    service = OpenMeteoWeatherService(lambda *_: {})
    with pytest.raises(ValueError):
        service.get_weather(
            latitude=latitude,
            longitude=longitude,
            forecast_days=days,
        )
