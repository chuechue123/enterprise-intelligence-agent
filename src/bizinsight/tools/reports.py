"""Deterministic Markdown/HTML reports built only from reviewed findings."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from pydantic import BaseModel, ConfigDict, Field

from bizinsight.schemas import Finding, ReviewResult
from bizinsight.tools.charts import ChartSeries, ChartSpec, render_chart

REPORT_SECTIONS = (
    "执行摘要",
    "核心指标概览",
    "主要异常排名",
    "财务与销售分析",
    "客户、产品与服务分析",
    "项目交付分析",
    "外部行业背景",
    "根因假设与置信度",
    "行动建议",
    "数据限制与待验证问题",
    "证据索引",
)
TREND_METRICS = {
    "revenue": "收入趋势",
    "gross_margin": "毛利率趋势",
    "renewal_rate": "续费率趋势",
    "win_rate": "赢单率趋势",
    "on_time_acceptance_rate": "按时验收率趋势",
}


class ActionRecommendation(BaseModel):
    """A recommendation that is concrete enough for management follow-up."""

    model_config = ConfigDict(extra="forbid")

    priority: Literal["P0", "P1", "P2"]
    action: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    owner_type: str = Field(min_length=1)
    timeframe: str = Field(min_length=1)


@dataclass(frozen=True)
class ReportArtifact:
    """Paths and content for one generated report."""

    markdown_path: Path
    html_path: Path
    chart_paths: tuple[Path, ...]
    markdown: str
    html: str


def _deduplicate_evidence(findings: Sequence[Finding]) -> list[object]:
    indexed = {}
    for finding in findings:
        for evidence in finding.evidence:
            indexed.setdefault(evidence.evidence_id, evidence)
    return list(indexed.values())


class ReportBuilder:
    """Render an auditable management report without asking an LLM to format it."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir.resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        template_dir = Path(__file__).resolve().parents[1] / "templates"
        self.environment = Environment(
            loader=FileSystemLoader(template_dir),
            undefined=StrictUndefined,
            autoescape=select_autoescape(("html", "xml")),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def build(
        self,
        *,
        question: str,
        findings: Sequence[Finding],
        review: ReviewResult,
        actions: Sequence[ActionRecommendation],
        limitations: Sequence[str] = (),
    ) -> ReportArtifact:
        """Filter by the review decision, render five trends, and write two formats."""

        accepted_ids = set(review.accepted_finding_ids)
        accepted = [item for item in findings if item.finding_id in accepted_ids]
        charts = self._render_charts(accepted)
        context = {
            "question": question,
            "findings": accepted,
            "actions": actions,
            "limitations": list(
                dict.fromkeys([*limitations, *review.data_limitations]),
            ),
            "evidence": _deduplicate_evidence(accepted),
            "charts": charts,
            "sections": REPORT_SECTIONS,
            "review": review,
        }
        markdown = self.environment.get_template("report.md.j2").render(**context)
        html = self.environment.get_template("report.html.j2").render(**context)
        markdown_path = self.output_dir / "report.md"
        html_path = self.output_dir / "report.html"
        markdown_path.write_text(markdown, encoding="utf-8")
        html_path.write_text(html, encoding="utf-8")
        return ReportArtifact(
            markdown_path=markdown_path,
            html_path=html_path,
            chart_paths=tuple(item["path"] for item in charts),
            markdown=markdown,
            html=html,
        )

    def _render_charts(self, findings: Sequence[Finding]) -> list[dict[str, object]]:
        values: dict[str, dict[str, float]] = {name: {} for name in TREND_METRICS}
        for finding in findings:
            for metric in finding.metrics:
                if metric.metric_name in values:
                    values[metric.metric_name][metric.period] = float(metric.value)
        charts = []
        chart_dir = self.output_dir / "charts"
        for metric_name, title in TREND_METRICS.items():
            points = values[metric_name]
            if not points:
                continue
            labels = sorted(points)
            artifact = render_chart(
                ChartSpec(
                    title=title,
                    chart_type="line",
                    x_label="期间",
                    y_label=metric_name,
                    series=[
                        ChartSeries(
                            name=title,
                            labels=labels,
                            values=[points[label] for label in labels],
                        ),
                    ],
                ),
                output_dir=chart_dir,
                filename=f"{metric_name}.png",
            )
            charts.append(
                {
                    "title": title,
                    "relative_path": f"charts/{artifact.path.name}",
                    "path": artifact.path,
                },
            )
        return charts
