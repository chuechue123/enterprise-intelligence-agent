"""Small Open-Meteo adapter used only by the Weather MCP server."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

JsonFetcher = Callable[[str, Mapping[str, str | int | float]], dict[str, Any]]

WEATHER_CODES = {
    0: "晴",
    1: "大致晴朗",
    2: "局部多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "中等毛毛雨",
    55: "强毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    80: "小阵雨",
    81: "中等阵雨",
    82: "强阵雨",
    85: "小阵雪",
    86: "强阵雪",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴强冰雹",
}


def _fetch_json(
    base_url: str,
    parameters: Mapping[str, str | int | float],
) -> dict[str, Any]:
    request = Request(
        f"{base_url}?{urlencode(parameters)}",
        headers={"User-Agent": "BizInsight-Agent/0.1"},
    )
    with urlopen(request, timeout=15) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("weather provider returned a non-object response")
    if payload.get("error"):
        raise RuntimeError(str(payload.get("reason") or "weather provider error"))
    return payload


class OpenMeteoWeatherService:
    """Resolve locations and read current/forecast weather without a key."""

    def __init__(self, fetch_json: JsonFetcher = _fetch_json) -> None:
        self._fetch_json = fetch_json

    def resolve_location(
        self,
        query: str,
        *,
        language: str = "zh",
        count: int = 5,
    ) -> dict[str, Any]:
        query = query.strip()
        if not query:
            raise ValueError("location query must not be empty")
        if not 1 <= count <= 5:
            raise ValueError("location candidate count must be between 1 and 5")
        payload = self._fetch_json(
            "https://geocoding-api.open-meteo.com/v1/search",
            {
                "name": query,
                "count": count,
                "language": language,
                "format": "json",
            },
        )
        candidates = []
        for item in payload.get("results", []):
            if "latitude" not in item or "longitude" not in item:
                continue
            candidates.append(
                {
                    "name": item.get("name"),
                    "admin1": item.get("admin1"),
                    "country": item.get("country"),
                    "country_code": item.get("country_code"),
                    "latitude": item["latitude"],
                    "longitude": item["longitude"],
                    "timezone": item.get("timezone") or "auto",
                }
            )
        return {
            "query": query,
            "candidates": candidates,
            "source": "Open-Meteo Geocoding API",
        }

    def get_weather(
        self,
        *,
        latitude: float,
        longitude: float,
        timezone: str = "auto",
        forecast_days: int = 2,
    ) -> dict[str, Any]:
        if not -90 <= latitude <= 90:
            raise ValueError("latitude must be between -90 and 90")
        if not -180 <= longitude <= 180:
            raise ValueError("longitude must be between -180 and 180")
        if not 1 <= forecast_days <= 7:
            raise ValueError("forecast_days must be between 1 and 7")
        payload = self._fetch_json(
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": latitude,
                "longitude": longitude,
                "timezone": timezone,
                "forecast_days": forecast_days,
                "current": (
                    "temperature_2m,apparent_temperature,relative_humidity_2m,"
                    "precipitation,weather_code,wind_speed_10m"
                ),
                "daily": (
                    "weather_code,temperature_2m_max,temperature_2m_min,"
                    "precipitation_probability_max"
                ),
            },
        )
        current = dict(payload.get("current") or {})
        if "weather_code" in current:
            current["weather_description"] = WEATHER_CODES.get(
                int(current["weather_code"]),
                "未知天气",
            )
        daily_payload = dict(payload.get("daily") or {})
        dates = list(daily_payload.get("time") or [])
        daily = []
        for index, date in enumerate(dates):
            code = int(daily_payload["weather_code"][index])
            daily.append(
                {
                    "date": date,
                    "weather_code": code,
                    "weather_description": WEATHER_CODES.get(code, "未知天气"),
                    "temperature_max_c": daily_payload["temperature_2m_max"][index],
                    "temperature_min_c": daily_payload["temperature_2m_min"][index],
                    "precipitation_probability_max_percent": daily_payload[
                        "precipitation_probability_max"
                    ][index],
                }
            )
        return {
            "latitude": payload.get("latitude", latitude),
            "longitude": payload.get("longitude", longitude),
            "timezone": payload.get("timezone", timezone),
            "current": current,
            "daily": daily,
            "source": "Open-Meteo Forecast API",
        }


__all__ = ["OpenMeteoWeatherService", "WEATHER_CODES"]
