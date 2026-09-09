"""Deterministic metric and anomaly-coverage scorers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal

from bizinsight.schemas import Finding


def score_metric_accuracy(
    findings: Sequence[Finding],
    expected: Mapping[str, float | int | str],
    *,
    tolerance: Decimal = Decimal("0.000001"),
) -> float:
    """Score expected Q2 metrics against structured MetricValue objects."""

    if not expected:
        return 100.0
    actual = {
        metric.metric_name: metric.value
        for finding in findings
        for metric in finding.metrics
        if metric.period == "2026-Q2"
    }
    correct = sum(
        name in actual and abs(actual[name] - Decimal(str(value))) <= tolerance
        for name, value in expected.items()
    )
    return round(100 * correct / len(expected), 2)


def score_anomaly_coverage(
    findings: Sequence[Finding],
    expected_keywords: Sequence[str],
) -> float:
    """Measure whether each expected anomaly appears in an accepted conclusion."""

    if not expected_keywords:
        return 100.0
    text = " ".join(
        f"{item.title} {item.fact_statement} {item.business_interpretation}"
        for item in findings
    )
    hits = sum(keyword in text for keyword in expected_keywords)
    return round(100 * hits / len(expected_keywords), 2)
