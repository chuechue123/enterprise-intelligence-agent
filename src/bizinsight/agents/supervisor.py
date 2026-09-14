"""General AgentScope supervisor that preserves the business-analysis pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentscope.agent import Agent, ReActConfig
from agentscope.message import Msg, UserMsg
from agentscope.model import ChatModelBase
from agentscope.tool import FunctionTool, Toolkit
from pydantic import BaseModel, Field

from bizinsight.config import BizInsightSettings
from bizinsight.mcp.weather_client import WeatherMCPConnection
from bizinsight.rag.hybrid import HybridKnowledgeRetriever
from bizinsight.rag.vector_index import AgentScopeVectorIndex
from bizinsight.tools.knowledge import KnowledgeRetriever, _tokenize


class _KnowledgeInput(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=10)


class _BusinessAnalysisInput(BaseModel):
    question: str = Field(min_length=1)


class SupervisorAgent(Agent):
    """Route conversation, RAG, business analysis and real-time MCP tools."""

    WEATHER_WORDS = (
        "天气",
        "气温",
        "温度",
        "下雨",
        "降雨",
        "降水",
        "预报",
        "weather",
        "temperature",
        "rain",
    )
    BUSINESS_SCOPE_WORDS = (
        "经营分析",
        "经营表现",
        "经营问题",
        "经营异常",
        "业绩下滑",
        "业绩下降",
    )
    BUSINESS_ACTION_WORDS = ("分析", "诊断", "原因", "报告", "建议")
    WEATHER_PENDING_KEY = "bizinsight_weather_pending"

    def __init__(
        self,
        *args: Any,
        project_root: Path,
        settings: BizInsightSettings | None = None,
        **kwargs: Any,
    ) -> None:
        self.project_root = project_root.resolve()
        self.settings = settings or BizInsightSettings()
        self._core_tools_ready = False
        self._weather_connection: WeatherMCPConnection | None = None
        self._weather_tool_names: list[str] = []
        self.last_route = "general"
        self.last_business_metadata: dict[str, Any] | None = None

        prompt = (
            Path(__file__).resolve().parents[1] / "prompts" / "supervisor.md"
        ).read_text(encoding="utf-8")
        supplied_prompt = str(kwargs.pop("system_prompt", "")).strip()
        kwargs["system_prompt"] = (
            f"{supplied_prompt}\n\n{prompt}" if supplied_prompt else prompt
        )
        kwargs.setdefault("react_config", ReActConfig(max_iters=5))
        kwargs.setdefault("toolkit", Toolkit())
        super().__init__(*args, **kwargs)

    async def _ensure_core_tools(self) -> None:
        if self._core_tools_ready:
            return
        await self.toolkit.add_tool(
            [
                FunctionTool(
                    self.search_internal_knowledge,
                    name="search_internal_knowledge",
                    input_schema=_KnowledgeInput,
                    is_read_only=True,
                ),
                FunctionTool(
                    self.run_business_analysis,
                    name="run_business_analysis",
                    input_schema=_BusinessAnalysisInput,
                    is_read_only=True,
                ),
            ]
        )
        self._core_tools_ready = True

    def _weather_relevant(self, inputs: Any) -> bool:
        messages = inputs if isinstance(inputs, list) else [inputs]
        current_text = " ".join(
            item.get_text_content()
            for item in messages
            if isinstance(item, Msg)
        ).lower()
        if any(word in current_text for word in self.WEATHER_WORDS):
            return True
        return bool(self.state.middle_context.get(self.WEATHER_PENDING_KEY))

    @staticmethod
    def _asks_for_weather_location(text: str) -> bool:
        lowered = text.lower()
        return (
            any(word in lowered for word in ("城市", "地区", "地点"))
            and any(
                word in lowered
                for word in ("哪个", "哪座", "告诉", "提供", "具体")
            )
        )

    def _business_analysis_relevant(self, inputs: Any) -> bool:
        messages = inputs if isinstance(inputs, list) else [inputs]
        current_text = " ".join(
            item.get_text_content()
            for item in messages
            if isinstance(item, Msg)
        )
        return any(word in current_text for word in self.BUSINESS_SCOPE_WORDS) and any(
            word in current_text for word in self.BUSINESS_ACTION_WORDS
        )

    @staticmethod
    def _append_business_route_hint(inputs: Any) -> list[Any]:
        messages = list(inputs) if isinstance(inputs, list) else [inputs]
        messages.append(
            UserMsg(
                name="BizInsightRouteGuard",
                content=(
                    "<system-notification>该请求明确要求经营诊断或分析报告。"
                    "你必须调用 run_business_analysis，禁止仅凭通用知识直接回答。"
                    "工具完成后再向用户概括 Reviewer 通过的结论和报告地址。"
                    "</system-notification>"
                ),
            )
        )
        return messages

    async def _attach_weather_mcp(self) -> None:
        if self._weather_connection is not None:
            return
        connection = WeatherMCPConnection.build(project_root=self.project_root)
        try:
            await connection.connect_to(self.toolkit)
        except Exception:
            await connection.close()
            raise
        else:
            self._weather_tool_names = list(connection.attached_tool_names)
            self._weather_connection = connection

    async def _close_weather_mcp(self) -> None:
        connection = self._weather_connection
        self._weather_connection = None
        for name in self._weather_tool_names:
            await self.toolkit.remove_tool(name)
        self._weather_tool_names = []
        if connection is not None:
            await connection.close()

    async def search_internal_knowledge(
        self,
        query: str,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Search traceable internal documents, preferring hybrid retrieval."""

        self.last_route = "knowledge"
        lexical_path = self.project_root / "data/knowledge/index.json"
        lexical_data = json.loads(lexical_path.read_text(encoding="utf-8"))
        retriever: Any = KnowledgeRetriever(lexical_data)
        mode = "bm25"
        degradation = None
        vector: AgentScopeVectorIndex | None = None
        manifest_path = self.project_root / "data/knowledge/vector/manifest.json"
        if manifest_path.is_file() and self.settings.dashscope_api_key is not None:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if (
                    manifest.get("source_hash") != lexical_data.get("source_hash")
                    or manifest.get("model") != self.settings.embedding_model
                    or manifest.get("dimensions") != self.settings.embedding_dimensions
                ):
                    raise ValueError("vector manifest does not match knowledge sources")
                vector = AgentScopeVectorIndex.from_settings(
                    settings=self.settings,
                    index_dir=self.project_root / "data/knowledge/vector",
                )
                await vector.__aenter__()
                retriever = HybridKnowledgeRetriever(
                    chunks=list(lexical_data["chunks"]),
                    tokenizer=_tokenize,
                    knowledge_base=vector.knowledge_base,
                )
                mode = "hybrid"
            except Exception as exc:
                degradation = f"向量检索不可用，已降级 BM25：{type(exc).__name__}"
                retriever = KnowledgeRetriever(lexical_data)
                vector = None
        try:
            result = retriever.search(query, top_k=top_k)
            if hasattr(result, "__await__"):
                result = await result
        finally:
            if vector is not None:
                await vector.__aexit__(None, None, None)
        return {
            "mode": mode,
            "query": result.query,
            "evidence": [item.model_dump(mode="json") for item in result.evidence],
            "reason": result.reason,
            "degradation": degradation,
        }

    async def run_business_analysis(self, question: str) -> dict[str, Any]:
        """Invoke the existing reviewed business-analysis workflow unchanged."""

        from bizinsight.app import run_analysis

        self.last_route = "business_analysis"
        session_id = self.state.session_id or "supervisor"
        result = await run_analysis(
            question,
            project_root=self.project_root,
            output_dir=self.project_root / "outputs" / session_id,
            session_id=session_id,
            settings=self.settings,
            mode="online",
            model_override=self.model,
        )
        relative = result.report.html_path.resolve().relative_to(
            (self.project_root / "outputs").resolve()
        )
        report_url = "/bizinsight/reports/" + relative.as_posix()
        accepted = set(result.review.accepted_finding_ids)
        payload = {
            "status": "completed",
            "run_id": result.telemetry.run_id,
            "review_status": result.review.status.value,
            "accepted_findings": [
                {
                    "finding_id": item.finding_id,
                    "title": item.title,
                    "fact_statement": item.fact_statement,
                    "confidence": item.confidence,
                }
                for item in result.findings
                if item.finding_id in accepted
            ],
            "data_limitations": result.review.data_limitations,
            "errors": list(result.errors),
            "report_url": report_url,
        }
        self.last_business_metadata = {
            "bizinsight_report": report_url,
            "run_id": result.telemetry.run_id,
            "review_status": result.review.status.value,
        }
        return payload

    async def reply(self, inputs: Any = None, structured_schema: Any = None) -> Msg:
        self.last_route = "general"
        self.last_business_metadata = None
        await self._ensure_core_tools()
        if self._business_analysis_relevant(inputs):
            inputs = self._append_business_route_hint(inputs)
        attach_weather = self._weather_relevant(inputs)
        if attach_weather:
            self.last_route = "weather"
            try:
                await self._attach_weather_mcp()
            except Exception:
                self.last_route = "weather_unavailable"
        try:
            response = await super().reply(inputs, structured_schema)
        finally:
            await self._close_weather_mcp()
        if attach_weather:
            self.state.middle_context[self.WEATHER_PENDING_KEY] = (
                self._asks_for_weather_location(response.get_text_content())
            )
        if self.last_business_metadata:
            response.metadata.update(self.last_business_metadata)
        return response


def build_supervisor_agent(
    *,
    model: ChatModelBase,
    project_root: Path,
    name: str = "BizInsightSupervisor",
    settings: BizInsightSettings | None = None,
) -> SupervisorAgent:
    """Build a standalone Supervisor for CLI tests and non-service callers."""

    return SupervisorAgent(
        name=name,
        model=model,
        project_root=project_root,
        settings=settings,
    )


__all__ = ["SupervisorAgent", "build_supervisor_agent"]
