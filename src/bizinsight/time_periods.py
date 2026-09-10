"""Quarter parsing and data-driven defaults for business questions."""

from __future__ import annotations

import re
from datetime import date

from bizinsight.schemas import DateRange

_ZH = {"一": 1, "二": 2, "三": 3, "四": 4}
_PATTERN = re.compile(
    r"(20\d{2})\s*年?\s*(?:第?\s*([一二三四1234])\s*季度|[-\s]?Q([1-4]))",
    re.IGNORECASE,
)


def parse_quarters(text: str) -> list[str]:
    """Extract canonical quarters in mention order without duplicates."""
    values: list[str] = []
    for match in _PATTERN.finditer(text):
        token = match.group(2) or match.group(3)
        quarter = int(token) if token.isdigit() else _ZH[token]
        value = f"{match.group(1)}-Q{quarter}"
        if value not in values:
            values.append(value)
    return values


def previous_quarter(period: str) -> str:
    year, quarter = int(period[:4]), int(period[-1])
    return f"{year - 1}-Q4" if quarter == 1 else f"{year}-Q{quarter - 1}"


def quarter_range(period: str) -> DateRange:
    year, quarter = int(period[:4]), int(period[-1])
    months = {1: (1, 3, 31), 2: (4, 6, 30), 3: (7, 9, 30), 4: (10, 12, 31)}
    start_month, end_month, end_day = months[quarter]
    return DateRange(
        start_date=date(year, start_month, 1),
        end_date=date(year, end_month, end_day),
    )


def available_quarters(provider: object) -> list[str]:
    """Discover periods from the database instead of encoding a demo quarter."""
    columns = (
        ("contracts", "recognition_quarter"),
        ("subscriptions", "quarter"),
        ("projects", "planned_acceptance_quarter"),
        ("opportunities", "close_quarter"),
    )
    periods: set[str] = set()
    for table, column in columns:
        result = provider.execute_readonly_query(
            f'SELECT DISTINCT "{column}" AS period FROM "{table}"',
            allowed_datasets=(table,),
        )
        periods.update(
            str(row["period"])
            for row in result.rows
            if row["period"] and re.fullmatch(r"\d{4}-Q[1-4]", str(row["period"]))
        )
    return sorted(periods)


def resolve_periods(question: str, provider: object) -> tuple[str, str, bool]:
    mentioned = parse_quarters(question)
    known = available_quarters(provider)
    if len(mentioned) >= 2:
        current, comparison = mentioned[0], mentioned[1]
    elif mentioned:
        current, comparison = mentioned[0], previous_quarter(mentioned[0])
    else:
        if not known:
            raise ValueError("数据库中没有可分析季度")
        current, comparison = known[-1], previous_quarter(known[-1])
    unavailable = [item for item in (current, comparison) if item not in known]
    if unavailable:
        raise ValueError("请求期间超出数据范围: " + ", ".join(unavailable))
    return current, comparison, not bool(mentioned)
