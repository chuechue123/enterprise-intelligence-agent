"""Deterministic business metrics calculated from read-only SQL results."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from bizinsight.data.provider import BusinessDataProvider
from bizinsight.schemas import Evidence, EvidenceType, MetricValue

PERIOD_PATTERN = re.compile(r"^\d{4}-Q[1-4]$")
RATIO_PRECISION = Decimal("0.000001")
METRIC_QUERIES = {
    "revenue": """
        SELECT
            COALESCE(SUM(recognized_revenue), 0) AS numerator,
            NULL AS denominator
        FROM contracts
        WHERE recognition_quarter = ?
    """,
    "gross_margin": """
        SELECT
            COALESCE(SUM(recognized_revenue), 0)
                - COALESCE(SUM(recognized_cost), 0) AS numerator,
            COALESCE(SUM(recognized_revenue), 0) AS denominator
        FROM contracts
        WHERE recognition_quarter = ?
    """,
    "renewal_rate": """
        SELECT
            SUM(
                CASE
                    WHEN due_for_renewal = 1 AND renewal_status = 'renewed'
                    THEN 1 ELSE 0
                END
            ) AS numerator,
            SUM(CASE WHEN due_for_renewal = 1 THEN 1 ELSE 0 END) AS denominator
        FROM subscriptions
        WHERE quarter = ?
    """,
    "on_time_acceptance_rate": """
        SELECT
            SUM(CASE WHEN on_time = 1 THEN 1 ELSE 0 END) AS numerator,
            COUNT(project_id) AS denominator
        FROM projects
        WHERE planned_acceptance_quarter = ?
    """,
    "win_rate": """
        SELECT
            SUM(CASE WHEN outcome = 'won' THEN 1 ELSE 0 END) AS numerator,
            COUNT(opportunity_id) AS denominator
        FROM opportunities
        WHERE close_quarter = ?
    """,
}


class MetricUnavailableError(ValueError):
    """Raised when a metric has no valid denominator for the requested period."""


@dataclass(frozen=True)
class MetricCalculation:
    """A metric value together with database and calculation evidence."""

    metric: MetricValue
    numerator: Decimal
    denominator: Decimal | None
    evidence: tuple[Evidence, Evidence]


@dataclass(frozen=True)
class MetricComparison:
    """Current and comparison values plus deterministic changes."""

    current: MetricCalculation
    comparison: MetricCalculation
    absolute_change: Decimal
    relative_change: Decimal | None


def _decimal(value: object) -> Decimal:
    if value is None:
        return Decimal(0)
    return Decimal(str(value))


def _validate_period(period: str) -> None:
    if not PERIOD_PATTERN.fullmatch(period):
        raise ValueError("period must use YYYY-Q1 through YYYY-Q4 format")


def calculate_metric(
    provider: BusinessDataProvider,
    metric_name: str,
    period: str,
) -> MetricCalculation:
    """Calculate one registered metric without using an LLM."""

    _validate_period(period)
    definition = provider.get_metric_definition(metric_name)
    try:
        sql = METRIC_QUERIES[metric_name]
    except KeyError as exc:
        raise KeyError(f"unknown metric: {metric_name}") from exc

    query_result = provider.execute_readonly_query(sql, parameters=(period,))
    if not query_result.rows:
        raise MetricUnavailableError(f"no data returned for {metric_name} in {period}")
    row = query_result.rows[0]
    numerator = _decimal(row["numerator"])
    denominator_value = row["denominator"]
    denominator = None if denominator_value is None else _decimal(denominator_value)
    if denominator is None:
        value = numerator
    else:
        if denominator == 0:
            raise MetricUnavailableError(
                f"{metric_name} has a zero denominator in {period}",
            )
        value = (numerator / denominator).quantize(
            RATIO_PRECISION,
            rounding=ROUND_HALF_UP,
        )

    calculation_id = f"CALC-{metric_name.upper()}-{period.replace('-', '_')}"
    calculation_evidence = Evidence(
        evidence_id=calculation_id,
        evidence_type=EvidenceType.CALCULATION,
        source=f"metric:{metric_name}",
        locator=f"formula: {definition['formula']}; period: {period}",
        summary=(
            f"{definition['name_zh']}={value} {definition['unit']}；"
            f"分子={numerator}，分母={denominator}"
        ),
        generated_at=datetime.now(UTC),
    )
    evidence = (query_result.evidence, calculation_evidence)
    metric = MetricValue(
        metric_name=metric_name,
        value=value,
        unit=str(definition["unit"]),
        period=period,
        calculation=str(definition["formula"]),
        evidence_ids=[item.evidence_id for item in evidence],
    )
    return MetricCalculation(
        metric=metric,
        numerator=numerator,
        denominator=denominator,
        evidence=evidence,
    )


def compare_periods(
    provider: BusinessDataProvider,
    metric_name: str,
    *,
    current_period: str,
    comparison_period: str,
) -> MetricComparison:
    """Compare two periods using the same registered metric definition."""

    current = calculate_metric(provider, metric_name, current_period)
    comparison = calculate_metric(provider, metric_name, comparison_period)
    absolute_change = current.metric.value - comparison.metric.value
    relative_change = None
    if comparison.metric.value != 0:
        relative_change = (absolute_change / comparison.metric.value).quantize(
            RATIO_PRECISION,
            rounding=ROUND_HALF_UP,
        )
    return MetricComparison(
        current=current,
        comparison=comparison,
        absolute_change=absolute_change,
        relative_change=relative_change,
    )
