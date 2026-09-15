from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bizinsight.web import attach_web_workbench


def _payload() -> dict:
    return {
        "name": "demo",
        "display_name": "Demo MCP",
        "description": "A test server",
        "transport": "stdio",
        "command": "python",
        "args": ["-m", "demo"],
        "url": None,
        "api_key_env": None,
        "targets": ["BizInsightSupervisor"],
    }


def test_mcp_create_requires_real_probe_and_persists_tools(
    tmp_path: Path, monkeypatch
) -> None:
    async def fake_probe(config, *, project_root, timeout=12.0):
        assert config.name == "demo"
        assert project_root == tmp_path.resolve()
        return {
            "ok": True,
            "tools": [{"name": "lookup", "description": "Look up data"}],
            "duration_ms": 8,
            "error": None,
        }

    monkeypatch.setattr("bizinsight.mcp.custom.probe_server", fake_probe)
    app = FastAPI()
    attach_web_workbench(app, project_root=tmp_path, agent_factory=lambda _: object())

    with TestClient(app) as client:
        created = client.post("/bizinsight/mcp/servers", json=_payload())
        assert created.status_code == 200
        assert created.json()["server"]["tools"][0]["name"] == "lookup"
        listing = client.get("/bizinsight/mcp/servers").json()
        custom = [item for item in listing["servers"] if item["type"] == "custom"]
        assert custom[0]["targets"] == ["BizInsightSupervisor"]


def test_mcp_create_rejects_failed_probe(tmp_path: Path, monkeypatch) -> None:
    async def fake_probe(config, *, project_root, timeout=12.0):
        return {
            "ok": False,
            "tools": [],
            "duration_ms": 4,
            "error": "连接失败（ConnectionError）",
        }

    monkeypatch.setattr("bizinsight.mcp.custom.probe_server", fake_probe)
    app = FastAPI()
    attach_web_workbench(app, project_root=tmp_path, agent_factory=lambda _: object())
    with TestClient(app) as client:
        response = client.post("/bizinsight/mcp/servers", json=_payload())
        assert response.status_code == 422
        assert not (tmp_path / "config" / "mcp_servers.yaml").exists()


def test_mcp_update_rejects_coerced_boolean(tmp_path: Path, monkeypatch) -> None:
    async def fake_probe(config, *, project_root, timeout=12.0):
        return {"ok": True, "tools": [], "duration_ms": 1, "error": None}

    monkeypatch.setattr("bizinsight.mcp.custom.probe_server", fake_probe)
    app = FastAPI()
    attach_web_workbench(app, project_root=tmp_path, agent_factory=lambda _: object())
    with TestClient(app) as client:
        created = client.post("/bizinsight/mcp/servers", json=_payload())
        assert created.status_code == 200
        response = client.put(
            "/bizinsight/mcp/servers/demo", json={"enabled": "false"}
        )
        assert response.status_code == 422


def test_custom_mcp_can_be_deleted_but_builtin_cannot(
    tmp_path: Path, monkeypatch
) -> None:
    async def fake_probe(config, *, project_root, timeout=12.0):
        return {"ok": True, "tools": [], "duration_ms": 1, "error": None}

    monkeypatch.setattr("bizinsight.mcp.custom.probe_server", fake_probe)
    app = FastAPI()
    attach_web_workbench(app, project_root=tmp_path, agent_factory=lambda _: object())
    with TestClient(app) as client:
        created = client.post("/bizinsight/mcp/servers", json=_payload())
        assert created.status_code == 200
        deleted = client.delete("/bizinsight/mcp/servers/demo")
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True
        assert client.delete("/bizinsight/mcp/servers/weather").status_code == 404
        listing = client.get("/bizinsight/mcp/servers").json()
        assert not [item for item in listing["servers"] if item["type"] == "custom"]
