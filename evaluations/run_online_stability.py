"""Explicit five-run stability harness for the real AgentScope pipeline."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from bizinsight.app import run_analysis
from bizinsight.config import BizInsightSettings


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument(
        "--question",
        default="综合分析公司2026年第二季度经营表现下降的主要原因",
    )
    args = parser.parse_args()
    settings = BizInsightSettings()
    settings.require_online_model()
    root = Path(__file__).resolve().parents[1]
    print(f"Explicit online stability run count: {args.runs}")
    records = []
    for index in range(1, args.runs + 1):
        try:
            result = await run_analysis(
                args.question,
                project_root=root,
                output_dir=root / f"outputs/online-stability/run-{index}",
                session_id=f"stability-{index}",
                settings=settings,
                mode="online",
            )
            records.append(
                {
                    "run": index,
                    "success": True,
                    "finding_count": len(result.findings),
                    "accepted_count": len(result.review.accepted_finding_ids),
                    "telemetry": result.telemetry.model_dump(mode="json"),
                }
            )
        except Exception as exc:
            records.append(
                {"run": index, "success": False, "error_type": type(exc).__name__}
            )
    success_rate = sum(item["success"] for item in records) / args.runs
    summary = {"runs": args.runs, "success_rate": success_rate, "records": records}
    output = root / "outputs/online-stability/summary.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"runs": args.runs, "success_rate": success_rate}, indent=2))
    if success_rate < 0.8:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
