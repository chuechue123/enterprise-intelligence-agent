"""Tests for evidence review contracts."""

import pytest
from pydantic import ValidationError

from bizinsight.schemas.plan import WorkerName
from bizinsight.schemas.review import (
    ReviewResult,
    ReviewStatus,
    RevisionRequest,
)


def _revision() -> RevisionRequest:
    return RevisionRequest(
        request_id="REVISION-1",
        finding_id="FINDING-renewal",
        target_agent=WorkerName.CUSTOMER_PRODUCT,
        reason="续费率分母与指标字典不一致。",
        required_changes=["按到期客户数重新计算续费率"],
    )


def test_revision_required_status_must_include_request() -> None:
    with pytest.raises(ValidationError, match="revision request"):
        ReviewResult(
            status=ReviewStatus.REVISION_REQUIRED,
            reviewer_notes="需要重新计算。",
        )


def test_review_rejects_overlapping_accepted_and_rejected_findings() -> None:
    with pytest.raises(ValidationError, match="both accepted and rejected"):
        ReviewResult(
            status=ReviewStatus.PARTIAL,
            accepted_finding_ids=["FINDING-1"],
            rejected_finding_ids=["FINDING-1"],
            reviewer_notes="状态冲突。",
        )


def test_valid_revision_review_preserves_targeted_changes() -> None:
    review = ReviewResult(
        status=ReviewStatus.REVISION_REQUIRED,
        revision_requests=[_revision()],
        conflicts=["Worker 与指标字典使用了不同分母"],
        reviewer_notes="完成一次定向返工后重新审查。",
    )

    assert review.revision_requests[0].finding_id == "FINDING-renewal"
    assert review.revision_requests[0].target_agent is WorkerName.CUSTOMER_PRODUCT
