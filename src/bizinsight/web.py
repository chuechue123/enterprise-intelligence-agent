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
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import uuid4

from agentscope.message import UserMsg
from agentscope.state import AgentState
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

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


class _WebAgent(Protocol):
    last_route: str

    async def reply(self, inputs: Any = None, structured_schema: Any = None) -> Any: ...


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
        async with self._registry_lock:
            entry = self._entries.get(session_id)
            if entry is None:
                agent = self._factory(session_id)
                if inspect.isawaitable(agent):
                    agent = await agent
                entry = _SessionEntry(agent=agent)
                self._entries[session_id] = entry
                while len(self._entries) > self._capacity:
                    self._entries.popitem(last=False)
            else:
                self._entries.move_to_end(session_id)
            entry.last_used = time.monotonic()
            return entry


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
    def build(session_id: str) -> _WebAgent:
        from bizinsight.agents.supervisor import SupervisorAgent
        from bizinsight.app import build_dashscope_model

        settings = BizInsightSettings()
        return SupervisorAgent(
            name="BizInsightSupervisor",
            model=build_dashscope_model(settings),
            project_root=project_root,
            state=AgentState(session_id=session_id),
            settings=settings,
        )

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

    app.mount(
        "/bizinsight/assets",
        StaticFiles(directory=web_root),
        name="bizinsight-assets",
    )

    async def workbench() -> FileResponse:
        return FileResponse(web_root / "index.html")

    async def knowledge_page() -> FileResponse:
        return FileResponse(web_root / "knowledge.html")

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
        "/bizinsight/knowledge/documents",
        knowledge_documents,
        methods=["GET"],
        response_model=KnowledgeDocumentPage,
        tags=["BizInsight"],
    )
    app.add_api_route(
        "/bizinsight/chat",
        chat,
        methods=["POST"],
        response_model=ChatResponse,
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
