from pathlib import Path

import pytest

from bizinsight.app import _provider
from bizinsight.tools.segments import analyze_segments


def test_segment_query_uses_allowlisted_dimension() -> None:
    provider = _provider(Path(__file__).resolve().parents[3])
    result = analyze_segments(
        provider,
        dataset="contracts",
        dimension="region",
        period="2026-Q2",
    )
    assert result.rows
    assert {row["segment"] for row in result.rows} <= {
        "华东",
        "华南",
        "华北",
        "西南",
        "华中",
    }


def test_unknown_dimension_is_rejected_before_sql() -> None:
    provider = _provider(Path(__file__).resolve().parents[3])
    with pytest.raises(ValueError, match="unsupported segment dimension"):
        analyze_segments(
            provider,
            dataset="contracts",
            dimension="password",
            period="2026-Q2",
        )
