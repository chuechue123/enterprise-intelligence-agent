"""AgentScope integration test for the external research Worker."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from agentscope.credential import CredentialBase
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import ToolCallBlock
from agentscope.model import ChatModelBase, ChatResponse
from pydantic import BaseModel

from bizinsight.agents.external_research import ExternalResearchAgent
from bizinsight.schemas import AnalysisTask, Finding, WorkerName
from bizinsight.tools.external_search import ExternalSearchService, SearchMode

FALLBACK_DIR = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "knowledge"
    / "external_fallback"
)


class _Credential(CredentialBase):
    @classmethod
    def get_chat_model_class(cls) -> type[ChatModelBase]:
        return _ResearchMockModel


class _ResearchMockModel(ChatModelBase):
    class Parameters(BaseModel):
        pass

    def __init__(self) -> None:
        super().__init__(
            credential=_Credential(),
            model="research-mock",
            parameters=self.Parameters(),
            stream=False,
            context_size=4_096,
        )
        self.formatter = OpenAIChatFormatter()
        self.call_count = 0

    async def _call_api(self, *args: Any, **kwargs: Any) -> ChatResponse:
        del args, kwargs
        self.call_count += 1
        payload = {
            "finding_id": "FINDING-EXTERNAL-001",
            "title": "企业软件市场背景",
            "fact_statement": "本地行业资料显示价格与稳定性是采购考虑因素。",
            "metrics": [],
            "evidence": [
                {
                    "evidence_id": "DOC-EXTERNAL-MARKET-001-C001",
                    "evidence_type": "document",
                    "source": "DOC-EXTERNAL-MARKET-001｜企业软件采购趋势",
                    "locator": "market_trends.md:L10-L10",
                    "summary": "企业客户同时比较价格、可靠性和服务。",
                    "generated_at": "2026-09-09T09:00:00+08:00",
                },
            ],
            "business_interpretation": "该资料只能作为行业背景。",
            "causal_assessment": "不能直接证明虚构企业内部业绩下降原因。",
            "confidence": 0.6,
            "limitations": ["未完成实时搜索。"],
            "is_key": False,
        }
        return ChatResponse(
            content=[
                ToolCallBlock(
                    id="research-output",
                    name="GenerateStructuredOutput",
                    input=json.dumps(payload, ensure_ascii=False),
                ),
            ],
            is_last=True,
        )


@pytest.mark.asyncio
async def test_external_agent_returns_finding_and_supports_offline_research() -> None:
    service = ExternalSearchService(fallback_dir=FALLBACK_DIR, api_key=None)
    model = _ResearchMockModel()
    agent = ExternalResearchAgent(model=model, search_service=service)
    task = AnalysisTask(
        task_id="TASK-EXTERNAL-001",
        target_agent=WorkerName.EXTERNAL_RESEARCH,
        question="检索企业软件行业的价格竞争和稳定性背景。",
        required_datasets=["external_information"],
        expected_outputs=["带来源的行业背景"],
    )

    research = agent.research(task.question)
    finding = await agent.analyze(task)

    assert research.mode is SearchMode.OFFLINE
    assert isinstance(finding, Finding)
    assert "不能直接证明" in (finding.causal_assessment or "")
    assert agent.tool_names == {"search_external_information"}
    assert model.call_count == 1


def test_external_fallback_finding_preserves_searched_evidence() -> None:
    service = ExternalSearchService(fallback_dir=FALLBACK_DIR, api_key=None)
    result = service.search("企业软件行业背景", max_results=2)
    task = AnalysisTask(
        task_id="TASK-EXTERNAL-FALLBACK",
        target_agent=WorkerName.EXTERNAL_RESEARCH,
        question="检索企业软件行业背景。",
        required_datasets=["external_information"],
        expected_outputs=["带来源的行业背景"],
    )

    finding = ExternalResearchAgent._fallback_finding(task, result)

    assert finding.evidence == result.evidence
    assert finding.is_key is False
    assert finding.metrics == []
    assert "不能单独证明" in (finding.causal_assessment or "")
