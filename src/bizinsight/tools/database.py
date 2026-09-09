"""Agent-facing wrappers for the read-only business data provider."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from bizinsight.data.provider import BusinessDataProvider, QueryResult


def describe_dataset(
    provider: BusinessDataProvider,
    dataset: str | None = None,
) -> dict[str, Any]:
    """Describe one allowed dataset, or all available datasets."""

    return provider.describe_schema(dataset)


def execute_readonly_sql(
    provider: BusinessDataProvider,
    sql: str,
    *,
    parameters: Sequence[Any] = (),
    max_rows: int | None = None,
    timeout_ms: int | None = None,
) -> QueryResult:
    """Execute one bounded SELECT/read-only CTE and return DB evidence."""

    return provider.execute_readonly_query(
        sql,
        parameters=parameters,
        max_rows=max_rows,
        timeout_ms=timeout_ms,
    )
