import json

from pydantic import SecretStr

from bizinsight.observability import RunTelemetry


def test_telemetry_redacts_secrets_and_is_json_serializable() -> None:
    telemetry = RunTelemetry(mode="offline", model_name="deterministic")
    telemetry.record_event(
        {"event": "tool", "api_key": SecretStr("must-not-leak"), "value": 1}
    )
    payload = telemetry.model_dump_json()
    json.loads(payload)
    assert "must-not-leak" not in payload
    assert "***" in payload
