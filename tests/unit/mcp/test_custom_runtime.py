from __future__ import annotations

from pathlib import Path

import pytest
from agentscope.tool import Toolkit

from bizinsight.mcp.custom import attach_enabled_servers
from bizinsight.mcp_registry import MCPServerConfig, save_custom


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeClient:
    def __init__(self, name: str, *, fails: bool = False) -> None:
        self.name = name
        self.fails = fails
        self.is_connected = False

    async def connect(self) -> None:
        if self.fails:
            raise ConnectionError("private endpoint details")
        self.is_connected = True

    async def list_tools(self):
        return [_FakeTool(f"mcp__{self.name}__lookup")]

    async def close(self) -> None:
        self.is_connected = False


@pytest.mark.asyncio
async def test_attach_only_enabled_authorized_servers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configs = [
        MCPServerConfig(
            name="allowed",
            transport="stdio",
            command="python",
            targets=["DeliveryAgent"],
        ),
        MCPServerConfig(
            name="other",
            transport="stdio",
            command="python",
            targets=["FinanceSalesAgent"],
        ),
        MCPServerConfig(
            name="off",
            transport="stdio",
            command="python",
            targets=["DeliveryAgent"],
            enabled=False,
        ),
    ]
    save_custom(tmp_path, configs)
    monkeypatch.setattr(
        "bizinsight.mcp.custom.build_custom_client",
        lambda config, project_root: _FakeClient(config.name),
    )
    toolkit = Toolkit()

    connections, errors = await attach_enabled_servers(
        project_root=tmp_path,
        target="DeliveryAgent",
        toolkit=toolkit,
    )

    assert errors == []
    assert [item.client.name for item in connections] == ["allowed"]
    assert connections[0].attached_tool_names == ["mcp__allowed__lookup"]


@pytest.mark.asyncio
async def test_one_server_failure_does_not_block_other_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    save_custom(
        tmp_path,
        [
            MCPServerConfig(
                name=name,
                transport="stdio",
                command="python",
                targets=["BizInsightSupervisor"],
            )
            for name in ("broken", "working")
        ],
    )
    monkeypatch.setattr(
        "bizinsight.mcp.custom.build_custom_client",
        lambda config, project_root: _FakeClient(
            config.name, fails=config.name == "broken"
        ),
    )
    connections, errors = await attach_enabled_servers(
        project_root=tmp_path,
        target="BizInsightSupervisor",
        toolkit=Toolkit(),
    )

    assert [item.client.name for item in connections] == ["working"]
    assert errors == [{"server": "broken", "error": "连接失败（ConnectionError）"}]
