"""Tests for deterministic business metric calculations."""

from __future__ import annotations

import inspect
import json
from decimal import Decimal
from pathlib import Path

import pytest

from bizinsight.data.provider import BusinessDataProvider
from bizinsight.schemas import EvidenceType
from bizinsight.tools import metrics
from bizinsight.tools.metrics import calculate_metric, compare_periods

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def provider(generated_database_path: Path) -> BusinessDataProvider:
    return BusinessDataProvider(
        database_path=generated_database_path,
        table_dictionary_path=(
            PROJECT_ROOT / "data" / "data_dictionary" / "tables.yaml"
        ),
        metric_dictionary_path=(
            PROJECT_ROOT / "data" / "data_dictionary" / "metrics.yaml"
        ),
    )


@pytest.fixture(scope="module")
def expected_metrics() -> dict[str, dict[str, float | int]]:
    ground_truth = json.loads(
        (PROJECT_ROOT / "evaluations" / "ground_truth" / "golden_case.json")
        .read_text(encoding="utf-8"),
    )
    return ground_truth["core_metrics"]


@pytest.mark.parametrize(
    "period",
    ["2026-Q1", "2026-Q2"],
)
@pytest.mark.parametrize(
    "metric_name",
    [
        "revenue",
        "gross_margin",
        "renewal_rate",
        "on_time_acceptance_rate",
        "win_rate",
    ],
)
def test_core_metrics_match_ground_truth_exactly(
    provider: BusinessDataProvider,
    expected_metrics: dict[str, dict[str, float | int]],
    period: str,
    metric_name: str,
) -> None:
    result = calculate_metric(provider, metric_name, period)

    assert result.metric.value == Decimal(str(expected_metrics[period][metric_name]))
    assert result.metric.period == period
    assert {item.evidence_type for item in result.evidence} == {
        EvidenceType.DATABASE,
        EvidenceType.CALCULATION,
    }
    assert set(result.metric.evidence_ids) == {
        item.evidence_id for item in result.evidence
    }


def test_period_comparison_calculates_absolute_and_relative_change(
    provider: BusinessDataProvider,
) -> None:
    comparison = compare_periods(
        provider,
        "revenue",
        current_period="2026-Q2",
        comparison_period="2026-Q1",
    )

    assert comparison.current.metric.value == Decimal("16400000")
    assert comparison.comparison.metric.value == Decimal("18700000")
    assert comparison.absolute_change == Decimal("-2300000")
    assert comparison.relative_change == Decimal("-0.122995")


def test_metric_definition_comes_from_data_dictionary(
    provider: BusinessDataProvider,
) -> None:
    definition = provider.get_metric_definition("gross_margin")

    assert definition["name_zh"] == "综合毛利率"
    assert "SUM(recognized_revenue)" in definition["formula"]


def test_unknown_metric_and_invalid_period_are_rejected(
    provider: BusinessDataProvider,
) -> None:
    with pytest.raises(KeyError, match="unknown metric"):
        calculate_metric(provider, "invented_metric", "2026-Q2")
    with pytest.raises(ValueError, match="YYYY-Q"):
        calculate_metric(provider, "revenue", "Q2")


@pytest.mark.parametrize(
    "metric_name",
    [
        "revenue",
        "gross_margin",
        "renewal_rate",
        "on_time_acceptance_rate",
        "win_rate",
    ],
)
def test_metric_with_no_data_raises_instead_of_fabricating_zero(
    provider: BusinessDataProvider,
    metric_name: str,
) -> None:
    # 2025-Q1 predates the synthetic dataset (2025-Q3..2026-Q2); a metric
    # queried there must be reported as unavailable, never as 0 with a
    # CALCULATION evidence that would pass reviewer recalculation.
    with pytest.raises(metrics.MetricUnavailableError):
        calculate_metric(provider, metric_name, "2025-Q1")


def test_runtime_metric_code_never_reads_evaluation_ground_truth() -> None:
    assert "ground_truth" not in inspect.getsource(metrics)
