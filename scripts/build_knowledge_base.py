"""Build the deterministic local enterprise knowledge index."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from bizinsight.config import BizInsightSettings
from bizinsight.rag.vector_index import AgentScopeVectorIndex
from bizinsight.tools.knowledge import build_knowledge_index


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Project root containing data/knowledge (default: repository root)",
    )
    parser.add_argument(
        "--online-embedding",
        action="store_true",
        help="Explicitly call Qwen embedding and build AgentScope/Qdrant index",
    )
    return parser.parse_args()


async def _main() -> None:
    args = parse_args()
    knowledge_dir = args.root / "data" / "knowledge"
    index_path = knowledge_dir / "index.json"
    index = build_knowledge_index(knowledge_dir, index_path)
    print(
        f"Built {index['document_count']} documents / "
        f"{index['chunk_count']} chunks at {index_path}",
    )
    if not args.online_embedding:
        print("BM25 index only; no embedding request was made.")
        return
    settings = BizInsightSettings()
    settings.require_online_embedding()
    vector = AgentScopeVectorIndex.from_settings(
        settings=settings,
        index_dir=knowledge_dir / "vector",
    )
    async with vector:
        manifest = await vector.build_from_json(
            lexical_index_path=index_path,
            manifest_path=knowledge_dir / "vector/manifest.json",
            settings=settings,
        )
    print(f"Built AgentScope vector index with {manifest['chunk_count']} chunks.")


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
