"""Environment-backed configuration for BizInsight Agent."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(RuntimeError):
    """Raised when a requested runtime mode lacks required configuration."""


class BizInsightSettings(BaseSettings):
    """BizInsight configuration loaded from environment variables or `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    dashscope_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="DASHSCOPE_API_KEY",
    )
    model_name: str = Field(
        default="qwen-plus",
        validation_alias="BIZINSIGHT_MODEL_NAME",
    )
    embedding_model: str = Field(
        default="text-embedding-v4",
        validation_alias="BIZINSIGHT_EMBEDDING_MODEL",
    )
    embedding_dimensions: int = Field(
        default=1024,
        validation_alias="BIZINSIGHT_EMBEDDING_DIMENSIONS",
        ge=64,
        le=4096,
    )
    tavily_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="TAVILY_API_KEY",
    )
    enable_business_mcp: bool = Field(
        default=True,
        validation_alias="BIZINSIGHT_ENABLE_BUSINESS_MCP",
    )
    service_storage_backend: Literal["sqlite", "redis"] = Field(
        default="sqlite",
        validation_alias="BIZINSIGHT_SERVICE_STORAGE",
    )

    @field_validator(
        "dashscope_api_key", "model_name", "embedding_model", mode="before"
    )
    @classmethod
    def empty_strings_are_missing(cls, value: object) -> object:
        """Treat blank environment variables as absent configuration."""
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    def require_online_model(self) -> None:
        """Validate the configuration needed for a real DashScope call."""
        missing: list[str] = []
        if self.dashscope_api_key is None:
            missing.append("DASHSCOPE_API_KEY")
        if missing:
            names = ", ".join(missing)
            raise ConfigurationError(
                "Online model mode requires explicit environment variables: "
                f"{names}. Copy .env.example to .env and provide values; "
                "no API key or model name is inferred.",
            )

    def require_online_embedding(self) -> None:
        """Validate configuration before a paid embedding request."""
        if self.dashscope_api_key is None:
            raise ConfigurationError(
                "Online embedding mode requires DASHSCOPE_API_KEY."
            )
