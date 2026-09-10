"""Immutable Worker scopes shared by local and MCP adapters."""

from __future__ import annotations

from bizinsight.schemas import WorkerName

MCP_SCOPES = {
    WorkerName.FINANCE_SALES.value: {
        "datasets": frozenset({"contracts", "customers", "opportunities", "payments"}),
        "metrics": frozenset({"gross_margin", "revenue", "win_rate"}),
    },
    WorkerName.CUSTOMER_PRODUCT.value: {
        "datasets": frozenset(
            {
                "contracts",
                "customers",
                "product_usage",
                "subscriptions",
                "support_tickets",
            }
        ),
        "metrics": frozenset({"renewal_rate"}),
    },
    WorkerName.DELIVERY.value: {
        "datasets": frozenset({"contracts", "customers", "projects"}),
        "metrics": frozenset({"on_time_acceptance_rate"}),
    },
}

TOOL_NAMES = (
    "list_business_datasets",
    "describe_business_dataset",
    "calculate_business_metric",
    "compare_business_periods",
    "query_business_data",
)


def require_scope(scope: str) -> dict[str, frozenset[str]]:
    try:
        return MCP_SCOPES[scope]
    except KeyError as exc:
        raise ValueError(f"unknown immutable MCP scope: {scope}") from exc
