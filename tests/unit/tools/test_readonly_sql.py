"""Safety and contract tests for read-only business data access."""

from __future__ import annotations

from pathlib import Path

import pytest

from bizinsight.data.provider import (
    BusinessDataProvider,
    QueryTimeoutError,
    UnsafeQueryError,
)
from bizinsight.schemas import EvidenceType
from bizinsight.tools.database import execute_readonly_sql

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def provider(generated_database_path: Path) -> BusinessDataProvider:
    return BusinessDataProvider(
        database_path=generated_database_path,
        table_dictionary_path=(
            PROJECT_ROOT / "data" / "data_dictionary" / "tables.yaml"
        ),
        metric_dictionary_path=(
            PROJECT_ROOT / "data" / "data_dictionary" / "metrics.yaml"
        ),
        max_rows=100,
        timeout_ms=1_000,
    )


def test_provider_lists_and_describes_only_business_datasets(
    provider: BusinessDataProvider,
) -> None:
    datasets = provider.list_datasets()

    assert datasets == (
        "contracts",
        "customers",
        "opportunities",
        "payments",
        "product_usage",
        "projects",
        "subscriptions",
        "support_tickets",
    )
    schema = provider.describe_schema("contracts")
    assert schema["primary_key"] == "contract_id"
    assert schema["columns"]["recognized_revenue"]


def test_select_and_read_only_cte_return_traceable_evidence(
    provider: BusinessDataProvider,
) -> None:
    result = execute_readonly_sql(
        provider,
        """
        WITH q2 AS (
            SELECT contract_id, recognized_revenue
            FROM contracts
            WHERE recognition_quarter = ?
        )
        SELECT SUM(recognized_revenue) AS revenue FROM q2
        """,
        parameters=("2026-Q2",),
    )

    assert result.rows == ({"revenue": 16_400_000},)
    assert result.evidence.evidence_type is EvidenceType.DATABASE
    assert result.evidence.evidence_id.startswith("DB-")
    assert "WITH q2" in result.evidence.locator


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO customers VALUES ('x', 'x', 'x', 'x', 'x', 'x')",
        "UPDATE customers SET customer_name = 'x'",
        "DELETE FROM customers",
        "DROP TABLE customers",
        "ALTER TABLE customers ADD COLUMN secret TEXT",
        "CREATE TABLE secret(value TEXT)",
        "ATTACH DATABASE 'other.db' AS other",
        "DETACH DATABASE main",
        "PRAGMA table_info(customers)",
        "VACUUM",
        "SELECT 1; SELECT 2",
        "WITH changed AS (DELETE FROM customers RETURNING *) SELECT * FROM changed",
    ],
)
def test_dangerous_or_multiple_statements_are_rejected(
    provider: BusinessDataProvider,
    sql: str,
) -> None:
    with pytest.raises(UnsafeQueryError):
        provider.execute_readonly_query(sql)


def test_sql_keywords_inside_a_string_are_not_treated_as_commands(
    provider: BusinessDataProvider,
) -> None:
    result = provider.execute_readonly_query(
        "SELECT 'drop table is text, not SQL' AS phrase",
    )

    assert result.rows[0]["phrase"] == "drop table is text, not SQL"


def test_result_rows_are_capped_and_truncation_is_reported(
    provider: BusinessDataProvider,
) -> None:
    result = provider.execute_readonly_query(
        "SELECT customer_id FROM customers ORDER BY customer_id",
        max_rows=3,
    )

    assert len(result.rows) == 3
    assert result.truncated is True
    assert "截断" in result.evidence.summary


def test_long_running_query_is_interrupted(provider: BusinessDataProvider) -> None:
    sql = """
        WITH RECURSIVE counter(x) AS (
            VALUES(0)
            UNION ALL
            SELECT x + 1 FROM counter WHERE x < 10000000
        )
        SELECT SUM(x) FROM counter
    """

    with pytest.raises(QueryTimeoutError):
        provider.execute_readonly_query(sql, timeout_ms=1)


def test_unknown_dataset_is_rejected(provider: BusinessDataProvider) -> None:
    with pytest.raises(KeyError, match="unknown dataset"):
        provider.describe_schema("sqlite_master")
