"""Scorers distinguish correct and incorrect benchmark outputs."""

from datetime import UTC, datetime
from decimal import Decimal

from bizinsight.schemas import Evidence, EvidenceType, Finding, MetricValue
from evaluations.scorers import (
    score_anomaly_coverage,
    score_evidence_completeness,
    score_metric_accuracy,
)


def _finding(value: str) -> Finding:
    evidence = Evidence(
        evidence_id="CALC-eval1",
        evidence_type=EvidenceType.CALCULATION,
        source="metric:revenue",
        locator="2026-Q2",
        summary="复算",
        generated_at=datetime.now(UTC),
    )
    return Finding(
        finding_id="FINDING-eval",
        title="收入下降",
        fact_statement="收入下降。",
        metrics=[
            MetricValue(
                metric_name="revenue",
                value=Decimal(value),
                unit="CNY",
                period="2026-Q2",
                calculation="sum",
                evidence_ids=[evidence.evidence_id],
            )
        ],
        evidence=[evidence],
        business_interpretation="经营承压。",
        confidence=0.8,
    )


def test_correct_answer_scores_higher_than_wrong_answer():
    correct = _finding("16400000")
    wrong = _finding("1")
    assert score_metric_accuracy([correct], {"revenue": 16400000}) == 100
    assert score_metric_accuracy([wrong], {"revenue": 16400000}) == 0
    assert score_anomaly_coverage([correct], ["收入"]) == 100
    assert score_evidence_completeness([correct]) == 100
