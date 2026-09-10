"""Scoped read-only Business Data MCP server."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from bizinsight.data.provider import BusinessDataProvider
from bizinsight.mcp.contracts import require_scope
from bizinsight.tools.metrics import calculate_metric, compare_periods


def _provider(root: Path) -> BusinessDataProvider:
    return BusinessDataProvider(
        database_path=root / "data/database/bizinsight.sqlite",
        table_dictionary_path=root / "data/data_dictionary/tables.yaml",
        metric_dictionary_path=root / "data/data_dictionary/metrics.yaml",
    )


def create_mcp_server(*, scope: str, project_root: Path) -> FastMCP:
    """Create one server whose authorization is fixed by its process args."""
    access = require_scope(scope)
    provider = _provider(project_root.resolve())
    server = FastMCP("BizInsight Business Data", log_level="ERROR")

    def require_dataset(dataset: str) -> None:
        if dataset not in access["datasets"]:
            raise PermissionError(f"dataset is outside {scope} scope: {dataset}")

    def require_metric(metric_name: str) -> None:
        if metric_name not in access["metrics"]:
            raise PermissionError(f"metric is outside {scope} scope: {metric_name}")

    @server.tool()
    def list_business_datasets() -> dict[str, Any]:
        """List only the business datasets authorized for this Worker."""
        return {"scope": scope, "datasets": sorted(access["datasets"])}

    @server.tool()
    def describe_business_dataset(dataset: str) -> dict[str, Any]:
        """Describe an authorized dataset without returning its full contents."""
        require_dataset(dataset)
        return provider.describe_schema(dataset)

    @server.tool()
    def calculate_business_metric(metric_name: str, period: str) -> dict[str, Any]:
        """Calculate one allowlisted metric with reproducible evidence."""
        require_metric(metric_name)
        result = calculate_metric(provider, metric_name, period)
        return {
            "metric": result.metric.model_dump(mode="json"),
            "evidence": [item.model_dump(mode="json") for item in result.evidence],
        }

    @server.tool()
    def compare_business_periods(
        metric_name: str, current_period: str, comparison_period: str
    ) -> dict[str, Any]:
        """Compare one allowlisted metric across two quarters."""
        require_metric(metric_name)
        result = compare_periods(
            provider,
            metric_name,
            current_period=current_period,
            comparison_period=comparison_period,
        )
        return {
            "current": result.current.metric.model_dump(mode="json"),
            "comparison": result.comparison.metric.model_dump(mode="json"),
            "absolute_change": str(result.absolute_change),
            "relative_change": None
            if result.relative_change is None
            else str(result.relative_change),
        }

    @server.tool()
    def query_business_data(
        sql: str,
        parameters: list[str | int | float | bool | None] | None = None,
        max_rows: int = 200,
    ) -> dict[str, Any]:
        """Run one bounded SELECT over the Worker's authorized tables."""
        result = provider.execute_readonly_query(
            sql,
            parameters=parameters or (),
            max_rows=min(max_rows, 500),
            allowed_datasets=tuple(access["datasets"]),
        )
        return {
            "columns": list(result.columns),
            "rows": list(result.rows),
            "truncated": result.truncated,
            "evidence": result.evidence.model_dump(mode="json"),
        }

    return server


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args()
    create_mcp_server(scope=args.scope, project_root=args.project_root).run("stdio")


if __name__ == "__main__":
    main()
