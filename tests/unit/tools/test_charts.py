"""Tests for headless and path-restricted chart rendering."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from bizinsight.tools.charts import ChartSeries, ChartSpec, render_chart


def _chart_spec() -> ChartSpec:
    return ChartSpec(
        title="季度营业收入",
        chart_type="bar",
        x_label="季度",
        y_label="万元",
        series=[
            ChartSeries(
                name="营业收入",
                labels=["2026-Q1", "2026-Q2"],
                values=[1870, 1640],
            ),
        ],
    )


def test_chart_renders_png_without_a_gui(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs"

    artifact = render_chart(
        _chart_spec(),
        output_dir=output_dir,
        filename="revenue.png",
    )

    assert artifact.path == output_dir / "revenue.png"
    assert artifact.path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert len(artifact.sha256) == 64


@pytest.mark.parametrize("filename", ["../escape.png", "chart.svg", "a/b.png"])
def test_chart_cannot_escape_output_directory(
    tmp_path: Path,
    filename: str,
) -> None:
    with pytest.raises(ValueError, match="filename"):
        render_chart(
            _chart_spec(),
            output_dir=tmp_path / "outputs",
            filename=filename,
        )


def test_chart_rejects_mismatched_labels_and_values() -> None:
    with pytest.raises(ValidationError, match="same number"):
        ChartSeries(
            name="营业收入",
            labels=["2026-Q1", "2026-Q2"],
            values=[1870],
        )
