"""Self-contained web workbench adapter for the existing SupervisorAgent."""

from __future__ import annotations

import asyncio
import inspect
import json
import math
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import uuid4

from agentscope.message import UserMsg
from agentscope.state import AgentState
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

from bizinsight.config import BizInsightSettings


class ChatRequest(BaseModel):
    """Validated browser request passed to one isolated Supervisor session."""

    question: str = Field(min_length=1, max_length=8_000)
    session_id: str | None = Field(default=None, min_length=1, max_length=80)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("问题不能为空")
        return value

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("会话 ID 不能为空")
        if not all(char.isalnum() or char in "_-" for char in value):
            raise ValueError("会话 ID 只能包含字母、数字、下划线和连字符")
        return value


class ExecutionNode(BaseModel):
    """One workflow node proven by the run telemetry."""

    key: str
    agent_name: str
    status: Literal["success", "failed", "not_called"]
    summary: str
    duration_ms: float | None = None
    evidence_types: list[str] = Field(default_factory=list)


class ExecutionFlow(BaseModel):
    """Truthful post-run workflow state for the browser."""

    duration_ms: float | None = None
    nodes: list[ExecutionNode]
    phases: dict[str, bool]


class ChatResponse(BaseModel):
    """Stable response contract consumed by the local workbench."""

    session_id: str
    answer: str
    route: str
    report_url: str | None = None
    run_id: str | None = None
    review_status: str | None = None
    executed_agents: list[str] = Field(default_factory=list)
    execution_flow: ExecutionFlow


class KnowledgeDocumentItem(BaseModel):
    """One safe, display-ready document from the local RAG index."""

    document_id: str
    title: str
    document_type: str
    status: Literal["ready"] = "ready"
    updated_at: str
    source_path: str


class KnowledgeDocumentPage(BaseModel):
    """Paginated knowledge document response consumed by the browser."""

    items: list[KnowledgeDocumentItem]
    total: int
    page: int
    page_size: int
    pages: int


class MCPServerRequest(BaseModel):
    """Untrusted MCP definition accepted from the control center."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=48, pattern=r"^[A-Za-z0-9_-]+$")
    display_name: str = Field(default="", max_length=80)
    description: str = Field(default="", max_length=400)
    transport: Literal["stdio", "streamable_http", "sse"]
    command: str | None = Field(default=None, max_length=500)
    args: list[str] = Field(default_factory=list, max_length=64)
    url: str | None = Field(default=None, max_length=2000)
    api_key_env: str | None = Field(default=None, max_length=100)
    targets: list[str] = Field(min_length=1, max_length=4)


class MCPServerUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool | None = None
    targets: list[str] | None = Field(default=None, min_length=1, max_length=4)

    @model_validator(mode="after")
    def require_change(self) -> MCPServerUpdateRequest:
        if self.enabled is None and self.targets is None:
            raise ValueError("至少提供 enabled 或 targets")
        return self


class _WebAgent(Protocol):
    last_route: str

    async def reply(self, inputs: Any = None, structured_schema: Any = None) -> Any: ...

    async def close(self) -> None: ...


AgentFactory = Callable[[str], _WebAgent]


@dataclass
class _SessionEntry:
    agent: _WebAgent
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_used: float = field(default_factory=time.monotonic)


class WebSessionRegistry:
    """Keep a bounded set of stateful agents for browser conversations."""

    def __init__(self, factory: AgentFactory, *, capacity: int = 64) -> None:
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self._factory = factory
        self._capacity = capacity
        self._entries: OrderedDict[str, _SessionEntry] = OrderedDict()
        self._registry_lock = asyncio.Lock()

    async def get(self, session_id: str) -> _SessionEntry:
        evicted: list[_SessionEntry] = []
        async with self._registry_lock:
            entry = self._entries.get(session_id)
            if entry is None:
                agent = self._factory(session_id)
                if inspect.isawaitable(agent):
                    agent = await agent
                entry = _SessionEntry(agent=agent)
                self._entries[session_id] = entry
                while len(self._entries) > self._capacity:
                    _, removed = self._entries.popitem(last=False)
                    evicted.append(removed)
            else:
                self._entries.move_to_end(session_id)
            entry.last_used = time.monotonic()
        for removed in evicted:
            close = getattr(removed.agent, "close", None)
            if close is not None:
                await close()
        return entry

    @property
    def session_count(self) -> int:
        return len(self._entries)

    async def close(self) -> None:
        """Close all stateful agents when the application shuts down."""
        async with self._registry_lock:
            entries = list(self._entries.values())
            self._entries.clear()
        for entry in entries:
            close = getattr(entry.agent, "close", None)
            if close is not None:
                await close()


def _safe_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _validate_report_url(value: Any) -> str | None:
    url = _safe_optional_text(value)
    if url is None:
        return None
    if not url.startswith("/bizinsight/reports/") or ".." in url:
        return None
    return url


_FLOW_NODES = (
    ("supervisor", "BizInsightLeader"),
    ("finance", "FinanceSalesAgent"),
    ("customer", "CustomerProductAgent"),
    ("delivery", "DeliveryAgent"),
    ("external", "ExternalResearchAgent"),
    ("reviewer", "EvidenceReviewerAgent"),
)
_WORKER_NAMES = {
    name for key, name in _FLOW_NODES if key not in {"supervisor", "reviewer"}
}


def _knowledge_document_type(document: dict[str, Any]) -> str:
    """Map internal metadata to a small, stable set of UI categories."""

    searchable = " ".join(
        str(document.get(field, ""))
        for field in ("document_id", "title", "department", "relative_path")
    ).casefold()
    rules = (
        (("incident", "故障", "复盘"), "技术文档"),
        (("operations-plan", "经营计划", "运营计划"), "经营计划"),
        (("customer-interview", "客户访谈"), "客户资料"),
        (("market", "competitor", "竞品", "行业"), "行业研究"),
        (("product", "release", "cloudflow"), "产品文档"),
        (("sla", "policy", "制度", "协议", "管理办法"), "制度文档"),
    )
    for needles, category in rules:
        if any(needle in searchable for needle in needles):
            return category
    return "内部资料"


def _load_knowledge_documents(project_root: Path) -> list[KnowledgeDocumentItem]:
    """Load and validate the public subset of the deterministic RAG manifest."""

    index_path = project_root / "data" / "knowledge" / "index.json"
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    raw_documents = payload.get("documents")
    if not isinstance(raw_documents, list):
        raise ValueError("knowledge index has no document manifest")

    documents: dict[str, KnowledgeDocumentItem] = {}
    for raw in raw_documents:
        if not isinstance(raw, dict):
            raise ValueError("knowledge document metadata must be an object")
        required = ("document_id", "title", "date", "relative_path")
        if any(not str(raw.get(field, "")).strip() for field in required):
            raise ValueError("knowledge document metadata is incomplete")
        document_id = str(raw["document_id"]).strip()
        source_path = str(raw["relative_path"]).strip().replace("\\", "/")
        source = Path(source_path)
        if source.is_absolute() or ".." in source.parts:
            raise ValueError("knowledge source path is unsafe")
        documents.setdefault(
            document_id,
            KnowledgeDocumentItem(
                document_id=document_id,
                title=str(raw["title"]).strip(),
                document_type=_knowledge_document_type(raw),
                updated_at=str(raw["date"]).strip(),
                source_path=source.as_posix(),
            ),
        )
    return sorted(
        documents.values(),
        key=lambda item: (item.updated_at, item.document_id),
        reverse=True,
    )


def _knowledge_document_page(
    project_root: Path,
    *,
    query: str,
    page: int,
    page_size: int,
) -> KnowledgeDocumentPage:
    documents = _load_knowledge_documents(project_root)
    normalized_query = query.strip().casefold()
    if normalized_query:
        documents = [
            item
            for item in documents
            if normalized_query
            in " ".join(
                (item.document_id, item.title, item.document_type)
            ).casefold()
        ]
    total = len(documents)
    pages = max(1, math.ceil(total / page_size))
    start = (page - 1) * page_size
    return KnowledgeDocumentPage(
        items=documents[start : start + page_size],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


def _empty_execution_flow(*, report_generated: bool = False) -> ExecutionFlow:
    return ExecutionFlow(
        nodes=[
            ExecutionNode(
                key=key,
                agent_name=agent_name,
                status="not_called",
                summary="本次未调用",
            )
            for key, agent_name in _FLOW_NODES
        ],
        phases={
            "planned": False,
            "workers": False,
            "reviewed": False,
            "report": report_generated,
        },
    )


def _execution_flow(
    project_root: Path,
    session_id: str,
    run_id: str | None,
    *,
    report_generated: bool,
) -> ExecutionFlow:
    """Convert the workflow telemetry into display-safe, factual node states."""

    if run_id is None:
        return _empty_execution_flow(report_generated=report_generated)
    telemetry_path = (
        project_root / "outputs" / session_id / f"{session_id}.telemetry.json"
    )
    try:
        payload = json.loads(telemetry_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return _empty_execution_flow(report_generated=report_generated)
    if payload.get("run_id") != run_id:
        return _empty_execution_flow(report_generated=report_generated)
    agents = payload.get("agents", [])
    if not isinstance(agents, list):
        return _empty_execution_flow(report_generated=report_generated)

    by_name = {
        str(item["agent_name"]): item
        for item in agents
        if isinstance(item, dict) and item.get("agent_name")
    }
    nodes: list[ExecutionNode] = []
    for key, agent_name in _FLOW_NODES:
        item = by_name.get(agent_name)
        if item is None:
            nodes.append(
                ExecutionNode(
                    key=key,
                    agent_name=agent_name,
                    status="not_called",
                    summary="本次未调用",
                )
            )
            continue
        tool_calls = item.get("tool_calls", [])
        evidence_types = sorted(
            {
                str(tool.get("tool_name", "")).removeprefix("evidence:")
                for tool in tool_calls
                if isinstance(tool, dict)
                and str(tool.get("tool_name", "")).startswith("evidence:")
            }
        )
        failed = bool(item.get("error"))
        raw_duration = item.get("duration_ms")
        duration_ms = (
            float(raw_duration) if isinstance(raw_duration, int | float) else None
        )
        nodes.append(
            ExecutionNode(
                key=key,
                agent_name=agent_name,
                status="failed" if failed else "success",
                summary=f"{agent_name}（调用失败）" if failed else agent_name,
                duration_ms=duration_ms,
                evidence_types=evidence_types,
            )
        )

    called_names = set(by_name)
    raw_total = payload.get("duration_ms")
    total_duration = float(raw_total) if isinstance(raw_total, int | float) else None
    return ExecutionFlow(
        duration_ms=total_duration,
        nodes=nodes,
        phases={
            "planned": "BizInsightLeader" in called_names,
            "workers": bool(called_names & _WORKER_NAMES),
            "reviewed": "EvidenceReviewerAgent" in called_names,
            "report": report_generated,
        },
    )


def _default_agent_factory(project_root: Path) -> AgentFactory:
    async def build(session_id: str) -> _WebAgent:
        from bizinsight.agents.supervisor import SupervisorAgent
        from bizinsight.app import build_dashscope_model

        settings = BizInsightSettings()
        agent = SupervisorAgent(
            name="BizInsightSupervisor",
            model=build_dashscope_model(settings),
            project_root=project_root,
            state=AgentState(session_id=session_id),
            settings=settings,
        )
        await agent.attach_custom_mcps()
        return agent

    return build


def attach_web_workbench(
    app: FastAPI,
    *,
    project_root: Path,
    agent_factory: AgentFactory | None = None,
) -> WebSessionRegistry:
    """Attach the browser UI and chat adapter to an existing FastAPI app."""

    root = project_root.resolve()
    web_root = Path(__file__).resolve().parent / "web"
    registry = WebSessionRegistry(agent_factory or _default_agent_factory(root))
    app.router.add_event_handler("shutdown", registry.close)

    app.mount(
        "/bizinsight/assets",
        StaticFiles(directory=web_root),
        name="bizinsight-assets",
    )
    outputs_dir = root / "outputs"
    if outputs_dir.is_dir():
        app.mount(
            "/bizinsight/reports",
            StaticFiles(directory=str(outputs_dir)),
            name="bizinsight-reports",
        )

    async def workbench() -> FileResponse:
        return FileResponse(web_root / "index.html")

    async def knowledge_page() -> FileResponse:
        return FileResponse(web_root / "knowledge.html")

    async def report_page() -> FileResponse:
        return FileResponse(web_root / "report.html")

    async def mcp_page() -> FileResponse:
        return FileResponse(web_root / "mcp.html")

    async def report_list() -> list[dict[str, Any]]:
        """List all generated reports sorted by mtime descending."""
        from datetime import datetime as _dt
        reports_root = root / "outputs"
        items: list[dict[str, Any]] = []
        if not reports_root.is_dir():
            return items
        for run_dir in sorted(reports_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not run_dir.is_dir():
                continue
            html = run_dir / "report.html"
            md = run_dir / "report.md"
            if not html.is_file():
                continue
            mtime = run_dir.stat().st_mtime
            title = run_dir.name
            excerpt = ""
            if md.is_file():
                try:
                    lines = md.read_text(encoding="utf-8").splitlines()
                    if lines and lines[0].startswith("# "):
                        title = lines[0][2:].strip() or title
                    for line in lines[:6]:
                        if line.startswith("> 分析问题："):
                            excerpt = line.replace("> 分析问题：", "").strip()
                            break
                except (OSError, UnicodeDecodeError):
                    pass
            if run_dir.name.startswith(".pytest") or run_dir.name.startswith("evaluation"):
                continue
            items.append({
                "run_id": run_dir.name,
                "title": title,
                "excerpt": excerpt,
                "generated_at": _dt.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M"),
                "html_url": f"/bizinsight/reports/{run_dir.name}/report.html",
                "md_url": f"/bizinsight/reports/{run_dir.name}/report.md",
            })
        return items

    async def report_delete(run_id: str) -> dict[str, Any]:
        """Delete a generated report by run_id."""
        import shutil

        # Guard: never escape outputs/, refuse obvious non-run_id values.
        if not run_id or ".." in run_id or "/" in run_id or "\\" in run_id:
            raise HTTPException(status_code=400, detail="无效的报告标识符")
        reports_root = root / "outputs"
        target = reports_root / run_id
        if not target.is_dir():
            raise HTTPException(status_code=404, detail="报告不存在")
        if not (target / "report.html").is_file():
            raise HTTPException(status_code=404, detail="报告目录不完整")
        try:
            shutil.rmtree(target)
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"删除失败：{exc}")
        return {"run_id": run_id, "deleted": True}

    # ----------------------------- MCP servers ------------------------------

    def _mcp_registry():
        """Lazy import so the registry module stays optional at import time."""
        import bizinsight.mcp_registry as reg
        return reg

    def _mcp_config(payload: MCPServerRequest):
        import bizinsight.mcp_registry as reg

        return reg.MCPServerConfig(**payload.model_dump())

    def _mcp_change_response(server: Any) -> dict[str, Any]:
        return {
            "server": server.public_dict(),
            "requires_new_session": registry.session_count > 0,
            "affected_sessions": registry.session_count,
        }

    async def mcp_servers_list() -> dict[str, Any]:
        reg = _mcp_registry()
        try:
            servers = reg.list_all(
                root,
                business_enabled=BizInsightSettings().enable_business_mcp,
            )
        except ValueError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        healthy = sum(
            1
            for item in servers
            if item.get("last_probe", {}).get("status") == "ok"
            and item.get("enabled")
        )
        return {
            "servers": servers,
            "targets": [
                {"id": "BizInsightSupervisor", "label": "Supervisor"},
                {"id": "FinanceSalesAgent", "label": "财务与销售 Agent"},
                {"id": "CustomerProductAgent", "label": "客户与产品 Agent"},
                {"id": "DeliveryAgent", "label": "项目交付 Agent"},
            ],
            "summary": {
                "configured": len(servers),
                "healthy": healthy,
                "tools": sum(len(item.get("tools") or []) for item in servers),
                "active_sessions": registry.session_count,
            },
        }

    async def mcp_probe(payload: MCPServerRequest) -> dict[str, Any]:
        from bizinsight.mcp.custom import probe_server

        try:
            config = _mcp_config(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return await probe_server(config, project_root=root)

    async def mcp_server_add(payload: MCPServerRequest) -> dict[str, Any]:
        import bizinsight.mcp_registry as reg
        from bizinsight.mcp.custom import probe_server

        try:
            config = _mcp_config(payload)
            result = await probe_server(config, project_root=root)
            if not result["ok"]:
                raise HTTPException(status_code=422, detail=result["error"])
            values = config.model_dump()
            values["tools"] = result["tools"]
            values["last_probe"] = {
                "status": "ok",
                "checked_at": datetime.now(UTC).isoformat(),
                "duration_ms": result["duration_ms"],
            }
            saved = reg.add_custom(root, reg.MCPServerConfig.model_validate(values))
            return _mcp_change_response(saved)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def mcp_server_delete(name: str) -> dict[str, Any]:
        import bizinsight.mcp_registry as reg

        name = name.strip()
        if not name or ".." in name:
            raise HTTPException(status_code=400, detail="无效的服务器标识符")
        try:
            reg.delete_custom(root, name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "name": name,
            "deleted": True,
            "requires_new_session": registry.session_count > 0,
            "affected_sessions": registry.session_count,
        }

    async def mcp_server_update(
        name: str, payload: MCPServerUpdateRequest
    ) -> dict[str, Any]:
        import bizinsight.mcp_registry as reg

        name = name.strip()
        if not name or ".." in name:
            raise HTTPException(status_code=400, detail="无效的服务器标识符")
        try:
            changes = payload.model_dump(exclude_none=True)
            return _mcp_change_response(reg.update_custom(root, name, changes))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    async def mcp_server_probe(name: str) -> dict[str, Any]:
        import bizinsight.mcp_registry as reg
        from bizinsight.mcp.custom import probe_server

        try:
            config = reg.get_custom(root, name)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        result = await probe_server(config, project_root=root)
        updated = reg.record_probe(
            root,
            name,
            tools=result["tools"],
            status="ok" if result["ok"] else "error",
            duration_ms=result["duration_ms"],
            error=result["error"],
        )
        return {"probe": result, "server": updated.public_dict()}

    # ----------------------------- Knowledge ------------------------------

    async def knowledge_documents(
        query: str = Query(default="", max_length=200),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=10, ge=1, le=50),
    ) -> KnowledgeDocumentPage:
        try:
            return _knowledge_document_page(
                root,
                query=query,
                page=page,
                page_size=page_size,
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=503,
                detail="知识库索引暂不可用",
            ) from exc

    async def knowledge_document_download(document_id: str) -> FileResponse:
        """Download a knowledge document by its ID."""
        try:
            documents = _load_knowledge_documents(root)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=503,
                detail="知识库索引暂不可用",
            ) from exc

        target = next((d for d in documents if d.document_id == document_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail="文档不存在")

        knowledge_dir = root / "data" / "knowledge"
        file_path = (knowledge_dir / target.source_path).resolve()

        # Security: ensure the resolved path is inside knowledge_dir
        try:
            file_path.relative_to(knowledge_dir.resolve())
        except ValueError:
            raise HTTPException(status_code=400, detail="非法路径")

        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="文档文件不存在")

        filename = Path(target.source_path).name
        return FileResponse(
            path=str(file_path),
            filename=filename,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    async def _rebuild_knowledge_indexes(
        knowledge_dir: Path, index_path: Path
    ) -> dict[str, str | None]:
        """Rebuild BM25 lexical (always) + Qdrant vector (best-effort, degrades gracefully)."""
        from bizinsight.tools.knowledge import build_knowledge_index

        import asyncio as _asyncio

        try:
            await _asyncio.to_thread(build_knowledge_index, knowledge_dir, index_path)
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"知识库索引重建失败: {exc}",
            ) from exc

        vector_status = "skipped"
        vector_error = None
        try:
            settings = BizInsightSettings()
            settings.require_online_embedding()
            from bizinsight.rag.vector_index import AgentScopeVectorIndex

            vector_dir = root / "data" / "knowledge" / "vector"
            qdrant_dir = vector_dir / "qdrant"
            manifest_path = vector_dir / "manifest.json"

            if qdrant_dir.exists():
                import shutil

                shutil.rmtree(qdrant_dir, ignore_errors=True)
            if manifest_path.exists():
                manifest_path.unlink(missing_ok=True)

            vector_index = AgentScopeVectorIndex.from_settings(
                settings=settings,
                index_dir=vector_dir,
            )
            async with vector_index:
                await vector_index.build_from_json(
                    lexical_index_path=index_path,
                    manifest_path=manifest_path,
                    settings=settings,
                )
            vector_status = "ok"
        except ValueError as exc:
            vector_status = "skipped"
            vector_error = str(exc)
        except Exception as exc:
            vector_status = "degraded"
            vector_error = f"{type(exc).__name__}: {exc}"

        return {"vector_status": vector_status, "vector_error": vector_error}

    async def knowledge_document_delete(document_id: str) -> dict[str, Any]:
        """Delete a knowledge document and rebuild BM25 + vector indexes.

        Robust against index.json drift: also scans on-disk files for a
        matching document_id in YAML front-matter, so orphan files left
        behind by a prior failed rebuild still get cleaned up.
        """
        knowledge_dir = root / "data" / "knowledge"
        knowledge_dir_resolved = knowledge_dir.resolve()

        # Try 1: find in the current index.json
        on_disk_files: list[Path] = []
        target_title = ""
        found_source: str | None = None
        try:
            documents = _load_knowledge_documents(root)
            target = next((d for d in documents if d.document_id == document_id), None)
            if target is not None:
                found_source = target.source_path
                target_title = target.title
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass

        # Try 2: scan on-disk md files for the document_id in front-matter
        if found_source is None:
            import yaml as _yaml

            for path in sorted(knowledge_dir.rglob("*.md")):
                if "external_fallback" in path.parts:
                    continue
                try:
                    lines = path.read_text(encoding="utf-8").splitlines()
                    if (
                        len(lines) >= 4
                        and lines[0].strip() == "---"
                        and any(line.strip() == "---" for line in lines[1:])
                    ):
                        closing = next(
                            i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"
                        )
                        meta = _yaml.safe_load("\n".join(lines[1:closing])) or {}
                        if str(meta.get("document_id", "")).strip() == document_id:
                            found_source = path.name
                            target_title = str(meta.get("title", path.stem)).strip()
                            break
                except Exception:
                    continue

        if found_source is None:
            raise HTTPException(status_code=404, detail="文档不存在")

        file_path = (knowledge_dir / found_source).resolve()
        try:
            file_path.relative_to(knowledge_dir_resolved)
        except ValueError:
            raise HTTPException(status_code=400, detail="非法路径")

        actually_deleted = False
        if file_path.is_file():
            try:
                file_path.unlink()
                actually_deleted = True
            except OSError as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"删除文件失败: {exc}",
                ) from exc

        index_path = knowledge_dir / "index.json"
        rebuild = await _rebuild_knowledge_indexes(knowledge_dir, index_path)

        return {
            "document_id": document_id,
            "title": target_title or Path(found_source).stem,
            "deleted": True,
            "file_was_present": actually_deleted,
            "index_rebuilt": True,
            "vector_status": rebuild["vector_status"],
            "vector_error": rebuild["vector_error"],
        }

    async def knowledge_document_upload(file: UploadFile = File(...)) -> dict:
        """Upload a Markdown document, auto-add front-matter, rebuild BM25 + vector indexes."""
        # Validate filename
        safe_name = Path(file.filename or "").name
        if not safe_name or ".." in safe_name or "/" in safe_name or "\\" in safe_name:
            raise HTTPException(status_code=400, detail="无效的文件名")

        # Validate extension (knowledge pipeline only supports Markdown)
        allowed_ext = {".md", ".markdown"}
        ext = Path(safe_name).suffix.lower()
        if ext not in allowed_ext:
            raise HTTPException(
                status_code=400,
                detail="当前仅支持 Markdown (.md / .markdown) 文件上传。",
            )

        # Validate size (max 10 MB)
        raw_bytes = await file.read()
        if len(raw_bytes) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="文件超过 10MB 限制")
        if len(raw_bytes) == 0:
            raise HTTPException(status_code=400, detail="文件为空")

        # Decode and ensure YAML front-matter (required by the indexer)
        import hashlib
        from datetime import datetime

        import yaml

        knowledge_dir = root / "data" / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        index_path = knowledge_dir / "index.json"

        # ---- Duplicate detection: filename ----
        save_path = knowledge_dir / safe_name
        if save_path.exists():
            raise HTTPException(
                status_code=409,
                detail=f"文件 '{safe_name}' 已存在。请先删除旧文件，或修改文件名后再上传。",
            )

        body_text = raw_bytes.decode("utf-8-sig").strip()
        doc_title = save_path.stem

        # Check if the file already has valid YAML front-matter
        lines = body_text.splitlines()
        has_front = (
            len(lines) >= 4
            and lines[0].strip() == "---"
            and any(line.strip() == "---" for line in lines[1:])
        )

        if has_front:
            # Validate and normalise the document_id in existing front-matter
            try:
                closing = next(
                    i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"
                )
                meta = yaml.safe_load("\n".join(lines[1:closing])) or {}
                existing_id = str(meta.get("document_id", "")).strip()
                existing_title = str(meta.get("title", "")).strip() or doc_title
                existing_date = str(meta.get("date", "")).strip() or datetime.now().strftime(
                    "%Y-%m-%d"
                )
                existing_dept = str(meta.get("department", "")).strip() or "用户上传"
                body_only = "\n".join(lines[closing + 1 :]).strip()
            except Exception:
                has_front = False  # fall through to rebuild front-matter

        if not has_front:
            # Generate compliant metadata
            doc_id = f"DOC-USER-{datetime.now().strftime('%Y%m%d')}-{hashlib.md5(save_path.name.encode()).hexdigest()[:4].upper()}"
            document_id = doc_id
            front_matter = {
                "document_id": document_id,
                "title": doc_title,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "department": "用户上传",
            }
            body_only = body_text
            final_text = "---\n" + yaml.safe_dump(front_matter, allow_unicode=True, sort_keys=False) + "---\n\n" + body_only + "\n"
        else:
            # Ensure document_id is compliant with DOC-* pattern
            import re

            doc_id_pattern = re.compile(r"^DOC-[A-Z0-9]+(?:-[A-Z0-9]+)*$")
            document_id = (
                existing_id
                if doc_id_pattern.fullmatch(existing_id or "")
                else f"DOC-USER-{datetime.now().strftime('%Y%m%d')}-{hashlib.md5(save_path.name.encode()).hexdigest()[:4].upper()}"
            )
            if not doc_id_pattern.fullmatch(existing_id or "") or existing_id != document_id:
                # Rebuild front-matter with corrected id
                front_matter = {
                    "document_id": document_id,
                    "title": existing_title,
                    "date": existing_date,
                    "department": existing_dept,
                }
                final_text = "---\n" + yaml.safe_dump(front_matter, allow_unicode=True, sort_keys=False) + "---\n\n" + body_only + "\n"
            else:
                final_text = body_text + ("\n" if not body_text.endswith("\n") else "")

        # ---- Duplicate detection: document_id ----
        try:
            existing_index = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing_index = {}
        existing_doc_ids = {
            str(d.get("document_id"))
            for d in existing_index.get("documents", [])
            if isinstance(d, dict) and d.get("document_id")
        }
        if document_id in existing_doc_ids:
            raise HTTPException(
                status_code=409,
                detail=f"document_id '{document_id}' 已被占用。请修改文档中的 ID（Front-Matter）后重试。",
            )

        save_path.write_text(final_text, encoding="utf-8")

        # Rebuild indexes (BM25 always, vector best-effort)
        rebuild = await _rebuild_knowledge_indexes(knowledge_dir, index_path)

        return {
            "document_id": document_id,
            "title": doc_title,
            "filename": save_path.name,
            "size": len(raw_bytes),
            "index_rebuilt": True,
            "vector_status": rebuild["vector_status"],
            "vector_error": rebuild["vector_error"],
        }

    async def chat(payload: ChatRequest) -> ChatResponse:
        session_id = payload.session_id or f"web-{uuid4().hex}"
        try:
            entry = await registry.get(session_id)
            async with entry.lock:
                message = await entry.agent.reply(
                    UserMsg(name="user", content=payload.question)
                )
                entry.last_used = time.monotonic()
        except (KeyboardInterrupt, asyncio.CancelledError):
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="智能体暂时无法完成本次请求，请检查在线模型配置后重试。",
            ) from exc

        answer = message.get_text_content().strip()
        metadata = getattr(message, "metadata", {}) or {}
        run_id = _safe_optional_text(metadata.get("run_id"))
        report_url = _validate_report_url(metadata.get("bizinsight_report"))
        execution_flow = _execution_flow(
            root,
            session_id,
            run_id,
            report_generated=report_url is not None,
        )
        return ChatResponse(
            session_id=session_id,
            answer=answer or "智能体已完成处理，但没有返回可显示的文本。",
            route=_safe_optional_text(entry.agent.last_route) or "general",
            report_url=report_url,
            run_id=run_id,
            review_status=_safe_optional_text(metadata.get("review_status")),
            executed_agents=[
                node.agent_name
                for node in execution_flow.nodes
                if node.status != "not_called"
            ],
            execution_flow=execution_flow,
        )

    app.add_api_route("/", workbench, methods=["GET"], include_in_schema=False)
    app.add_api_route(
        "/knowledge",
        knowledge_page,
        methods=["GET"],
        include_in_schema=False,
    )
    app.add_api_route(
        "/reports",
        report_page,
        methods=["GET"],
        include_in_schema=False,
    )
    app.add_api_route(
        "/bizinsight/reports",
        report_list,
        methods=["GET"],
        response_model=list[dict[str, Any]],
        tags=["BizInsight"],
    )
    app.add_api_route(
        "/bizinsight/reports/{run_id}",
        report_delete,
        methods=["DELETE"],
        response_model=dict[str, Any],
        tags=["BizInsight"],
    )
    app.add_api_route(
        "/bizinsight/knowledge/documents",
        knowledge_documents,
        methods=["GET"],
        response_model=KnowledgeDocumentPage,
        tags=["BizInsight"],
    )
    app.add_api_route(
        "/bizinsight/knowledge/documents/{document_id:path}/download",
        knowledge_document_download,
        methods=["GET"],
        tags=["BizInsight"],
    )
    app.add_api_route(
        "/bizinsight/knowledge/documents/upload",
        knowledge_document_upload,
        methods=["POST"],
        tags=["BizInsight"],
    )
    app.add_api_route(
        "/bizinsight/knowledge/documents/{document_id:path}",
        knowledge_document_delete,
        methods=["DELETE"],
        tags=["BizInsight"],
    )
    app.add_api_route(
        "/bizinsight/chat",
        chat,
        methods=["POST"],
        response_model=ChatResponse,
        tags=["BizInsight"],
    )
    app.add_api_route(
        "/bizinsight/mcp",
        mcp_page,
        methods=["GET"],
        include_in_schema=False,
    )
    app.add_api_route(
        "/bizinsight/mcp/servers",
        mcp_servers_list,
        methods=["GET"],
        response_model=dict[str, Any],
        tags=["BizInsight"],
    )
    app.add_api_route(
        "/bizinsight/mcp/probe",
        mcp_probe,
        methods=["POST"],
        response_model=dict[str, Any],
        tags=["BizInsight"],
    )
    app.add_api_route(
        "/bizinsight/mcp/servers",
        mcp_server_add,
        methods=["POST"],
        response_model=dict[str, Any],
        tags=["BizInsight"],
    )
    app.add_api_route(
        "/bizinsight/mcp/servers/{name}",
        mcp_server_delete,
        methods=["DELETE"],
        response_model=dict[str, Any],
        tags=["BizInsight"],
    )
    app.add_api_route(
        "/bizinsight/mcp/servers/{name}/probe",
        mcp_server_probe,
        methods=["POST"],
        response_model=dict[str, Any],
        tags=["BizInsight"],
    )
    app.add_api_route(
        "/bizinsight/mcp/servers/{name}",
        mcp_server_update,
        methods=["PUT"],
        response_model=dict[str, Any],
        tags=["BizInsight"],
    )
    return registry


__all__ = [
    "ChatRequest",
    "ChatResponse",
    "ExecutionFlow",
    "ExecutionNode",
    "KnowledgeDocumentItem",
    "KnowledgeDocumentPage",
    "WebSessionRegistry",
    "attach_web_workbench",
]
