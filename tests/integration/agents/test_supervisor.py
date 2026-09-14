"""AgentScope integration tests for the general Supervisor."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from agentscope.credential import CredentialBase
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import AssistantMsg, TextBlock, UserMsg
from agentscope.model import ChatModelBase, ChatResponse
from pydantic import BaseModel

from bizinsight.agents.service_agent import BizInsightServiceAgent
from bizinsight.agents.supervisor import SupervisorAgent, build_supervisor_agent
from bizinsight.config import BizInsightSettings

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class _Credential(CredentialBase):
    @classmethod
    def get_chat_model_class(cls) -> type[ChatModelBase]:
        return _GeneralMockModel


class _GeneralMockModel(ChatModelBase):
    class Parameters(BaseModel):
        pass

    def __init__(self) -> None:
        super().__init__(
            credential=_Credential(),
            model="supervisor-mock",
            parameters=self.Parameters(),
            stream=False,
            context_size=8_192,
        )
        self.formatter = OpenAIChatFormatter()
        self.call_count = 0

    async def _call_api(self, *args: Any, **kwargs: Any) -> ChatResponse:
        del args, kwargs
        self.call_count += 1
        return ChatResponse(
            content=[TextBlock(text="我是 BizInsight 企业智能助手。")],
            is_last=True,
        )


@pytest.mark.asyncio
async def test_identity_question_is_answered_without_weather_mcp() -> None:
    model = _GeneralMockModel()
    agent = build_supervisor_agent(
        model=model,
        project_root=PROJECT_ROOT,
        settings=BizInsightSettings(_env_file=None),
    )

    response = await agent.reply(UserMsg(name="user", content="你是谁？"))

    assert "BizInsight" in response.get_text_content()
    assert model.call_count == 1
    assert agent._weather_connection is None
    assert agent.last_route == "general"
    tool_names = {
        tool.name for group in agent.toolkit.tool_groups for tool in group.tools
    }
    assert "search_internal_knowledge" in tool_names
    assert "run_business_analysis" in tool_names


@pytest.mark.asyncio
async def test_new_turn_does_not_reuse_previous_business_metadata() -> None:
    agent = build_supervisor_agent(
        model=_GeneralMockModel(),
        project_root=PROJECT_ROOT,
        settings=BizInsightSettings(_env_file=None),
    )
    agent.last_route = "business_analysis"
    agent.last_business_metadata = {"run_id": "RUN-old"}

    response = await agent.reply(UserMsg(name="user", content="你好"))

    assert agent.last_route == "general"
    assert "run_id" not in response.metadata


@pytest.mark.asyncio
async def test_supervisor_uses_existing_internal_knowledge_index() -> None:
    agent = build_supervisor_agent(
        model=_GeneralMockModel(),
        project_root=PROJECT_ROOT,
        settings=BizInsightSettings(_env_file=None),
    )

    result = await agent.search_internal_knowledge("收入确认需要满足什么条件？")

    assert result["mode"] == "bm25"
    assert result["evidence"]
    assert any(
        item["evidence_id"].startswith("DOC-FINANCE-REVREC")
        for item in result["evidence"]
    )
    assert agent.last_route == "knowledge"


def test_weather_followup_is_detected_from_agentscope_context() -> None:
    agent = build_supervisor_agent(
        model=_GeneralMockModel(),
        project_root=PROJECT_ROOT,
        settings=BizInsightSettings(_env_file=None),
    )
    agent.state.middle_context[agent.WEATHER_PENDING_KEY] = True

    assert agent._weather_relevant(UserMsg(name="user", content="上海"))


def test_identity_capability_text_does_not_trigger_weather_mcp() -> None:
    agent = build_supervisor_agent(
        model=_GeneralMockModel(),
        project_root=PROJECT_ROOT,
        settings=BizInsightSettings(_env_file=None),
    )
    agent.state.context.append(
        AssistantMsg(
            name=agent.name,
            content="我可以检索知识、分析经营问题并查询实时天气。",
        )
    )

    assert not agent._weather_relevant(
        UserMsg(name="user", content="解释收入确认制度")
    )


def test_explicit_business_report_gets_a_strict_route_hint() -> None:
    agent = build_supervisor_agent(
        model=_GeneralMockModel(),
        project_root=PROJECT_ROOT,
        settings=BizInsightSettings(_env_file=None),
    )
    request = UserMsg(
        name="user",
        content="请分析第二季度经营表现下降原因并生成报告",
    )

    assert agent._business_analysis_relevant(request)
    hinted = agent._append_business_route_hint(request)
    assert "必须调用 run_business_analysis" in hinted[-1].get_text_content()


def test_simple_internal_policy_question_does_not_force_business_report() -> None:
    agent = build_supervisor_agent(
        model=_GeneralMockModel(),
        project_root=PROJECT_ROOT,
        settings=BizInsightSettings(_env_file=None),
    )

    assert not agent._business_analysis_relevant(
        UserMsg(name="user", content="收入确认制度是什么？")
    )


def test_service_agent_is_the_agentscope_supervisor() -> None:
    assert issubclass(BizInsightServiceAgent, SupervisorAgent)
