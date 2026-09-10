from pathlib import Path

import pytest
from agentscope.tool import Toolkit

from bizinsight.mcp.client import BusinessMCPConnection
from bizinsight.mcp.contracts import TOOL_NAMES


@pytest.mark.asyncio
async def test_agentscope_client_discovers_business_tools() -> None:
    root = Path(__file__).resolve().parents[3]
    connection = BusinessMCPConnection.build(
        scope="FinanceSalesAgent", project_root=root
    )
    toolkit = Toolkit()
    try:
        names = await connection.connect_to(toolkit)
        assert names == list(TOOL_NAMES)
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_mcp_process_scope_rejects_other_domain_metric() -> None:
    root = Path(__file__).resolve().parents[3]
    connection = BusinessMCPConnection.build(
        scope="FinanceSalesAgent", project_root=root
    )
    try:
        await connection.client.connect()
        tool = await connection.client.get_tool("calculate_business_metric")
        result = await tool(metric_name="renewal_rate", period="2026-Q2")
        assert result.state.value == "error"
    finally:
        await connection.close()
