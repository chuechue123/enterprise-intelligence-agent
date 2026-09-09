"""Deterministic evidence reviewer rule tests."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from bizinsight.agents.reviewer import EvidenceReviewerAgent
from bizinsight.data.generator import generate_dataset, write_dataset
from bizinsight.data.provider import BusinessDataProvider
from bizinsight.schemas import (
    Evidence,
    EvidenceType,
    Finding,
    MetricValue,
    ReviewStatus,
    WorkerName,
)
from bizinsight.tools.metrics import calculate_metric

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def provider(tmp_path_factory: pytest.TempPathFactory) -> BusinessDataProvider:
    root = tmp_path_factory.mktemp("review-data")
    database = write_dataset(generate_dataset(), root).database_path
    return BusinessDataProvider(
        database_path=database,
        table_dictionary_path=PROJECT_ROOT / "data/data_dictionary/tables.yaml",
        metric_dictionary_path=PROJECT_ROOT / "data/data_dictionary/metrics.yaml",
    )


def _evidence(kind: EvidenceType = EvidenceType.DATABASE) -> Evidence:
    prefix = {
        EvidenceType.DATABASE: "DB",
        EvidenceType.DOCUMENT: "DOC",
        EvidenceType.WEB: "WEB",
        EvidenceType.CALCULATION: "CALC",
    }[kind]
    kwargs = {}
    if kind is EvidenceType.WEB:
        kwargs = {
            "url": "https://example.com/market",
            "accessed_at": datetime.now(UTC),
        }
    return Evidence(
        evidence_id=f"{prefix}-review001",
        evidence_type=kind,
        source="测试来源",
        locator="测试位置",
        summary="测试证据支持指标复算和结论审查。",
        generated_at=datetime.now(UTC),
        **kwargs,
    )


def _metric_finding(value: Decimal) -> Finding:
    evidence = [_evidence(), _evidence(EvidenceType.CALCULATION)]
    return Finding(
        finding_id="FINDING-renewal-review",
        title="第二季度续费率下降",
        fact_statement="2026-Q2 续费率发生变化。",
        metrics=[
            MetricValue(
                metric_name="renewal_rate",
                value=value,
                unit="ratio",
                period="2026-Q2",
                calculation="renewed / due",
                evidence_ids=[item.evidence_id for item in evidence],
            ),
        ],
        evidence=evidence,
        business_interpretation="客户留存承压。",
        confidence=0.8,
    )


def test_wrong_metric_value_requires_targeted_revision(
    provider: BusinessDataProvider,
) -> None:
    reviewer = EvidenceReviewerAgent(provider=provider)

    result = reviewer.review(
        [_metric_finding(Decimal("0.900000"))],
        owners={"FINDING-renewal-review": WorkerName.CUSTOMER_PRODUCT},
    )

    assert result.status is ReviewStatus.REVISION_REQUIRED
    assert result.revision_requests[0].target_agent is WorkerName.CUSTOMER_PRODUCT
    assert "重新计算" in result.revision_requests[0].required_changes[0]


def test_correct_reproducible_metric_is_accepted(
    provider: BusinessDataProvider,
) -> None:
    expected = calculate_metric(provider, "renewal_rate", "2026-Q2").metric.value

    result = EvidenceReviewerAgent(provider=provider).review(
        [_metric_finding(expected)],
        owners={"FINDING-renewal-review": WorkerName.CUSTOMER_PRODUCT},
    )

    assert result.status is ReviewStatus.ACCEPTED
    assert result.accepted_finding_ids == ["FINDING-renewal-review"]


def test_unsupported_certain_claim_without_evidence_is_rejected(
    provider: BusinessDataProvider,
) -> None:
    finding = Finding(
        finding_id="FINDING-no-evidence",
        title="无证据结论",
        fact_statement="收入下降完全由产品故障造成。",
        business_interpretation="这是没有证据的确定性判断。",
        causal_assessment="产品故障直接导致全部收入下降。",
        confidence=0.9,
        is_key=False,
    )

    result = EvidenceReviewerAgent(provider=provider).review([finding])

    assert result.status is ReviewStatus.REJECTED
    assert finding.finding_id in result.rejected_finding_ids


def test_external_evidence_cannot_directly_prove_internal_cause(
    provider: BusinessDataProvider,
) -> None:
    web = _evidence(EvidenceType.WEB)
    finding = Finding(
        finding_id="FINDING-external-cause",
        title="外部价格竞争",
        fact_statement="行业出现低价竞争。",
        evidence=[web],
        business_interpretation="可能影响价格敏感客户。",
        causal_assessment="外部低价竞争直接导致公司第二季度输单。",
        confidence=0.8,
    )

    result = EvidenceReviewerAgent(provider=provider).review(
        [finding],
        owners={finding.finding_id: WorkerName.EXTERNAL_RESEARCH},
    )

    assert result.status is ReviewStatus.REVISION_REQUIRED
    assert any("内部因果" in item.reason for item in result.revision_requests)
