from pathlib import Path

import pytest
from agentscope.tool import Toolkit

from bizinsight.mcp.weather_client import WEATHER_TOOL_NAMES, WeatherMCPConnection


@pytest.mark.asyncio
async def test_agentscope_weather_client_discovers_readonly_tools() -> None:
    root = Path(__file__).resolve().parents[3]
    connection = WeatherMCPConnection.build(project_root=root)
    toolkit = Toolkit()
    try:
        names = await connection.connect_to(toolkit)
        assert names == list(WEATHER_TOOL_NAMES)
        assert len(connection.attached_tool_names) == 2
    finally:
        await connection.close()


@pytest.mark.online
@pytest.mark.asyncio
async def test_real_weather_mcp_returns_current_shanghai_weather() -> None:
    root = Path(__file__).resolve().parents[3]
    connection = WeatherMCPConnection.build(project_root=root)
    try:
        await connection.client.connect()
        location_tool = await connection.client.get_tool("resolve_weather_location")
        location = await location_tool(query="上海", language="zh", count=1)
        # AgentScope MCPTool emits a running ToolChunk; the Agent executor
        # converts it into the completed ToolResponse used by the ReAct loop.
        assert location.state.value == "running"
        assert "Asia/Shanghai" in str(location.content)

        weather_tool = await connection.client.get_tool("get_weather")
        weather = await weather_tool(
            latitude=31.22222,
            longitude=121.45806,
            timezone="Asia/Shanghai",
            forecast_days=2,
        )
        assert weather.state.value == "running"
        assert "Open-Meteo Forecast API" in str(weather.content)
    finally:
        await connection.close()
