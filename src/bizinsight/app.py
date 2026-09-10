"""BizInsight application wiring for offline, online and Agent Service use."""

from __future__ import annotations

import json
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from agentscope.agent import Agent, InjectionConfig, ReActConfig
from agentscope.credential import DashScopeCredential
from agentscope.message import UserMsg
from agentscope.model import ChatModelBase, DashScopeChatModel
from pydantic import BaseModel, Field

from bizinsight.agents import CustomerProductAgent, DeliveryAgent, FinanceSalesAgent
from bizinsight.agents.external_research import ExternalResearchAgent
from bizinsight.agents.leader import BizInsightLeader
from bizinsight.agents.reviewer import EvidenceReviewerAgent
from bizinsight.config import BizInsightSettings
from bizinsight.data.generator import generate_dataset, write_dataset
from bizinsight.data.provider import BusinessDataProvider
from bizinsight.observability import AgentTelemetry, RunTelemetry, ToolTelemetry
from bizinsight.orchestration.offline import (
    DeterministicDomainWorker,
    DeterministicExternalWorker,
)
from bizinsight.orchestration.review_loop import run_review_cycle
from bizinsight.orchestration.workflow import AnalysisWorkflow
from bizinsight.schemas import Finding, ReviewResult, WorkerName
from bizinsight.tools.external_search import ExternalSearchService
from bizinsight.tools.knowledge import KnowledgeRetriever
from bizinsight.tools.reports import ActionRecommendation, ReportArtifact, ReportBuilder


class SmokeResponse(BaseModel):
    """Structured contract used only by the minimal integration smoke test."""

    status: Literal["ok"]
    summary: str = Field(min_length=1)


def build_dashscope_model(settings: BizInsightSettings) -> DashScopeChatModel:
    """Build the online model only from explicitly validated configuration."""
    settings.require_online_model()
    assert settings.dashscope_api_key is not None
    assert settings.model_name is not None

    credential = DashScopeCredential(api_key=settings.dashscope_api_key)
    return DashScopeChatModel(
        credential=credential,
        model=settings.model_name,
        stream=False,
    )


def build_smoke_agent(model: ChatModelBase) -> Agent:
    """Create the smallest AgentScope Agent used to prove API compatibility."""
    return Agent(
        name="BizInsightSmokeAgent",
        system_prompt=(
            "You are the BizInsight integration smoke-test agent. When asked "
            "for a structured response, set status to 'ok' and provide a "
            "short non-empty summary."
        ),
        model=model,
        react_config=ReActConfig(max_iters=1, structured_output_grace_iters=1),
        injection_config=InjectionConfig(inject_runtime_state=False),
    )


async def run_structured_smoke(agent: Agent, question: str) -> SmokeResponse:
    """Run one structured reply and return the validated Pydantic object."""
    message = await agent.reply(
        UserMsg(name="user", content=question),
        structured_schema=SmokeResponse,
    )
    if message.structured_output is None:
        raise RuntimeError("AgentScope returned no structured smoke output.")
    return SmokeResponse.model_validate(message.structured_output)


@dataclass(frozen=True)
class AnalysisResult:
    """Complete MVP result returned by CLI, evaluation and HTTP adapters."""

    findings: tuple[Finding, ...]
    review: ReviewResult
    report: ReportArtifact
    event_path: Path
    errors: tuple[str, ...]
    telemetry: RunTelemetry


def _provider(project_root: Path) -> BusinessDataProvider:
    database = project_root / "data/database/bizinsight.sqlite"
    if not database.is_file():
        write_dataset(generate_dataset(), project_root)
    return BusinessDataProvider(
        database_path=database,
        table_dictionary_path=project_root / "data/data_dictionary/tables.yaml",
        metric_dictionary_path=project_root / "data/data_dictionary/metrics.yaml",
    )


def health_status(
    project_root: Path, settings: BizInsightSettings | None = None
) -> dict[str, Any]:
    """Return readiness without ever serializing secret values."""

    settings = settings or BizInsightSettings()
    database = project_root / "data/database/bizinsight.sqlite"
    knowledge = project_root / "data/knowledge/index.json"
    fallback = project_root / "data/knowledge/external_fallback/index.json"
    vector_manifest = project_root / "data/knowledge/vector/manifest.json"
    try:
        with socket.create_connection(("127.0.0.1", 6379), timeout=0.05):
            redis_status = "available"
    except OSError:
        redis_status = "unavailable"
    return {
        "status": "ok" if database.is_file() and knowledge.is_file() else "degraded",
        "database": "available" if database.is_file() else "missing",
        "knowledge_base": "available" if knowledge.is_file() else "missing",
        "vector_knowledge_base": "available"
        if vector_manifest.is_file()
        else "bm25_only",
        "business_mcp": "enabled" if settings.enable_business_mcp else "disabled",
        "redis": redis_status,
        "model": "configured"
        if settings.dashscope_api_key and settings.model_name
        else "offline",
        "external_search": "configured"
        if settings.tavily_api_key
        else "offline_fallback",
        "external_fallback": "available" if fallback.is_file() else "missing",
    }


async def run_analysis(
    question: str,
    *,
    project_root: Path,
    output_dir: Path,
    session_id: str = "local",
    settings: BizInsightSettings | None = None,
    mode: Literal["offline", "online"] = "offline",
    model_override: ChatModelBase | None = None,
) -> AnalysisResult:
    """Run the stable MVP pipeline; online adapters remain explicitly configured."""

    settings = settings or BizInsightSettings()
    telemetry = RunTelemetry(
        mode=mode,
        model_name=settings.model_name or "deterministic",
    )
    started = time.monotonic()
    provider = _provider(project_root)
    lexical_index_path = project_root / "data/knowledge/index.json"
    retriever = KnowledgeRetriever.from_index(lexical_index_path)
    external = ExternalSearchService(
        fallback_dir=project_root / "data/knowledge/external_fallback",
        api_key=settings.tavily_api_key if mode == "online" else None,
    )
    vector_index = None
    vector_manifest = project_root / "data/knowledge/vector/manifest.json"
    if mode == "online" and vector_manifest.is_file():
        try:
            import json as _json

            from bizinsight.rag.hybrid import HybridKnowledgeRetriever
            from bizinsight.rag.vector_index import AgentScopeVectorIndex
            from bizinsight.tools.knowledge import _tokenize

            manifest = _json.loads(vector_manifest.read_text(encoding="utf-8"))
            lexical = _json.loads(lexical_index_path.read_text(encoding="utf-8"))
            if (
                manifest.get("source_hash") != lexical.get("source_hash")
                or manifest.get("model") != settings.embedding_model
                or manifest.get("dimensions") != settings.embedding_dimensions
            ):
                raise ValueError("vector manifest does not match sources/model")
            vector_index = AgentScopeVectorIndex.from_settings(
                settings=settings,
                index_dir=project_root / "data/knowledge/vector",
            )
            await vector_index.__aenter__()
            retriever = HybridKnowledgeRetriever(
                chunks=list(lexical["chunks"]),
                tokenizer=_tokenize,
                knowledge_base=vector_index.knowledge_base,
            )
        except Exception as exc:
            vector_index = None
            telemetry.record_event(
                {
                    "event": "rag_vector_degraded",
                    "error_type": type(exc).__name__,
                }
            )
    if mode == "online":
        model = model_override or build_dashscope_model(settings)
        workers = {
            WorkerName.FINANCE_SALES: FinanceSalesAgent(
                model=model, provider=provider, knowledge_retriever=retriever
            ),
            WorkerName.CUSTOMER_PRODUCT: CustomerProductAgent(
                model=model, provider=provider, knowledge_retriever=retriever
            ),
            WorkerName.DELIVERY: DeliveryAgent(
                model=model, provider=provider, knowledge_retriever=retriever
            ),
            WorkerName.EXTERNAL_RESEARCH: ExternalResearchAgent(
                model=model, search_service=external
            ),
        }
        leader = BizInsightLeader(model, provider)
        plan = await leader.plan(question)
        reviewer = EvidenceReviewerAgent(provider, model)
    else:
        workers = {
            worker: DeterministicDomainWorker(worker, provider, retriever)
            for worker in (
                WorkerName.FINANCE_SALES,
                WorkerName.CUSTOMER_PRODUCT,
                WorkerName.DELIVERY,
            )
        }
        workers[WorkerName.EXTERNAL_RESEARCH] = DeterministicExternalWorker(external)
        leader = BizInsightLeader(provider=provider)
        plan = leader.plan_offline(question)
        reviewer = EvidenceReviewerAgent(provider)
    mcp_workers = []
    if mode == "online" and settings.enable_business_mcp:
        for worker in workers.values():
            attach = getattr(worker, "attach_business_mcp", None)
            if attach is None:
                continue
            try:
                await attach(project_root)
                mcp_workers.append(worker)
            except Exception as exc:
                telemetry.record_event(
                    {
                        "event": "business_mcp_degraded",
                        "worker": getattr(worker, "worker_name", "unknown"),
                        "error_type": type(exc).__name__,
                    }
                )

    async def record_event(event: Any) -> None:
        telemetry.record_event(event)

    workflow_result = await AnalysisWorkflow(
        workers,
        event_sink=record_event,
    ).execute(plan)
    findings = tuple(workflow_result.findings)
    owners = {
        execution.finding.finding_id: execution.task.target_agent
        for execution in workflow_result.executions
        if execution.finding is not None
    }
    tasks_by_finding = {
        execution.finding.finding_id: execution.task
        for execution in workflow_result.executions
        if execution.finding is not None
    }

    async def revise(request):
        task = tasks_by_finding[request.finding_id]
        worker = workers[request.target_agent]
        revised_task = task.model_copy(
            update={
                "question": (
                    f"{task.question}\n\nReviewer 定向返工：{request.reason}\n"
                    f"必须修改：{'；'.join(request.required_changes)}"
                )
            }
        )
        return await worker.analyze(revised_task)

    cycle = await run_review_cycle(
        findings,
        owners=owners,
        reviewer=reviewer,
        revise=revise,
    )
    findings = cycle.findings
    review = cycle.final_review
    telemetry.record_event(
        {"event": "initial_review", "status": cycle.initial_review.status.value}
    )
    if cycle.revision_count:
        telemetry.record_event(
            {"event": "revision_round", "count": cycle.revision_count}
        )
    telemetry.record_event({"event": "final_review", "status": review.status.value})
    for worker in mcp_workers:
        await worker.close()
    if vector_index is not None:
        await vector_index.__aexit__(None, None, None)
    actions = (
        ActionRecommendation(
            priority="P0",
            action="复盘重点输单与低毛利合同",
            rationale="收入、毛利率和赢单率同步下降",
            owner_type="销售与财务负责人",
            timeframe="两周内",
        ),
        ActionRecommendation(
            priority="P0",
            action="建立高风险续费客户清单",
            rationale="续费率和产品服务信号承压",
            owner_type="客户成功与产品负责人",
            timeframe="一周内",
        ),
        ActionRecommendation(
            priority="P1",
            action="治理高定制延期项目",
            rationale="按时验收率下降",
            owner_type="交付负责人",
            timeframe="一个月内",
        ),
    )
    limitations = [
        limitation for finding in findings for limitation in finding.limitations
    ]
    limitations.extend(review.data_limitations)
    limitations.extend(f"Worker 执行限制：{error}" for error in workflow_result.errors)
    accepted_ids = set(review.accepted_finding_ids)
    report_findings = tuple(
        finding for finding in findings if finding.finding_id in accepted_ids
    )
    report = ReportBuilder(output_dir).build(
        question=question,
        findings=report_findings,
        review=review,
        actions=actions,
        limitations=limitations,
    )
    safe_session = (
        "".join(char for char in session_id if char.isalnum() or char in "_-")
        or "local"
    )
    event_path = output_dir.resolve() / f"{safe_session}.events.json"
    event_path.write_text(
        json.dumps(
            [event.model_dump(mode="json") for event in workflow_result.events]
            + [
                {
                    "type": "initial_review",
                    "value": cycle.initial_review.model_dump(mode="json"),
                },
                {"type": "final_review", "value": review.model_dump(mode="json")},
                {"type": "report", "value": {"html": str(report.html_path)}},
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    duration_ms = (time.monotonic() - started) * 1_000
    telemetry.agents.extend(
        AgentTelemetry(
            agent_name=item.task.target_agent.value,
            model_name=(settings.model_name or "unknown")
            if mode == "online"
            else "deterministic",
            duration_ms=item.duration_ms,
            input_tokens=getattr(
                getattr(workers.get(item.task.target_agent), "last_usage", None),
                "input_tokens",
                0,
            ),
            output_tokens=getattr(
                getattr(workers.get(item.task.target_agent), "last_usage", None),
                "output_tokens",
                0,
            ),
            tool_calls=[
                ToolTelemetry(tool_name=f"evidence:{evidence.evidence_type.value}")
                for evidence in (item.finding.evidence if item.finding else [])
            ],
            error=item.error,
        )
        for item in workflow_result.executions
    )
    for name, component in (
        ("BizInsightLeader", leader),
        ("EvidenceReviewerAgent", reviewer),
    ):
        usage = getattr(component, "last_usage", None)
        telemetry.agents.append(
            AgentTelemetry(
                agent_name=name,
                model_name=(settings.model_name or "deterministic"),
                input_tokens=getattr(usage, "input_tokens", 0),
                output_tokens=getattr(usage, "output_tokens", 0),
            )
        )
    telemetry.record_event(
        {
            "event": "report",
            "path": str(report.html_path),
            "finding_count": len(report_findings),
        }
    )
    telemetry.finish(duration_ms, workflow_result.errors)
    telemetry_path = output_dir.resolve() / f"{safe_session}.telemetry.json"
    telemetry_path.write_text(
        telemetry.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return AnalysisResult(
        findings,
        review,
        report,
        event_path,
        tuple(workflow_result.errors),
        telemetry,
    )


def create_agent_service(project_root: Path | None = None):
    """Create the official AgentScope service plus BizInsight workflow routes."""

    try:
        from agentscope.app import create_app
        from agentscope.app.message_bus import InMemoryMessageBus
        from agentscope.app.storage import RedisStorage
        from agentscope.app.workspace_manager import LocalWorkspaceManager
    except ImportError as exc:
        raise RuntimeError(
            "Install the service extra with: pip install -e .[service]"
        ) from exc

    root = (project_root or Path(__file__).resolve().parents[2]).resolve()
    from bizinsight.agents.service_agent import BizInsightServiceAgent

    BizInsightServiceAgent.configure(project_root=root)
    app = create_app(
        storage=RedisStorage(host="localhost", port=6379),
        message_bus=InMemoryMessageBus(),
        workspace_manager=LocalWorkspaceManager(
            basedir=str(root / "outputs/workspaces")
        ),
        title="BizInsight Agent Service",
        custom_agent_cls=BizInsightServiceAgent,
    )

    async def analyze(payload: dict[str, Any]) -> dict[str, Any]:
        result = await run_analysis(
            str(payload.get("question", "请综合分析2026年第二季度经营表现及主要原因")),
            project_root=root,
            output_dir=root / "outputs" / str(payload.get("session_id", "web")),
            session_id=str(payload.get("session_id", "web")),
            mode=str(payload.get("mode", "offline")),
        )
        return {
            "report": str(result.report.html_path),
            "review": result.review.model_dump(mode="json"),
            "events": str(result.event_path),
        }

    from fastapi.staticfiles import StaticFiles

    output_root = (root / "outputs").resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    app.mount("/bizinsight/reports", StaticFiles(directory=output_root), name="reports")
    app.add_api_route(
        "/bizinsight/health", lambda: health_status(root), methods=["GET"]
    )
    app.add_api_route("/bizinsight/analyze", analyze, methods=["POST"])
    return app
