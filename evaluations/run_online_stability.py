"""Explicit five-run stability harness for the real AgentScope pipeline.

Each round runs in its own process through the CLI, mirroring real usage
and isolating anyio/MCP cleanup side effects between rounds.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def _load_dotenv_values(root: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    dotenv_path = root / ".env"
    if not dotenv_path.exists():
        return values
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument(
        "--question",
        default="综合分析公司2026年第二季度经营表现下降的主要原因",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    print(f"Explicit online stability run count: {args.runs}")
    env = os.environ.copy()
    env.update(_load_dotenv_values(root))
    records = []
    for index in range(1, args.runs + 1):
        output_dir = root / f"outputs/online-stability/run-{index}"
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "bizinsight.cli",
                "--question",
                args.question,
                "--mode",
                "online",
                "--output-dir",
                str(output_dir),
                "--session-id",
                f"stability-{index}",
                "--project-root",
                str(root),
            ],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
        )
        record: dict = {
            "run": index,
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
        }
        telemetry_files = sorted(output_dir.glob("*.telemetry.json"))
        if telemetry_files:
            record["telemetry"] = json.loads(
                telemetry_files[-1].read_text(encoding="utf-8")
            )
        if proc.returncode != 0:
            record["stderr_tail"] = proc.stderr[-2000:]
        records.append(record)
        print(
            json.dumps(
                {"run": index, "success": proc.returncode == 0},
                ensure_ascii=False,
            )
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
    main()
