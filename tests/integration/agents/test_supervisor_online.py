"""Explicit real-model acceptance checks for the general Supervisor."""

from pathlib import Path

import pytest
from agentscope.message import UserMsg

from bizinsight.agents.supervisor import build_supervisor_agent
from bizinsight.app import build_dashscope_model
from bizinsight.config import BizInsightSettings

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.online
@pytest.mark.asyncio
async def test_real_supervisor_identity_rag_and_weather_followup() -> None:
    settings = BizInsightSettings()
    agent = build_supervisor_agent(
        model=build_dashscope_model(settings),
        project_root=PROJECT_ROOT,
        settings=settings,
    )

    identity = await agent.reply(UserMsg(name="user", content="你是谁？"))
    assert "BizInsight" in identity.get_text_content()
    assert agent.last_route == "general"

    knowledge = await agent.reply(
        UserMsg(name="user", content="公司收入确认需要满足什么条件？")
    )
    assert agent.last_route == "knowledge"
    assert "收入" in knowledge.get_text_content()

    clarification = await agent.reply(
        UserMsg(name="user", content="今天天气怎么样？")
    )
    assert "城市" in clarification.get_text_content() or "地区" in (
        clarification.get_text_content()
    )

    weather = await agent.reply(UserMsg(name="user", content="上海"))
    assert agent.last_route == "weather"
    assert "上海" in weather.get_text_content()
    assert any(
        word in weather.get_text_content()
        for word in ("℃", "温", "雨", "晴", "云", "风")
    )


@pytest.mark.online
@pytest.mark.asyncio
async def test_real_supervisor_routes_business_analysis_to_existing_pipeline() -> None:
    settings = BizInsightSettings()
    agent = build_supervisor_agent(
        model=build_dashscope_model(settings),
        project_root=PROJECT_ROOT,
        settings=settings,
    )

    response = await agent.reply(
        UserMsg(
            name="user",
            content="请分析2026年第二季度经营表现下降的主要原因并生成报告。",
        )
    )

    assert agent.last_route == "business_analysis"
    assert response.metadata["bizinsight_report"].endswith("report.html")
    assert response.metadata["run_id"].startswith("RUN-")
    assert "报告" in response.get_text_content()
