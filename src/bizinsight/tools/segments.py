"""Controlled, parameterized segmentation queries for business diagnosis."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bizinsight.data.provider import BusinessDataProvider
from bizinsight.schemas import Evidence

DIMENSIONS = {
    "region": "c.region",
    "industry": "c.industry",
    "size_segment": "c.size_segment",
    "product": "d.product",
    "product_version": "d.product_version",
}
DATASETS = {
    "contracts": ("recognition_quarter", "recognized_revenue"),
    "opportunities": ("close_quarter", "amount"),
    "subscriptions": ("quarter", "mrr"),
    "product_usage": ("quarter", "active_users"),
    "projects": ("planned_acceptance_quarter", "deferred_revenue"),
    "support_tickets": ("quarter", None),
}


@dataclass(frozen=True)
class SegmentResult:
    dataset: str
    dimension: str
    period: str
    rows: tuple[dict[str, Any], ...]
    evidence: Evidence


def analyze_segments(
    provider: BusinessDataProvider,
    *,
    dataset: str,
    dimension: str,
    period: str,
    dimension_value: str | None = None,
) -> SegmentResult:
    """Group one dataset by an allowlisted dimension using bound values."""
    if dataset not in DATASETS:
        raise ValueError(f"unsupported segment dataset: {dataset}")
    if dimension not in DIMENSIONS:
        raise ValueError(f"unsupported segment dimension: {dimension}")
    period_column, value_column = DATASETS[dataset]
    if dimension in {"product", "product_version"}:
        schema = provider.describe_schema(dataset)
        if dimension not in schema["columns"]:
            raise ValueError(f"{dimension} is unavailable for {dataset}")
        dimension_sql = f'd."{dimension}"'
        join = ""
        scope = (dataset,)
    else:
        dimension_sql = DIMENSIONS[dimension]
        join = " JOIN customers c ON c.customer_id = d.customer_id"
        scope = (dataset, "customers")
    aggregate = (
        "COUNT(*) AS record_count"
        if value_column is None
        else f'COUNT(*) AS record_count, SUM(d."{value_column}") AS total_value'
    )
    sql = (
        f'SELECT {dimension_sql} AS segment, {aggregate} FROM "{dataset}" d'
        f'{join} WHERE d."{period_column}" = ?'
    )
    parameters: list[str] = [period]
    if dimension_value is not None:
        sql += f" AND {dimension_sql} = ?"
        parameters.append(dimension_value)
    sql += f" GROUP BY {dimension_sql} ORDER BY record_count DESC"
    result = provider.execute_readonly_query(
        sql,
        parameters=parameters,
        allowed_datasets=scope,
    )
    return SegmentResult(dataset, dimension, period, result.rows, result.evidence)
