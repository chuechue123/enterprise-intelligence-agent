"""Business Data MCP integration built on AgentScope's MCP client."""

from bizinsight.mcp.client import BusinessMCPConnection
from bizinsight.mcp.contracts import MCP_SCOPES

__all__ = ["BusinessMCPConnection", "MCP_SCOPES"]
