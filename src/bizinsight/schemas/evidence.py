"""Traceable evidence contracts shared by Workers and the Reviewer."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    StringConstraints,
    field_validator,
    model_validator,
)

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class EvidenceType(StrEnum):
    """Supported evidence origins."""

    DATABASE = "database"
    DOCUMENT = "document"
    WEB = "web"
    CALCULATION = "calculation"


class Evidence(BaseModel):
    """One source record capable of supporting a Finding."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(
        pattern=r"^(DB|DOC|WEB|CALC)-[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    evidence_type: EvidenceType
    source: NonEmptyStr
    locator: NonEmptyStr
    summary: NonEmptyStr
    generated_at: datetime
    url: HttpUrl | None = None
    accessed_at: datetime | None = None

    @field_validator("generated_at", "accessed_at")
    @classmethod
    def timestamps_must_include_timezone(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() is None
        ):
            raise ValueError("evidence timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_origin_fields(self) -> Evidence:
        expected_prefix = {
            EvidenceType.DATABASE: "DB",
            EvidenceType.DOCUMENT: "DOC",
            EvidenceType.WEB: "WEB",
            EvidenceType.CALCULATION: "CALC",
        }[self.evidence_type]
        actual_prefix = self.evidence_id.split("-", maxsplit=1)[0]
        if actual_prefix != expected_prefix:
            raise ValueError(
                f"evidence_id prefix {actual_prefix!r} does not match "
                f"evidence_type {self.evidence_type.value!r}",
            )
        if self.evidence_type is EvidenceType.WEB and (
            self.url is None or self.accessed_at is None
        ):
            raise ValueError("WEB evidence requires url and accessed_at")
        return self
