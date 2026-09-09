"""Evidence-review results and bounded revision requests."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from bizinsight.schemas.plan import WorkerName

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ReviewStatus(StrEnum):
    """Possible outcomes of one evidence-review pass."""

    ACCEPTED = "accepted"
    REVISION_REQUIRED = "revision_required"
    REJECTED = "rejected"
    PARTIAL = "partial"


class RevisionRequest(BaseModel):
    """A targeted request sent back to exactly one domain Worker."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(
        pattern=r"^REVISION-[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    finding_id: str = Field(
        pattern=r"^FINDING-[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    target_agent: WorkerName
    reason: NonEmptyStr
    required_changes: list[NonEmptyStr] = Field(min_length=1)


class ReviewResult(BaseModel):
    """Reviewer output with mutually consistent decisions."""

    model_config = ConfigDict(extra="forbid")

    status: ReviewStatus
    accepted_finding_ids: list[str] = Field(default_factory=list)
    rejected_finding_ids: list[str] = Field(default_factory=list)
    revision_requests: list[RevisionRequest] = Field(default_factory=list)
    conflicts: list[NonEmptyStr] = Field(default_factory=list)
    data_limitations: list[NonEmptyStr] = Field(default_factory=list)
    reviewer_notes: NonEmptyStr

    @model_validator(mode="after")
    def validate_decisions(self) -> ReviewResult:
        accepted = set(self.accepted_finding_ids)
        rejected = set(self.rejected_finding_ids)
        overlap = accepted & rejected
        if overlap:
            raise ValueError("a finding cannot be both accepted and rejected")

        revised = {request.finding_id for request in self.revision_requests}
        if accepted & revised:
            raise ValueError("an accepted finding cannot request revision")

        if self.status is ReviewStatus.REVISION_REQUIRED and not revised:
            raise ValueError(
                "revision_required status requires a revision request",
            )
        if self.status is ReviewStatus.ACCEPTED and (rejected or revised):
            raise ValueError(
                "accepted status cannot contain rejections or revisions",
            )
        if self.status is ReviewStatus.REJECTED and (accepted or not rejected):
            raise ValueError(
                "rejected status requires rejected findings and no accepted ones",
            )
        if self.status is ReviewStatus.PARTIAL and (
            not accepted or not (rejected or revised)
        ):
            raise ValueError(
                "partial status requires accepted findings plus an issue",
            )
        return self
