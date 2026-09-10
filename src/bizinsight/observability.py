"""Secret-safe telemetry for one BizInsight analysis run."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, SecretStr, field_serializer


def _redact(value: Any) -> Any:
    """Recursively remove values that must never enter events or artifacts."""
    if isinstance(value, SecretStr):
        return "***"
    if isinstance(value, dict):
        return {
            key: "***"
            if any(word in key.lower() for word in ("key", "secret", "token"))
            else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


class ToolTelemetry(BaseModel):
    tool_name: str
    duration_ms: float = 0
    status: str = "completed"
    error: str | None = None


class AgentTelemetry(BaseModel):
    agent_name: str
    model_name: str
    duration_ms: float = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_cny: float | None = None
    tool_calls: list[ToolTelemetry] = Field(default_factory=list)
    error: str | None = None


class RunTelemetry(BaseModel):
    run_id: str = Field(default_factory=lambda: f"RUN-{uuid4().hex}")
    mode: str
    model_name: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    duration_ms: float = 0
    cost_cny: float | None = None
    agents: list[AgentTelemetry] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @field_serializer("events")
    def serialize_events(self, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _redact(value)

    def record_event(self, event: Any) -> None:
        payload = (
            event.model_dump(mode="json") if hasattr(event, "model_dump") else event
        )
        self.events.append(_redact(payload))

    def finish(self, duration_ms: float, errors: list[str]) -> None:
        self.duration_ms = duration_ms
        self.errors = list(errors)


__all__ = ["AgentTelemetry", "RunTelemetry", "ToolTelemetry"]
