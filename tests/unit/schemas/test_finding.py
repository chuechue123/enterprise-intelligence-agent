"""Tests for evidence, metric, and finding contracts."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from bizinsight.schemas.evidence import Evidence, EvidenceType
from bizinsight.schemas.finding import Finding, MetricValue

NOW = datetime(2026, 9, 8, 9, 30, tzinfo=UTC)


def _database_evidence() -> Evidence:
    return Evidence(
        evidence_id="DB-revenue-q2",
        evidence_type=EvidenceType.DATABASE,
        source="bizinsight.sqlite/contracts",
        locator="SELECT SUM(recognized_revenue) ...",
        summary="2026 Q2 确认收入汇总",
        generated_at=NOW,
    )


def _calculation_evidence() -> Evidence:
    return Evidence(
        evidence_id="CALC-revenue-q2",
        evidence_type=EvidenceType.CALCULATION,
        source="calculate_metric",
        locator="revenue(period='2026-Q2')",
        summary="按收入确认口径计算第二季度营业收入",
        generated_at=NOW,
    )


def test_web_evidence_requires_url_and_access_time() -> None:
    with pytest.raises(ValidationError, match="url.*accessed_at"):
        Evidence(
            evidence_id="WEB-industry-1",
            evidence_type=EvidenceType.WEB,
            source="industry search",
            locator="enterprise software pricing pressure",
            summary="行业价格竞争加剧",
            generated_at=NOW,
        )


def test_evidence_id_prefix_must_match_type() -> None:
    with pytest.raises(ValidationError, match="prefix"):
        Evidence(
            evidence_id="DOC-wrong-kind",
            evidence_type=EvidenceType.DATABASE,
            source="bizinsight.sqlite/contracts",
            locator="SELECT 1",
            summary="错误类型示例",
            generated_at=NOW,
        )


def test_key_finding_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="key finding.*evidence"):
        Finding(
            finding_id="FINDING-revenue-decline",
            title="收入下降",
            fact_statement="第二季度收入低于第一季度。",
            business_interpretation="可能存在验收推迟。",
            confidence=0.8,
            is_key=True,
        )


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_finding_confidence_must_be_between_zero_and_one(
    confidence: float,
) -> None:
    with pytest.raises(ValidationError):
        Finding(
            finding_id="FINDING-confidence",
            title="置信度非法",
            fact_statement="这是一个事实描述。",
            business_interpretation="这是一个解释。",
            confidence=confidence,
            is_key=True,
            evidence=[_database_evidence()],
        )


def test_metric_must_reference_evidence_attached_to_finding() -> None:
    metric = MetricValue(
        metric_name="营业收入",
        value=Decimal("16400000.00"),
        unit="CNY",
        period="2026-Q2",
        calculation="SUM(contracts.recognized_revenue)",
        evidence_ids=["CALC-revenue-q2"],
    )

    with pytest.raises(ValidationError, match="missing evidence"):
        Finding(
            finding_id="FINDING-revenue",
            title="第二季度收入下降",
            fact_statement="第二季度营业收入为 1640 万元。",
            metrics=[metric],
            evidence=[_database_evidence()],
            business_interpretation="延期验收可能影响收入确认节奏。",
            confidence=0.9,
        )


def test_valid_finding_keeps_fact_interpretation_and_causality_separate() -> None:
    finding = Finding(
        finding_id="FINDING-revenue",
        title="第二季度收入下降",
        fact_statement="第二季度营业收入为 1640 万元。",
        metrics=[
            MetricValue(
                metric_name="营业收入",
                value=Decimal("16400000.00"),
                unit="CNY",
                period="2026-Q2",
                calculation="SUM(contracts.recognized_revenue)",
                evidence_ids=["CALC-revenue-q2"],
            ),
        ],
        evidence=[_database_evidence(), _calculation_evidence()],
        business_interpretation="延期验收可能影响收入确认节奏。",
        causal_assessment="当前证据支持相关关系，尚不足以单独证明因果。",
        confidence=0.9,
    )

    assert finding.fact_statement != finding.business_interpretation
    assert finding.causal_assessment is not None
    assert finding.metrics[0].value == Decimal("16400000.00")
