"""Structured business findings and reproducible metric values."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from bizinsight.schemas.evidence import Evidence

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class MetricValue(BaseModel):
    """A deterministic metric with enough information to reproduce it."""

    model_config = ConfigDict(extra="forbid")

    metric_name: NonEmptyStr
    value: Decimal = Field(allow_inf_nan=False)
    unit: NonEmptyStr
    period: NonEmptyStr
    calculation: NonEmptyStr
    evidence_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_evidence_ids(self) -> MetricValue:
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("metric evidence_ids must be unique")
        return self


class Finding(BaseModel):
    """Worker output that separates facts, interpretation, and causality."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str = Field(
        pattern=r"^FINDING-[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    title: NonEmptyStr
    fact_statement: NonEmptyStr
    metrics: list[MetricValue] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    business_interpretation: NonEmptyStr
    causal_assessment: NonEmptyStr | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    limitations: list[NonEmptyStr] = Field(default_factory=list)
    is_key: bool = True

    @model_validator(mode="after")
    def validate_evidence_links(self) -> Finding:
        if self.is_key and not self.evidence:
            raise ValueError("key finding requires at least one evidence")

        attached_ids = [item.evidence_id for item in self.evidence]
        if len(attached_ids) != len(set(attached_ids)):
            raise ValueError("finding evidence_id values must be unique")

        referenced_ids = {
            evidence_id
            for metric in self.metrics
            for evidence_id in metric.evidence_ids
        }
        missing_ids = referenced_ids - set(attached_ids)
        if missing_ids:
            missing = ", ".join(sorted(missing_ids))
            raise ValueError(f"metric references missing evidence: {missing}")
        return self
