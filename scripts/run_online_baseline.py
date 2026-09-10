"""Run the shared online pipeline repeatedly and preserve safe telemetry."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from bizinsight.app import run_analysis
from bizinsight.config import BizInsightSettings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--question", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/online"))
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    if args.runs < 1:
        raise ValueError("--runs must be positive")
    settings = BizInsightSettings()
    settings.require_online_model()
    print(f"About to perform {args.runs} explicitly enabled online run(s).")
    summaries = []
    for index in range(1, args.runs + 1):
        result = await run_analysis(
            args.question,
            project_root=Path.cwd(),
            output_dir=args.output_dir / f"run-{index}",
            session_id=f"online-{index}",
            settings=settings,
            mode="online",
        )
        summaries.append(result.telemetry.model_dump(mode="json"))
    print(json.dumps(summaries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
