"""Self-contained web workbench adapter for the existing SupervisorAgent."""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import uuid4

from agentscope.message import UserMsg
from agentscope.state import AgentState
from fastapi import FastAPI, HTTPException
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
    "WebSessionRegistry",
    "attach_web_workbench",
]
