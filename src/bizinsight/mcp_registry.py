"""Validated, atomically persisted registry for custom MCP servers."""

from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bizinsight.mcp.contracts import MCP_SCOPES, TOOL_NAMES
from bizinsight.schemas import WorkerName

MCP_TARGETS = (
    "BizInsightSupervisor",
    WorkerName.FINANCE_SALES.value,
    WorkerName.CUSTOMER_PRODUCT.value,
    WorkerName.DELIVERY.value,
)


class ProbeSnapshot(BaseModel):
    status: Literal["ok", "error", "never"] = "never"
    checked_at: str | None = None
    duration_ms: int | None = None
    error: str | None = None


class MCPServerConfig(BaseModel):
    """One safe custom MCP definition persisted in YAML."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=48, pattern=r"^[A-Za-z0-9_-]+$")
    display_name: str = Field(default="", max_length=80)
    description: str = Field(default="", max_length=400)
    transport: Literal["stdio", "streamable_http", "sse"] = "stdio"
    command: str | None = Field(default=None, min_length=1, max_length=500)
    args: list[str] = Field(default_factory=list, max_length=64)
    url: str | None = Field(default=None, max_length=2000)
    api_key_env: str | None = Field(
        default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", max_length=100
    )
    targets: list[str] = Field(default_factory=lambda: ["BizInsightSupervisor"])
    enabled: bool = True
    tools: list[dict[str, Any]] = Field(default_factory=list)
    last_probe: ProbeSnapshot = Field(default_factory=ProbeSnapshot)

    @field_validator("args")
    @classmethod
    def validate_args(cls, value: list[str]) -> list[str]:
        if any(not isinstance(item, str) or len(item) > 1000 for item in value):
            raise ValueError("每个命令参数必须是长度不超过 1000 的字符串")
        return value

    @field_validator("targets")
    @classmethod
    def validate_targets(cls, value: list[str]) -> list[str]:
        targets = list(dict.fromkeys(value))
        if not targets:
            raise ValueError("至少授权给一个 Agent")
        unknown = sorted(set(targets) - set(MCP_TARGETS))
        if unknown:
            raise ValueError(f"未知 Agent：{', '.join(unknown)}")
        return targets

    @model_validator(mode="after")
    def validate_connection(self) -> MCPServerConfig:
        if not self.display_name:
            self.display_name = self.name
        if self.transport == "stdio":
            if not self.command:
                raise ValueError("stdio MCP 必须提供 command")
            self.url = None
        else:
            if not self.url:
                raise ValueError("HTTP MCP 必须提供 URL")
            parsed = urlsplit(self.url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("MCP URL 必须是有效的 http 或 https 地址")
            if self.transport == "sse" and not (
                parsed.path.endswith("/sse") or parsed.path.endswith("/messages/")
            ):
                raise ValueError("SSE 地址路径必须以 /sse 或 /messages/ 结尾")
            self.command = None
            self.args = []
        return self

    @property
    def connection_label(self) -> str:
        if self.transport == "stdio":
            return " ".join([self.command or "", *self.args]).strip()
        return self.url or ""

    def public_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data.update(
            {
                "type": "custom",
                "connection": self.connection_label,
                "credential_configured": bool(
                    self.api_key_env and os.getenv(self.api_key_env)
                ),
            }
        )
        return data


def _registry_path(root: Path) -> Path:
    return root / "config" / "mcp_servers.yaml"


def load_custom(root: Path) -> list[MCPServerConfig]:
    """Load strictly; a corrupt registry is never treated as empty."""
    path = _registry_path(root)
    if not path.is_file():
        return []
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError("MCP 配置文件无法读取或格式已损坏") from exc
    if not isinstance(payload, dict) or not isinstance(
        payload.get("servers", []), list
    ):
        raise ValueError("MCP 配置文件必须包含 servers 列表")
    try:
        servers = [MCPServerConfig.model_validate(item) for item in payload["servers"]]
    except Exception as exc:
        raise ValueError("MCP 配置文件包含无效服务器配置") from exc
    names = [item.name for item in servers]
    if len(names) != len(set(names)):
        raise ValueError("MCP 配置文件包含重复的服务器名称")
    return servers


def save_custom(root: Path, servers: list[MCPServerConfig]) -> None:
    """Persist through a same-directory temporary file and atomic replace."""
    path = _registry_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"servers": [server.model_dump(mode="json") for server in servers]}
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            yaml.safe_dump(payload, stream, allow_unicode=True, sort_keys=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _builtin_servers(*, business_enabled: bool = True) -> list[dict[str, Any]]:
    agents = {
        WorkerName.FINANCE_SALES.value: ("财务与销售", "收入、毛利、赢单与回款"),
        WorkerName.CUSTOMER_PRODUCT.value: ("客户与产品", "续费、使用与客户服务"),
        WorkerName.DELIVERY.value: ("项目交付", "验收、延期与交付成本"),
    }
    servers: list[dict[str, Any]] = [
        {
            "name": "weather",
            "display_name": "天气查询 MCP",
            "description": "基于 Open-Meteo 的实时天气服务，在天气问题中按需连接。",
            "type": "builtin",
            "enabled": True,
            "runtime_status": "on_demand",
            "transport": "stdio",
            "connection": "python -m bizinsight.mcp.weather_server",
            "targets": ["BizInsightSupervisor"],
            "tools": [
                {"name": "resolve_weather_location", "description": "解析地点坐标"},
                {"name": "get_weather", "description": "获取实时天气与预报"},
            ],
            "last_probe": {"status": "never", "error": None},
        }
    ]
    for target, (label, summary) in agents.items():
        scope = MCP_SCOPES[target]
        servers.append(
            {
                "name": f"business_{target}",
                "display_name": f"业务数据 MCP · {label}",
                "description": f"{summary}的只读分析工具，在经营分析任务中按需连接。",
                "type": "builtin",
                "enabled": business_enabled,
                "runtime_status": "on_demand" if business_enabled else "disabled",
                "transport": "stdio",
                "connection": f"python -m bizinsight.mcp.server --scope {target}",
                "scope": target,
                "targets": [target],
                "authorized_datasets": sorted(scope["datasets"]),
                "authorized_metrics": sorted(scope["metrics"]),
                "tools": [
                    {"name": name, "description": "内置只读经营分析工具"}
                    for name in TOOL_NAMES
                ],
                "last_probe": {"status": "never", "error": None},
            }
        )
    return servers


def list_all(root: Path, *, business_enabled: bool = True) -> list[dict[str, Any]]:
    return _builtin_servers(business_enabled=business_enabled) + [
        item.public_dict() for item in load_custom(root)
    ]


def add_custom(root: Path, config: MCPServerConfig) -> MCPServerConfig:
    servers = load_custom(root)
    builtin_names = {item["name"] for item in _builtin_servers()}
    exists = config.name in builtin_names or any(
        item.name == config.name for item in servers
    )
    if exists:
        raise ValueError(f"服务器名称已存在：{config.name}")
    servers.append(config)
    save_custom(root, servers)
    return config


def get_custom(root: Path, name: str) -> MCPServerConfig:
    for server in load_custom(root):
        if server.name == name:
            return server
    raise KeyError(f"自定义服务器不存在：{name}")


def update_custom(root: Path, name: str, changes: dict[str, Any]) -> MCPServerConfig:
    servers = load_custom(root)
    for index, server in enumerate(servers):
        if server.name == name:
            forbidden = set(changes) - {"enabled", "targets"}
            if forbidden:
                raise ValueError(f"不允许修改字段：{', '.join(sorted(forbidden))}")
            values = server.model_dump()
            values.update(changes)
            updated = MCPServerConfig.model_validate(values)
            servers[index] = updated
            save_custom(root, servers)
            return updated
    raise KeyError(f"自定义服务器不存在：{name}")


def record_probe(
    root: Path,
    name: str,
    *,
    tools: list[dict[str, Any]],
    status: Literal["ok", "error"],
    duration_ms: int,
    error: str | None = None,
) -> MCPServerConfig:
    servers = load_custom(root)
    for index, server in enumerate(servers):
        if server.name == name:
            values = server.model_dump()
            if status == "ok":
                values["tools"] = tools
            values["last_probe"] = ProbeSnapshot(
                status=status,
                checked_at=datetime.now(UTC).isoformat(),
                duration_ms=duration_ms,
                error=error,
            )
            updated = MCPServerConfig.model_validate(values)
            servers[index] = updated
            save_custom(root, servers)
            return updated
    raise KeyError(f"自定义服务器不存在：{name}")


def delete_custom(root: Path, name: str) -> None:
    servers = load_custom(root)
    filtered = [item for item in servers if item.name != name]
    if len(filtered) == len(servers):
        raise KeyError(f"自定义服务器不存在：{name}")
    save_custom(root, filtered)


__all__ = [
    "MCP_TARGETS",
    "MCPServerConfig",
    "ProbeSnapshot",
    "add_custom",
    "delete_custom",
    "get_custom",
    "list_all",
    "load_custom",
    "record_probe",
    "save_custom",
    "update_custom",
]
