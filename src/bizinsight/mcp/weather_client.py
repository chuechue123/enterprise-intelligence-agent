"""AgentScope MCPClient lifecycle wrapper for the Weather MCP server."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path

from agentscope.mcp import MCPClient, StdioMCPConfig
from agentscope.tool import Toolkit

WEATHER_TOOL_NAMES = ("resolve_weather_location", "get_weather")


@dataclass
class WeatherMCPConnection:
    client: MCPClient
    attached_tool_names: list[str] = field(default_factory=list)

    @classmethod
    def build(cls, *, project_root: Path) -> WeatherMCPConnection:
        root = project_root.resolve()
        return cls(
            MCPClient(
                name="bizinsight-weather",
                is_stateful=True,
                execution_timeout=30,
                mcp_config=StdioMCPConfig(
                    command=sys.executable,
                    args=["-m", "bizinsight.mcp.weather_server"],
                    cwd=root,
                ),
            )
        )

    async def connect_to(self, toolkit: Toolkit) -> list[str]:
        await self.client.connect()
        available = await self.client.list_tools()
        selected = [
            name
            for name in WEATHER_TOOL_NAMES
            if any(tool.name.endswith(f"__{name}") for tool in available)
        ]
        for tool in available:
            if any(tool.name.endswith(f"__{name}") for name in selected):
                await toolkit.add_tool(tool)
                self.attached_tool_names.append(tool.name)
        return selected

    async def close(self) -> None:
        try:
            await self.client.close()
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if task is not None:
                task.uncancel()


__all__ = ["WEATHER_TOOL_NAMES", "WeatherMCPConnection"]
