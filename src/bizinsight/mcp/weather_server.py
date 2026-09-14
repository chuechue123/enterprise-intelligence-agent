"""Independent read-only Weather MCP server backed by Open-Meteo."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from bizinsight.tools.weather import OpenMeteoWeatherService


def create_weather_mcp_server(
    service: OpenMeteoWeatherService | None = None,
) -> FastMCP:
    server = FastMCP("BizInsight Weather", log_level="ERROR")
    weather = service or OpenMeteoWeatherService()

    @server.tool(annotations={"readOnlyHint": True})
    def resolve_weather_location(
        query: str,
        language: str = "zh",
        count: int = 5,
    ) -> dict[str, Any]:
        """Resolve a city or place name before requesting weather."""

        return weather.resolve_location(query, language=language, count=count)

    @server.tool(annotations={"readOnlyHint": True})
    def get_weather(
        latitude: float,
        longitude: float,
        timezone: str = "auto",
        forecast_days: int = 2,
    ) -> dict[str, Any]:
        """Get current conditions and a bounded daily forecast."""

        return weather.get_weather(
            latitude=latitude,
            longitude=longitude,
            timezone=timezone,
            forecast_days=forecast_days,
        )

    return server


def main() -> None:
    create_weather_mcp_server().run("stdio")


if __name__ == "__main__":
    main()
