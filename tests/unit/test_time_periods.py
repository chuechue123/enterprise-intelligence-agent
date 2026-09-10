from pathlib import Path

from bizinsight.app import _provider
from bizinsight.time_periods import parse_quarters, resolve_periods


def test_parse_chinese_and_canonical_quarters() -> None:
    assert parse_quarters("比较2026年第一季度和2025-Q4") == ["2026-Q1", "2025-Q4"]


def test_default_period_comes_from_database() -> None:
    root = Path(__file__).resolve().parents[2]
    assert resolve_periods("分析经营表现", _provider(root)) == (
        "2026-Q2",
        "2026-Q1",
        True,
    )
