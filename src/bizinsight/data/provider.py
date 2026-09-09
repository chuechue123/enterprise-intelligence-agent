"""Read-only access to BizInsight's structured business data."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from bizinsight.schemas import Evidence, EvidenceType

FIRST_KEYWORD_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
FORBIDDEN_KEYWORDS = frozenset(
    {
        "ALTER",
        "ANALYZE",
        "ATTACH",
        "CREATE",
        "DELETE",
        "DETACH",
        "DROP",
        "INSERT",
        "PRAGMA",
        "REINDEX",
        "REPLACE",
        "TRIGGER",
        "UPDATE",
        "VACUUM",
    },
)
WRITE_ACTION_NAMES = (
    "SQLITE_ALTER_TABLE",
    "SQLITE_ANALYZE",
    "SQLITE_ATTACH",
    "SQLITE_CREATE_INDEX",
    "SQLITE_CREATE_TABLE",
    "SQLITE_CREATE_TEMP_INDEX",
    "SQLITE_CREATE_TEMP_TABLE",
    "SQLITE_CREATE_TEMP_TRIGGER",
    "SQLITE_CREATE_TEMP_VIEW",
    "SQLITE_CREATE_TRIGGER",
    "SQLITE_CREATE_VIEW",
    "SQLITE_DELETE",
    "SQLITE_DETACH",
    "SQLITE_DROP_INDEX",
    "SQLITE_DROP_TABLE",
    "SQLITE_DROP_TEMP_INDEX",
    "SQLITE_DROP_TEMP_TABLE",
    "SQLITE_DROP_TEMP_TRIGGER",
    "SQLITE_DROP_TEMP_VIEW",
    "SQLITE_DROP_TRIGGER",
    "SQLITE_DROP_VIEW",
    "SQLITE_INSERT",
    "SQLITE_PRAGMA",
    "SQLITE_REINDEX",
    "SQLITE_SAVEPOINT",
    "SQLITE_TRANSACTION",
    "SQLITE_UPDATE",
)
WRITE_ACTIONS = frozenset(
    getattr(sqlite3, name) for name in WRITE_ACTION_NAMES if hasattr(sqlite3, name)
)


class UnsafeQueryError(ValueError):
    """Raised before a query can perform a disallowed operation."""


class QueryTimeoutError(TimeoutError):
    """Raised when SQLite exceeds the configured execution deadline."""


@dataclass(frozen=True)
class QueryResult:
    """Bounded rows and the evidence required to reproduce their query."""

    columns: tuple[str, ...]
    rows: tuple[dict[str, Any], ...]
    truncated: bool
    duration_ms: float
    query: str
    parameters: tuple[Any, ...]
    evidence: Evidence


def _mask_literals_and_comments(sql: str) -> str:
    """Mask quoted values, identifiers and comments while preserving separators."""

    output: list[str] = []
    index = 0
    length = len(sql)
    while index < length:
        current = sql[index]
        following = sql[index + 1] if index + 1 < length else ""

        if current == "-" and following == "-":
            output.extend("  ")
            index += 2
            while index < length and sql[index] not in "\r\n":
                output.append(" ")
                index += 1
            continue
        if current == "/" and following == "*":
            output.extend("  ")
            index += 2
            while index + 1 < length and sql[index : index + 2] != "*/":
                output.append(" ")
                index += 1
            if index + 1 >= length:
                raise UnsafeQueryError("SQL contains an unclosed block comment")
            output.extend("  ")
            index += 2
            continue
        if current in {"'", '"', "`"}:
            delimiter = current
            output.append(" ")
            index += 1
            while index < length:
                if sql[index] == delimiter:
                    if index + 1 < length and sql[index + 1] == delimiter:
                        output.extend("  ")
                        index += 2
                        continue
                    output.append(" ")
                    index += 1
                    break
                output.append(" ")
                index += 1
            else:
                raise UnsafeQueryError("SQL contains an unclosed quoted value")
            continue
        if current == "[":
            output.append(" ")
            index += 1
            while index < length and sql[index] != "]":
                output.append(" ")
                index += 1
            if index >= length:
                raise UnsafeQueryError("SQL contains an unclosed quoted identifier")
            output.append(" ")
            index += 1
            continue

        output.append(current)
        index += 1
    return "".join(output)


def validate_readonly_sql(sql: str) -> str:
    """Return normalized SQL when it is one SELECT or read-only WITH statement."""

    normalized = sql.strip()
    if not normalized:
        raise UnsafeQueryError("SQL must not be empty")

    masked = _mask_literals_and_comments(normalized).strip()
    semicolons = [index for index, char in enumerate(masked) if char == ";"]
    if semicolons:
        if len(semicolons) != 1 or masked[semicolons[0] + 1 :].strip():
            raise UnsafeQueryError("multiple SQL statements are not allowed")
        normalized = normalized[: semicolons[0]].rstrip()
        masked = masked[: semicolons[0]].rstrip()

    keywords = [
        match.group(0).upper()
        for match in FIRST_KEYWORD_PATTERN.finditer(masked)
    ]
    if not keywords or keywords[0] not in {"SELECT", "WITH"}:
        raise UnsafeQueryError("only SELECT or read-only WITH statements are allowed")
    forbidden = FORBIDDEN_KEYWORDS.intersection(keywords)
    if forbidden:
        names = ", ".join(sorted(forbidden))
        raise UnsafeQueryError(f"disallowed SQL keyword: {names}")
    return normalized


class BusinessDataProvider:
    """Unified, bounded and read-only access to business tables and dictionaries."""

    def __init__(
        self,
        *,
        database_path: Path,
        table_dictionary_path: Path,
        metric_dictionary_path: Path,
        max_rows: int = 500,
        timeout_ms: int = 2_000,
    ) -> None:
        self.database_path = database_path.resolve()
        self.table_dictionary_path = table_dictionary_path.resolve()
        self.metric_dictionary_path = metric_dictionary_path.resolve()
        if not self.database_path.is_file():
            raise FileNotFoundError(f"database not found: {self.database_path}")
        if max_rows < 1:
            raise ValueError("max_rows must be positive")
        if timeout_ms < 1:
            raise ValueError("timeout_ms must be positive")
        self.max_rows = max_rows
        self.timeout_ms = timeout_ms
        self._table_dictionary = self._load_dictionary(
            self.table_dictionary_path,
            "tables",
        )
        self._metric_dictionary = self._load_dictionary(
            self.metric_dictionary_path,
            "metrics",
        )

    @staticmethod
    def _load_dictionary(path: Path, section: str) -> dict[str, dict[str, Any]]:
        if not path.is_file():
            raise FileNotFoundError(f"data dictionary not found: {path}")
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        values = payload.get(section) if isinstance(payload, dict) else None
        if not isinstance(values, dict):
            raise ValueError(f"{path.name} must define a {section!r} mapping")
        return values

    @classmethod
    def from_project_root(
        cls,
        root: Path,
        *,
        max_rows: int = 500,
        timeout_ms: int = 2_000,
    ) -> BusinessDataProvider:
        root = root.resolve()
        return cls(
            database_path=root / "data" / "database" / "bizinsight.sqlite",
            table_dictionary_path=root / "data" / "data_dictionary" / "tables.yaml",
            metric_dictionary_path=root / "data" / "data_dictionary" / "metrics.yaml",
            max_rows=max_rows,
            timeout_ms=timeout_ms,
        )

    def _connect(self) -> sqlite3.Connection:
        uri = f"{self.database_path.as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row

        def authorizer(
            action: int,
            _arg1: str | None,
            _arg2: str | None,
            _database: str | None,
            _trigger: str | None,
        ) -> int:
            if action in WRITE_ACTIONS:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorizer)
        return connection

    def list_datasets(self) -> tuple[str, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name",
            ).fetchall()
        actual_tables = {str(row["name"]) for row in rows}
        return tuple(sorted(actual_tables.intersection(self._table_dictionary)))

    def describe_schema(self, dataset: str | None = None) -> dict[str, Any]:
        if dataset is None:
            return {
                name: dict(self._table_dictionary[name])
                for name in self.list_datasets()
            }
        if dataset not in self.list_datasets():
            raise KeyError(f"unknown dataset: {dataset}")
        return dict(self._table_dictionary[dataset])

    def get_metric_definition(self, metric_name: str) -> dict[str, Any]:
        try:
            return dict(self._metric_dictionary[metric_name])
        except KeyError as exc:
            raise KeyError(f"unknown metric: {metric_name}") from exc

    def execute_readonly_query(
        self,
        sql: str,
        *,
        parameters: Sequence[Any] = (),
        max_rows: int | None = None,
        timeout_ms: int | None = None,
    ) -> QueryResult:
        query = validate_readonly_sql(sql)
        requested_rows = self.max_rows if max_rows is None else max_rows
        requested_timeout = self.timeout_ms if timeout_ms is None else timeout_ms
        if requested_rows < 1:
            raise ValueError("max_rows must be positive")
        if requested_timeout < 1:
            raise ValueError("timeout_ms must be positive")
        row_limit = min(requested_rows, self.max_rows)
        query_timeout = min(requested_timeout, self.timeout_ms)
        bound_parameters = tuple(parameters)
        wrapped_query = f"SELECT * FROM ({query}) AS _bizinsight_query LIMIT ?"
        deadline = time.monotonic() + query_timeout / 1_000
        started = time.monotonic()

        with self._connect() as connection:
            connection.set_progress_handler(
                lambda: int(time.monotonic() >= deadline),
                100,
            )
            try:
                cursor = connection.execute(
                    wrapped_query,
                    (*bound_parameters, row_limit + 1),
                )
                raw_rows = cursor.fetchall()
            except sqlite3.OperationalError as exc:
                if "interrupted" in str(exc).lower():
                    raise QueryTimeoutError(
                        f"query exceeded {query_timeout} ms timeout",
                    ) from exc
                if "not authorized" in str(exc).lower():
                    raise UnsafeQueryError(
                        "SQLite denied a non-read operation",
                    ) from exc
                raise
            finally:
                connection.set_progress_handler(None, 0)

        duration_ms = (time.monotonic() - started) * 1_000
        truncated = len(raw_rows) > row_limit
        rows = tuple(dict(row) for row in raw_rows[:row_limit])
        columns = tuple(raw_rows[0].keys()) if raw_rows else ()
        query_identity = json.dumps(
            {"query": query, "parameters": bound_parameters},
            ensure_ascii=False,
            default=str,
            sort_keys=True,
        )
        digest = hashlib.sha256(query_identity.encode("utf-8")).hexdigest()[:16]
        summary = f"只读查询返回 {len(rows)} 行"
        if truncated:
            summary += f"，结果已按 {row_limit} 行上限截断"
        evidence = Evidence(
            evidence_id=f"DB-{digest}",
            evidence_type=EvidenceType.DATABASE,
            source=self.database_path.name,
            locator=f"SQL: {query} | parameters: {list(bound_parameters)!r}",
            summary=summary,
            generated_at=datetime.now(UTC),
        )
        return QueryResult(
            columns=columns,
            rows=rows,
            truncated=truncated,
            duration_ms=duration_ms,
            query=query,
            parameters=bound_parameters,
            evidence=evidence,
        )

    def fetch_evidence_rows(
        self,
        dataset: str,
        identifiers: Sequence[str],
    ) -> QueryResult:
        schema = self.describe_schema(dataset)
        primary_key = str(schema["primary_key"])
        values = tuple(identifiers)
        if not values:
            raise ValueError("identifiers must not be empty")
        if len(values) > self.max_rows:
            raise ValueError("identifier count exceeds max_rows")
        placeholders = ", ".join("?" for _ in values)
        return self.execute_readonly_query(
            f'SELECT * FROM "{dataset}" WHERE "{primary_key}" IN ({placeholders})',
            parameters=values,
            max_rows=len(values),
        )
