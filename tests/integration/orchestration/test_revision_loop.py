"""Tests for the single-pass targeted revision loop."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from bizinsight.agents.reviewer import EvidenceReviewerAgent
from bizinsight.data.generator import generate_dataset, write_dataset
from bizinsight.data.provider import BusinessDataProvider
from bizinsight.orchestration.review_loop import run_review_cycle
from bizinsight.schemas import ReviewStatus, WorkerName
from tests.unit.agents.test_reviewer_rules import _metric_finding

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def reviewer(tmp_path_factory: pytest.TempPathFactory) -> EvidenceReviewerAgent:
    root = tmp_path_factory.mktemp("revision-data")
    database = write_dataset(generate_dataset(), root).database_path
    provider = BusinessDataProvider(
        database_path=database,
        table_dictionary_path=PROJECT_ROOT / "data/data_dictionary/tables.yaml",
        metric_dictionary_path=PROJECT_ROOT / "data/data_dictionary/metrics.yaml",
    )
    return EvidenceReviewerAgent(provider=provider)


@pytest.mark.asyncio
async def test_successful_revision_is_reviewed_once_and_accepted(
    reviewer: EvidenceReviewerAgent,
) -> None:
    calls = 0

    async def revise(request):
        nonlocal calls
        calls += 1
        assert request.target_agent is WorkerName.CUSTOMER_PRODUCT
        return _metric_finding(Decimal("0.728395"))

    cycle = await run_review_cycle(
        [_metric_finding(Decimal("0.900000"))],
        owners={"FINDING-renewal-review": WorkerName.CUSTOMER_PRODUCT},
        reviewer=reviewer,
        revise=revise,
    )

    assert calls == 1
    assert cycle.revision_count == 1
    assert cycle.final_review.status is ReviewStatus.ACCEPTED


@pytest.mark.asyncio
async def test_unresolved_revision_is_rejected_without_second_loop(
    reviewer: EvidenceReviewerAgent,
) -> None:
    calls = 0

    async def revise(_request):
        nonlocal calls
        calls += 1
        return _metric_finding(Decimal("0.910000"))

    cycle = await run_review_cycle(
        [_metric_finding(Decimal("0.900000"))],
        owners={"FINDING-renewal-review": WorkerName.CUSTOMER_PRODUCT},
        reviewer=reviewer,
        revise=revise,
    )

    assert calls == 1
    assert cycle.revision_count == 1
    assert cycle.final_review.status is ReviewStatus.REJECTED
    assert cycle.final_review.data_limitations
