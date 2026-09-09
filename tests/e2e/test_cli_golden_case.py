"""End-to-end golden case through the public CLI."""

import json
import subprocess
import sys
from pathlib import Path


def test_cli_generates_accepted_offline_report(tmp_path):
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "bizinsight.cli",
            "--mode",
            "offline",
            "--question",
            "请综合分析2026年第二季度经营表现及主要原因",
            "--project-root",
            str(root),
            "--output-dir",
            str(tmp_path),
            "--session-id",
            "golden",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=60,
    )
    payload = json.loads(completed.stdout)
    assert payload["review_status"] == "accepted"
    assert payload["finding_count"] == 4
    assert (tmp_path / "report.html").is_file()
    assert len(list((tmp_path / "charts").glob("*.png"))) == 5
