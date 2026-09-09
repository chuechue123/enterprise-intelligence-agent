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

        def search_external_information(
            query: str,
            max_results: int = 5,
        ) -> dict[str, Any]:
            """Search public information or use clearly labelled local fallback."""

            result = self.research(query, max_results=max_results)
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
            Path(__file__).resolve().parents[1]
            / "prompts"
            / "external_research.md"
        ).read_text(encoding="utf-8")
        self.agent = Agent(
            name=WorkerName.EXTERNAL_RESEARCH.value,
            system_prompt=prompt,
            model=model,
            toolkit=self.toolkit,
            react_config=ReActConfig(max_iters=1, structured_output_grace_iters=1),
            injection_config=InjectionConfig(inject_runtime_state=False),
        )

    def research(self, query: str, *, max_results: int = 5) -> ExternalSearchResult:
        return self.search_service.search(query, max_results=max_results)

    async def analyze(self, task: AnalysisTask) -> Finding:
        if task.target_agent is not WorkerName.EXTERNAL_RESEARCH:
            raise ValueError("task is not assigned to ExternalResearchAgent")
        response = await self.agent.reply(
            UserMsg(name="BizInsightLeader", content=task.model_dump_json(indent=2)),
            structured_schema=Finding,
        )
        if response.structured_output is None:
            raise WorkerOutputError("ExternalResearchAgent returned no valid Finding")
        return Finding.model_validate(response.structured_output)
