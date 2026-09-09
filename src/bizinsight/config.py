"""Environment-backed configuration for BizInsight Agent."""

from __future__ import annotations

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
    model_name: str | None = Field(
        default=None,
        validation_alias="BIZINSIGHT_MODEL_NAME",
    )
    tavily_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="TAVILY_API_KEY",
    )

    @field_validator("dashscope_api_key", "model_name", mode="before")
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
        if self.model_name is None:
            missing.append("BIZINSIGHT_MODEL_NAME")

        if missing:
            names = ", ".join(missing)
            raise ConfigurationError(
                "Online model mode requires explicit environment variables: "
                f"{names}. Copy .env.example to .env and provide values; "
                "no API key or model name is inferred.",
            )
