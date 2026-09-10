"""Command-line fallback for the complete BizInsight workflow."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from bizinsight.app import run_analysis
from bizinsight.config import BizInsightSettings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", required=True)
    parser.add_argument("--mode", choices=("offline", "online"), default="offline")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/latest"))
    parser.add_argument("--session-id", default="cli")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    return parser.parse_args()


async def _main() -> None:
    args = parse_args()
    settings = BizInsightSettings()
    if args.mode == "online":
        settings.require_online_model()
    result = await run_analysis(
        args.question,
        project_root=args.project_root.resolve(),
        output_dir=args.output_dir.resolve(),
        session_id=args.session_id,
        settings=settings,
        mode=args.mode,
    )
    print(
        json.dumps(
            {
                "mode": args.mode,
                "review_status": result.review.status.value,
                "finding_count": len(result.findings),
                "report_markdown": str(result.report.markdown_path),
                "report_html": str(result.report.html_path),
                "events": str(result.event_path),
                "errors": result.errors,
                "run_id": result.telemetry.run_id,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
