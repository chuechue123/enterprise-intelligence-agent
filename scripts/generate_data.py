"""Generate the BizInsight synthetic business dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bizinsight.data.generator import DEFAULT_SEED, generate_dataset, write_dataset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset = generate_dataset(args.seed)
    paths = write_dataset(dataset, args.project_root)
    print(
        json.dumps(
            {
                "seed": dataset.seed,
                "record_counts": dataset.quality_summary["record_counts"],
                "core_metrics": dataset.quality_summary["core_metrics"],
                "database": str(paths.database_path),
            },
            ensure_ascii=False,
            indent=2,
        ),
    )


if __name__ == "__main__":
    main()
