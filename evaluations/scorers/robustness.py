"""Runtime robustness and report-contract scorers."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from bizinsight.tools.reports import REPORT_SECTIONS


def score_robustness(errors: Sequence[str], *, report_exists: bool) -> float:
    """Reward completion and isolate each recorded task error."""

    if not report_exists:
        return 0.0
    return max(0.0, 100.0 - 25.0 * len(errors))


def score_report_quality(markdown_path: Path) -> float:
    """Check the stable management-report structure and audit affordances."""

    if not markdown_path.is_file():
        return 0.0
    text = markdown_path.read_text(encoding="utf-8")
    section_score = (
        70 * sum(name in text for name in REPORT_SECTIONS) / len(REPORT_SECTIONS)
    )
    evidence_score = 15 if "#evidence-" in text else 0
    action_score = 10 if "P0" in text else 0
    chart_score = 5 if "charts/" in text else 0
    return round(section_score + evidence_score + action_score + chart_score, 2)
