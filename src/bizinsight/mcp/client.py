"""Lifecycle wrapper for AgentScope's public MCPClient API."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from agentscope.mcp import MCPClient, StdioMCPConfig
from agentscope.tool import Toolkit

from bizinsight.mcp.contracts import TOOL_NAMES, require_scope


@dataclass
class BusinessMCPConnection:
    client: MCPClient

    @classmethod
    def build(cls, *, scope: str, project_root: Path) -> BusinessMCPConnection:
        require_scope(scope)
        client = MCPClient(
            name=f"bizinsight-{scope}",
            is_stateful=True,
            execution_timeout=30,
            mcp_config=StdioMCPConfig(
                command=sys.executable,
                args=[
                    "-m",
                    "bizinsight.mcp.server",
                    "--scope",
                    scope,
                    "--project-root",
                    str(project_root.resolve()),
                ],
                cwd=project_root.resolve(),
            ),
        )
        return cls(client)

    async def connect_to(self, toolkit: Toolkit) -> list[str]:
        await self.client.connect()
        available = await self.client.list_tools()
        selected = [
            name
            for name in TOOL_NAMES
            if any(tool.name.endswith(f"__{name}") for tool in available)
        ]
        for tool in available:
            if any(tool.name.endswith(f"__{name}") for name in selected):
                await toolkit.add_tool(tool)
        return selected

    async def close(self) -> None:
        await self.client.close()
