"""Headless chart rendering restricted to a caller-provided output directory."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import matplotlib
from pydantic import BaseModel, ConfigDict, Field, model_validator

matplotlib.use("Agg")
matplotlib.rcParams["font.sans-serif"] = [
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "DejaVu Sans",
]
matplotlib.rcParams["axes.unicode_minus"] = False
from matplotlib import pyplot as plt  # noqa: E402

SAFE_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.png$")


class ChartSeries(BaseModel):
    """One validated, labelled numeric series."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    labels: list[str] = Field(min_length=1)
    values: list[float] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_shape_and_values(self) -> ChartSeries:
        if len(self.labels) != len(self.values):
            raise ValueError("labels and values must have the same number of items")
        if any(not label.strip() for label in self.labels):
            raise ValueError("chart labels must not be blank")
        if any(not math.isfinite(value) for value in self.values):
            raise ValueError("chart values must be finite")
        return self


class ChartSpec(BaseModel):
    """A small declarative chart contract accepted by the renderer."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    chart_type: Literal["bar", "line"]
    x_label: str = ""
    y_label: str = ""
    series: list[ChartSeries] = Field(min_length=1, max_length=10)


@dataclass(frozen=True)
class ChartArtifact:
    """A rendered image and its content digest."""

    path: Path
    sha256: str


def render_chart(
    spec: ChartSpec,
    *,
    output_dir: Path,
    filename: str,
) -> ChartArtifact:
    """Render a PNG with the non-interactive Agg backend."""

    if not SAFE_FILENAME_PATTERN.fullmatch(filename):
        raise ValueError("filename must be a plain .png name without directories")
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = (output_dir / filename).resolve()
    if output_path.parent != output_dir:
        raise ValueError("filename must remain inside output_dir")

    figure, axis = plt.subplots(figsize=(8, 4.5), constrained_layout=True)
    try:
        if spec.chart_type == "line":
            for series in spec.series:
                axis.plot(
                    series.labels,
                    series.values,
                    marker="o",
                    label=series.name,
                )
        else:
            label_count = len(spec.series[0].labels)
            if any(len(series.labels) != label_count for series in spec.series):
                raise ValueError("all bar series must have the same number of labels")
            width = 0.8 / len(spec.series)
            positions = list(range(label_count))
            for series_index, series in enumerate(spec.series):
                offsets = [
                    position - 0.4 + width / 2 + series_index * width
                    for position in positions
                ]
                axis.bar(offsets, series.values, width=width, label=series.name)
            axis.set_xticks(positions, spec.series[0].labels)

        axis.set_title(spec.title)
        axis.set_xlabel(spec.x_label)
        axis.set_ylabel(spec.y_label)
        axis.grid(axis="y", alpha=0.25)
        if len(spec.series) > 1:
            axis.legend()
        figure.savefig(output_path, format="png", dpi=144)
    finally:
        plt.close(figure)

    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
    return ChartArtifact(path=output_path, sha256=digest)
