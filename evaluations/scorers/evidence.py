"""Traceability scorer for accepted business findings."""

from __future__ import annotations

from collections.abc import Sequence

from bizinsight.schemas import Finding


def score_evidence_completeness(findings: Sequence[Finding]) -> float:
    """Require key findings and every metric reference to have attached evidence."""

    key_findings = [item for item in findings if item.is_key]
    if not key_findings:
        return 100.0 if findings else 0.0
    scores = []
    for finding in key_findings:
        attached = {item.evidence_id for item in finding.evidence}
        referenced = {
            evidence_id
            for metric in finding.metrics
            for evidence_id in metric.evidence_ids
        }
        scores.append(bool(attached) and referenced <= attached)
    return round(100 * sum(scores) / len(scores), 2)
