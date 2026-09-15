from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from bizinsight.mcp_registry import (
    MCPServerConfig,
    add_custom,
    delete_custom,
    list_all,
    load_custom,
    record_probe,
    update_custom,
)


def _config(**changes) -> MCPServerConfig:
    values = {
        "name": "demo",
        "display_name": "Demo MCP",
        "transport": "stdio",
        "command": "python",
        "args": ["-m", "demo_server"],
        "targets": ["BizInsightSupervisor"],
    }
    values.update(changes)
    return MCPServerConfig(**values)


def test_registry_round_trip_update_and_delete(tmp_path: Path) -> None:
    added = add_custom(tmp_path, _config())
    assert added.name == "demo"
    assert load_custom(tmp_path)[0].args == ["-m", "demo_server"]

    updated = update_custom(
        tmp_path,
        "demo",
        {"enabled": False, "targets": ["DeliveryAgent"]},
    )
    assert updated.enabled is False
    assert updated.targets == ["DeliveryAgent"]

    probed = record_probe(
        tmp_path,
        "demo",
        tools=[{"name": "lookup", "description": "Look up data"}],
        status="ok",
        duration_ms=17,
    )
    assert probed.tools[0]["name"] == "lookup"
    assert probed.last_probe.status == "ok"

    delete_custom(tmp_path, "demo")
    assert load_custom(tmp_path) == []


def test_registry_rejects_corruption_instead_of_overwriting(tmp_path: Path) -> None:
    path = tmp_path / "config" / "mcp_servers.yaml"
    path.parent.mkdir()
    path.write_text("servers: [broken", encoding="utf-8")
    with pytest.raises(ValueError, match="损坏"):
        load_custom(tmp_path)
    with pytest.raises(ValueError, match="损坏"):
        add_custom(tmp_path, _config())
    assert path.read_text(encoding="utf-8") == "servers: [broken"


def test_config_validates_transport_targets_and_sse_url() -> None:
    with pytest.raises(ValidationError):
        _config(targets=["ExternalResearchAgent"])
    with pytest.raises(ValidationError):
        _config(transport="streamable_http", command=None, url="file:///secret")
    with pytest.raises(ValidationError, match="/sse"):
        _config(transport="sse", command=None, url="https://example.com/mcp")


def test_builtin_scopes_match_runtime_contract(tmp_path: Path) -> None:
    servers = list_all(tmp_path)
    business = [item for item in servers if item["name"].startswith("business_")]
    assert {item["scope"] for item in business} == {
        "FinanceSalesAgent",
        "CustomerProductAgent",
        "DeliveryAgent",
    }
    assert all(item["runtime_status"] == "on_demand" for item in business)


def test_public_payload_never_exposes_credential_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEMO_SECRET", "do-not-return-this")
    config = _config(api_key_env="DEMO_SECRET")
    payload = config.public_dict()
    assert payload["credential_configured"] is True
    assert "do-not-return-this" not in str(payload)
