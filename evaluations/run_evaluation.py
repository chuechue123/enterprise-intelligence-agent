"""Run the reproducible BizInsight benchmark and write JSON/Markdown results."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import yaml

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bizinsight.app import run_analysis
from evaluations.scorers import (
    score_anomaly_coverage,
    score_evidence_completeness,
    score_metric_accuracy,
    score_report_quality,
    score_robustness,
)

WEIGHTS = {
    "metric_accuracy": 0.35,
    "anomaly_coverage": 0.25,
    "evidence_completeness": 0.20,
    "robustness": 0.10,
    "report_quality": 0.10,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("offline", "online"), default="offline")
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/evaluation"))
    return parser.parse_args()


def load_cases(case_dir: Path) -> list[dict]:
    cases = []
    for path in sorted(case_dir.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError(f"evaluation file must contain a list: {path}")
        cases.extend(payload)
    return cases


async def evaluate(args: argparse.Namespace) -> dict:
    root = args.project_root.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for case in load_cases(root / "evaluations/cases"):
        started = time.perf_counter()
        case_dir = output_dir / case["id"]
        errors = []
        try:
            result = await run_analysis(
                case["question"],
                project_root=root,
                output_dir=case_dir,
                session_id=case["id"],
                mode=args.mode,
            )
            accepted = [
                item
                for item in result.findings
                if item.finding_id in set(result.review.accepted_finding_ids)
            ]
            scores = {
                "metric_accuracy": score_metric_accuracy(
                    accepted, case["expected_metrics"]
                ),
                "anomaly_coverage": score_anomaly_coverage(
                    accepted, case["expected_anomalies"]
                ),
                "evidence_completeness": score_evidence_completeness(accepted),
                "robustness": score_robustness(
                    result.errors, report_exists=result.report.html_path.is_file()
                ),
                "report_quality": score_report_quality(result.report.markdown_path),
            }
            errors.extend(result.errors)
            tool_calls = sum(len(item.evidence) for item in result.findings)
        except Exception as exc:
            scores = {name: 0.0 for name in WEIGHTS}
            errors.append(str(exc))
            tool_calls = 0
        weighted = round(
            sum(scores[name] * weight for name, weight in WEIGHTS.items()), 2
        )
        records.append(
            {
                "id": case["id"],
                "question": case["question"],
                "scores": scores,
                "weighted_score": weighted,
                "runtime": {
                    "mode": args.mode,
                    "model": "deterministic-offline"
                    if args.mode == "offline"
                    else "configured-online-model",
                    "token_usage": 0 if args.mode == "offline" else None,
                    "tool_calls": tool_calls,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "errors": errors,
                },
            }
        )
    summary = {
        "mode": args.mode,
        "case_count": len(records),
        "average_score": round(
            sum(item["weighted_score"] for item in records) / len(records), 2
        ),
        "passed": all(item["weighted_score"] >= 80 for item in records),
        "cases": records,
    }
    (output_dir / "evaluation.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# BizInsight 自动评测",
        "",
        f"- 模式：{args.mode}",
        f"- 用例数：{len(records)}",
        f"- 平均分：{summary['average_score']}/100",
        f"- 阈值结果：{'通过' if summary['passed'] else '未通过'}",
        "",
        "| 用例 | 得分 | 耗时(ms) | 错误 |",
        "|---|---:|---:|---|",
    ]
    for item in records:
        error_text = "；".join(item["runtime"]["errors"]) or "-"
        lines.append(
            f"| {item['id']} | {item['weighted_score']} | "
            f"{item['runtime']['duration_ms']} | {error_text} |",
        )
    (output_dir / "evaluation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    args = parse_args()
    summary = asyncio.run(evaluate(args))
    print(
        json.dumps(
            {
                key: summary[key]
                for key in ("mode", "case_count", "average_score", "passed")
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
