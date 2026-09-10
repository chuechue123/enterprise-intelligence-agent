"""Minimal AgentScope 2.0.7 integration tests."""

from __future__ import annotations

import os
import sys
from typing import Any

import pytest
from agentscope.credential import CredentialBase
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import ToolCallBlock
from agentscope.model import ChatModelBase, ChatResponse
from pydantic import BaseModel

from bizinsight.app import (
    SmokeResponse,
    build_dashscope_model,
    build_smoke_agent,
    run_structured_smoke,
)
from bizinsight.config import BizInsightSettings, ConfigurationError


class _MockCredential(CredentialBase):
    """Credential required by AgentScope's model abstraction."""

    @classmethod
    def get_chat_model_class(cls) -> type[ChatModelBase]:
        return _StructuredMockModel


class _StructuredMockModel(ChatModelBase):
    """Return one deterministic structured-output tool call."""

    class Parameters(BaseModel):
        """No model parameters are needed by this deterministic fake."""

    def __init__(self) -> None:
        super().__init__(
            credential=_MockCredential(),
            model="bizinsight-structured-mock",
            parameters=self.Parameters(),
            stream=False,
            context_size=4_096,
        )
        self.formatter = OpenAIChatFormatter()
        self.call_count = 0

    async def _call_api(self, *args: Any, **kwargs: Any) -> ChatResponse:
        del args, kwargs
        self.call_count += 1
        return ChatResponse(
            content=[
                ToolCallBlock(
                    id="smoke-structured-call",
                    name="GenerateStructuredOutput",
                    input=(
                        '{"status":"ok",'
                        '"summary":"AgentScope 2.0.7 structured reply works"}'
                    ),
                ),
            ],
            is_last=True,
        )


def test_online_configuration_requires_key_and_uses_safe_model_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("BIZINSIGHT_MODEL_NAME", raising=False)
    settings = BizInsightSettings(_env_file=None)

    with pytest.raises(ConfigurationError) as exc_info:
        settings.require_online_model()

    message = str(exc_info.value)
    assert "DASHSCOPE_API_KEY" in message
    assert settings.model_name == "qwen-plus"


def test_dashscope_model_uses_only_explicit_configuration() -> None:
    settings = BizInsightSettings(
        dashscope_api_key="test-secret",
        model_name="qwen-test-model",
        _env_file=None,
    )

    model = build_dashscope_model(settings)

    assert model.model == "qwen-test-model"
    assert model.credential.api_key.get_secret_value() == "test-secret"


@pytest.mark.asyncio
async def test_agent_returns_validated_structured_response_without_alias() -> None:
    model = _StructuredMockModel()
    agent = build_smoke_agent(model)

    response = await run_structured_smoke(agent, "检查结构化响应")

    assert response == SmokeResponse(
        status="ok",
        summary="AgentScope 2.0.7 structured reply works",
    )
    assert model.call_count == 1
    assert not any(name == "alias" or name.startswith("alias.") for name in sys.modules)


@pytest.mark.online
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("DASHSCOPE_API_KEY") or not os.getenv("BIZINSIGHT_MODEL_NAME"),
    reason="explicit online smoke requires DashScope credentials and model name",
)
async def test_real_dashscope_structured_response() -> None:
    settings = BizInsightSettings()
    model = build_dashscope_model(settings)
    agent = build_smoke_agent(model)

    response = await run_structured_smoke(
        agent,
        "只返回结构化结果，确认服务可用。",
    )

    assert response.status == "ok"
    assert response.summary
