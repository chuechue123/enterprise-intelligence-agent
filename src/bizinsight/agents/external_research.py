"""AgentScope Worker for sourced external industry context."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentscope.agent import Agent, InjectionConfig, ReActConfig
from agentscope.message import UserMsg
from agentscope.model import ChatModelBase
from agentscope.tool import FunctionTool, Toolkit
from pydantic import BaseModel, Field

from bizinsight.agents.worker_base import WorkerOutputError
from bizinsight.observability import aggregate_agent_usage
from bizinsight.schemas import AnalysisTask, Finding, WorkerName
from bizinsight.tools.external_search import ExternalSearchResult, ExternalSearchService


class _SearchInput(BaseModel):
    query: str = Field(min_length=1)
    max_results: int = Field(default=5, ge=1, le=10)


class ExternalResearchAgent:
    """Collect industry background without asserting internal causality."""

    def __init__(
        self,
        *,
        model: ChatModelBase,
        search_service: ExternalSearchService,
    ) -> None:
        self.search_service = search_service
        self.last_usage = None
        self.last_research_result: ExternalSearchResult | None = None

        def search_external_information(
            query: str,
            max_results: int = 5,
        ) -> dict[str, Any]:
            """Search public information or use clearly labelled local fallback."""

            result = self.research(query, max_results=max_results)
            self.last_research_result = result
            return {
                "mode": result.mode.value,
                "evidence": [item.model_dump(mode="json") for item in result.evidence],
                "degradation_reason": result.degradation_reason,
            }

        self.toolkit = Toolkit(
            tools=[
                FunctionTool(
                    search_external_information,
                    name="search_external_information",
                    input_schema=_SearchInput,
                    is_read_only=True,
                ),
            ],
        )
        self.tool_names = {"search_external_information"}
        prompt = (
            Path(__file__).resolve().parents[1] / "prompts" / "external_research.md"
        ).read_text(encoding="utf-8")
        self.agent = Agent(
            name=WorkerName.EXTERNAL_RESEARCH.value,
            system_prompt=prompt,
            model=model,
            toolkit=self.toolkit,
            react_config=ReActConfig(max_iters=3, structured_output_grace_iters=2),
            injection_config=InjectionConfig(inject_runtime_state=False),
        )

    def research(self, query: str, *, max_results: int = 5) -> ExternalSearchResult:
        return self.search_service.search(query, max_results=max_results)

    @staticmethod
    def _fallback_finding(
        task: AnalysisTask,
        result: ExternalSearchResult,
    ) -> Finding:
        """Preserve searched evidence when the model misses the output schema."""

        mode = "实时公开资料" if result.mode.value == "online" else "本地备用资料"
        summaries = "；".join(item.summary[:160] for item in result.evidence[:3])
        limitations = [
            "外部研究模型未在限定轮次内提交结构化结果，"
            "系统仅保留工具已返回的外部背景证据。"
        ]
        if result.degradation_reason:
            limitations.append(result.degradation_reason)
        return Finding(
            finding_id=f"FINDING-EXT-FALLBACK-{task.task_id}",
            title="外部行业信息交叉验证",
            fact_statement=(
                f"{mode}检索获得 {len(result.evidence)} 条可追溯资料。"
                + (f"主要内容：{summaries}" if summaries else "")
            ),
            metrics=[],
            evidence=result.evidence,
            business_interpretation=(
                "这些资料仅用于说明行业和市场背景，需与企业内部数据结合判断。"
            ),
            causal_assessment="外部资料不能单独证明公司内部经营变化的原因。",
            confidence=0.5 if result.mode.value == "online" else 0.3,
            limitations=limitations,
            is_key=False,
        )

    async def analyze(self, task: AnalysisTask) -> Finding:
        if task.target_agent is not WorkerName.EXTERNAL_RESEARCH:
            raise ValueError("task is not assigned to ExternalResearchAgent")
        response = await self.agent.reply(
            UserMsg(name="BizInsightLeader", content=task.model_dump_json(indent=2)),
            structured_schema=Finding,
        )
        self.last_usage = response.usage or aggregate_agent_usage(self.agent)
        if response.structured_output is None:
            result = self.last_research_result or self.research(task.question)
            if not result.evidence:
                raise WorkerOutputError(
                    "ExternalResearchAgent returned no valid Finding"
                )
            return self._fallback_finding(task, result)
        return Finding.model_validate(response.structured_output)
