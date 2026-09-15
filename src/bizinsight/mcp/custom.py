"""Probe and runtime attachment for user-configured AgentScope MCP servers."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agentscope.mcp import HttpMCPConfig, MCPClient, StdioMCPConfig
from agentscope.tool import Toolkit

from bizinsight.mcp_registry import MCPServerConfig, load_custom


def build_custom_client(config: MCPServerConfig, *, project_root: Path) -> MCPClient:
    """Build the exact client used by both probing and Agent tool injection."""
    if config.api_key_env and not os.getenv(config.api_key_env):
        raise ValueError(f"环境变量 {config.api_key_env} 尚未配置")
    if config.transport == "stdio":
        mcp_config = StdioMCPConfig(
            command=config.command or "",
            args=config.args,
            cwd=project_root.resolve(),
        )
    else:
        headers = None
        if config.api_key_env:
            headers = {"Authorization": f"Bearer {os.environ[config.api_key_env]}"}
        mcp_config = HttpMCPConfig(url=config.url or "", headers=headers, timeout=10.0)
    return MCPClient(
        name=config.name,
        is_stateful=True,
        mcp_config=mcp_config,
        execution_timeout=30,
    )


async def _safe_close(client: MCPClient) -> None:
    if not client.is_connected:
        return
    try:
        await client.close()
    except asyncio.CancelledError:
        task = asyncio.current_task()
        if task is not None:
            while task.cancelling():
                task.uncancel()
    except Exception:
        pass


def _safe_error(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return "连接或工具发现超时"
    if isinstance(exc, ValueError):
        return str(exc)[:240]
    return f"连接失败（{type(exc).__name__}）"


async def probe_server(
    config: MCPServerConfig,
    *,
    project_root: Path,
    timeout: float = 12.0,
) -> dict[str, Any]:
    started = time.monotonic()
    client: MCPClient | None = None
    try:
        client = build_custom_client(config, project_root=project_root)
        async with asyncio.timeout(timeout):
            await client.connect()
            raw_tools = await client.list_raw_tools()
        tools = [
            {
                "name": item.name,
                "description": item.description or "",
                "input_schema": item.inputSchema,
            }
            for item in raw_tools
        ]
        return {
            "ok": True,
            "tools": tools,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "error": None,
        }
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        return {
            "ok": False,
            "tools": [],
            "duration_ms": round((time.monotonic() - started) * 1000),
            "error": _safe_error(exc),
        }
    finally:
        if client is not None:
            await _safe_close(client)


@dataclass
class CustomMCPConnection:
    client: MCPClient
    attached_tool_names: list[str] = field(default_factory=list)

    async def connect_to(self, toolkit: Toolkit) -> list[str]:
        await self.client.connect()
        tools = await self.client.list_tools()
        for tool in tools:
            await toolkit.add_tool(tool)
            self.attached_tool_names.append(tool.name)
        return list(self.attached_tool_names)

    async def close(self, toolkit: Toolkit | None = None) -> None:
        if toolkit is not None:
            for name in self.attached_tool_names:
                try:
                    await toolkit.remove_tool(name)
                except Exception:
                    pass
        self.attached_tool_names.clear()
        await _safe_close(self.client)


async def attach_enabled_servers(
    *, project_root: Path, target: str, toolkit: Toolkit
) -> tuple[list[CustomMCPConnection], list[dict[str, str]]]:
    connections: list[CustomMCPConnection] = []
    errors: list[dict[str, str]] = []
    for config in load_custom(project_root):
        if not config.enabled or target not in config.targets:
            continue
        connection = CustomMCPConnection(
            build_custom_client(config, project_root=project_root)
        )
        try:
            await connection.connect_to(toolkit)
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            await connection.close(toolkit)
            errors.append({"server": config.name, "error": _safe_error(exc)})
        else:
            connections.append(connection)
    return connections, errors


async def close_connections(
    connections: list[CustomMCPConnection], toolkit: Toolkit | None = None
) -> None:
    for connection in reversed(connections):
        await connection.close(toolkit)
    connections.clear()


__all__ = [
    "CustomMCPConnection",
    "attach_enabled_servers",
    "build_custom_client",
    "close_connections",
    "probe_server",
]
