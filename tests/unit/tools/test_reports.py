"""Report filtering, evidence links, and offline asset tests."""

from datetime import UTC, datetime
from decimal import Decimal

from bizinsight.schemas import (
    Evidence,
    EvidenceType,
    Finding,
    MetricValue,
    ReviewResult,
    ReviewStatus,
)
from bizinsight.tools.reports import ActionRecommendation, ReportBuilder


def test_report_only_contains_reviewed_findings_and_local_assets(tmp_path):
    evidence = Evidence(
        evidence_id="CALC-report1",
        evidence_type=EvidenceType.CALCULATION,
        source="metric:revenue",
        locator="2026-Q2",
        summary="收入复算",
        generated_at=datetime.now(UTC),
    )
    finding = Finding(
        finding_id="FINDING-report",
        title="收入下降",
        fact_statement="收入为 120。",
        metrics=[
            MetricValue(
                metric_name="revenue",
                value=Decimal("120"),
                unit="CNY",
                period="2026-Q2",
                calculation="sum",
                evidence_ids=[evidence.evidence_id],
            )
        ],
        evidence=[evidence],
        business_interpretation="收入承压。",
        confidence=0.8,
    )
    rejected = finding.model_copy(
        update={"finding_id": "FINDING-hidden", "title": "不应出现"}
    )
    review = ReviewResult(
        status=ReviewStatus.PARTIAL,
        accepted_finding_ids=[finding.finding_id],
        rejected_finding_ids=[rejected.finding_id],
        reviewer_notes="checked",
    )
    artifact = ReportBuilder(tmp_path).build(
        question="为什么下降？",
        findings=[finding, rejected],
        review=review,
        actions=[
            ActionRecommendation(
                priority="P0",
                action="复盘重点客户",
                rationale="收入下降",
                owner_type="销售负责人",
                timeframe="两周",
            )
        ],
    )
    assert "120" in artifact.markdown
    assert "不应出现" not in artifact.markdown
    assert "#evidence-calc-report1" in artifact.markdown
    assert 'src="charts/revenue.png"' in artifact.html
    assert artifact.html_path.exists() and artifact.chart_paths[0].exists()
