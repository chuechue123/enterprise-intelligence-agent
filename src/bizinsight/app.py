"""Minimal AgentScope 2.0.7 application wiring.

The domain workflow is added in later implementation tasks. This module keeps
the first integration deliberately small: build an AgentScope Agent, inject a
model, and verify a Pydantic-validated structured reply.
"""

from __future__ import annotations

from typing import Literal

from agentscope.agent import Agent, InjectionConfig, ReActConfig
from agentscope.credential import DashScopeCredential
from agentscope.message import UserMsg
from agentscope.model import ChatModelBase, DashScopeChatModel
from pydantic import BaseModel, Field

from bizinsight.config import BizInsightSettings


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
