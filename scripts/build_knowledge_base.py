"""Build the deterministic local enterprise knowledge index."""

from __future__ import annotations

import argparse
from pathlib import Path

from bizinsight.tools.knowledge import build_knowledge_index


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Project root containing data/knowledge (default: repository root)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    knowledge_dir = args.root / "data" / "knowledge"
    index_path = knowledge_dir / "index.json"
    index = build_knowledge_index(knowledge_dir, index_path)
    print(
        f"Built {index['document_count']} documents / "
        f"{index['chunk_count']} chunks at {index_path}",
    )


if __name__ == "__main__":
    main()
