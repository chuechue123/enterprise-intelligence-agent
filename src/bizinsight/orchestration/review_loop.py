"""One-round targeted revision orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass

from bizinsight.agents.reviewer import EvidenceReviewerAgent
from bizinsight.schemas import Finding, ReviewResult, WorkerName
from bizinsight.schemas.review import RevisionRequest

RevisionHandler = Callable[[RevisionRequest], Awaitable[Finding | None]]


@dataclass(frozen=True)
class ReviewCycleResult:
    """Initial and final decisions from a bounded review cycle."""

    findings: tuple[Finding, ...]
    initial_review: ReviewResult
    final_review: ReviewResult
    revision_count: int


async def run_review_cycle(
    findings: Sequence[Finding],
    *,
    owners: Mapping[str, WorkerName],
    reviewer: EvidenceReviewerAgent,
    revise: RevisionHandler,
) -> ReviewCycleResult:
    """Revise all targeted findings in one round, never recursively."""

    initial = reviewer.review(findings, owners, allow_revision=True)
    if not initial.revision_requests:
        return ReviewCycleResult(tuple(findings), initial, initial, 0)

    replacements = await asyncio.gather(
        *(revise(request) for request in initial.revision_requests),
        return_exceptions=True,
    )
    updated = {item.finding_id: item for item in findings}
    for request, replacement in zip(
        initial.revision_requests,
        replacements,
        strict=True,
    ):
        if isinstance(replacement, Finding):
            updated[request.finding_id] = replacement

    revised_findings = tuple(updated[item.finding_id] for item in findings)
    final = reviewer.review(revised_findings, owners, allow_revision=False)
    if final.status.value != "accepted" and not final.data_limitations:
        final = final.model_copy(
            update={"data_limitations": ["定向返工后仍未通过证据审查。"]},
        )
    return ReviewCycleResult(revised_findings, initial, final, 1)
