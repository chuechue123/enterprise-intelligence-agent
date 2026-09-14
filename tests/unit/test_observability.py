import json
from types import SimpleNamespace

from agentscope.message import Usage
from pydantic import SecretStr

from bizinsight.observability import RunTelemetry, aggregate_agent_usage


def test_telemetry_redacts_secrets_and_is_json_serializable() -> None:
    telemetry = RunTelemetry(mode="offline", model_name="deterministic")
    telemetry.record_event(
        {"event": "tool", "api_key": SecretStr("must-not-leak"), "value": 1}
    )
    payload = telemetry.model_dump_json()
    json.loads(payload)
    assert "must-not-leak" not in payload
    assert "***" in payload


def test_structured_agent_usage_is_aggregated_from_context() -> None:
    agent = SimpleNamespace(
        state=SimpleNamespace(
            context=[
                SimpleNamespace(
                    usage=Usage(input_tokens=100, output_tokens=20),
                ),
                SimpleNamespace(usage=None),
                SimpleNamespace(
                    usage=Usage(
                        input_tokens=50,
                        output_tokens=10,
                        cache_input_tokens=5,
                    ),
                ),
            ],
        ),
    )

    usage = aggregate_agent_usage(agent)

    assert usage is not None
    assert usage.input_tokens == 150
    assert usage.output_tokens == 30
    assert usage.cache_input_tokens == 5
