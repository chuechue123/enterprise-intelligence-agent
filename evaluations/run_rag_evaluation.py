"""Evaluate lexical or AgentScope-vector hybrid internal retrieval."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import yaml

from bizinsight.config import BizInsightSettings
from bizinsight.tools.knowledge import KnowledgeRetriever, _tokenize


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("offline", "hybrid"), default="offline")
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    index_path = root / "data/knowledge/index.json"
    retriever = KnowledgeRetriever.from_index(index_path)
    vector = None
    if args.mode == "hybrid":
        from bizinsight.rag.hybrid import HybridKnowledgeRetriever
        from bizinsight.rag.vector_index import AgentScopeVectorIndex

        settings = BizInsightSettings()
        vector = AgentScopeVectorIndex.from_settings(
            settings=settings, index_dir=root / "data/knowledge/vector"
        )
        await vector.__aenter__()
        index = json.loads(index_path.read_text(encoding="utf-8"))
        retriever = HybridKnowledgeRetriever(
            chunks=index["chunks"],
            tokenizer=_tokenize,
            knowledge_base=vector.knowledge_base,
        )
    cases = yaml.safe_load(
        (root / "evaluations/rag/cases.yaml").read_text(encoding="utf-8")
    )
    reciprocal_ranks = []
    hits = 0
    records = []
    for case in cases:
        result = retriever.search(case["query"], top_k=3)
        if asyncio.iscoroutine(result):
            result = await result
        document_ids = [item.source.split("｜", 1)[0] for item in result.evidence]
        try:
            rank = document_ids.index(case["expected_document"]) + 1
        except ValueError:
            rank = 0
        hits += int(bool(rank))
        reciprocal_ranks.append(0 if not rank else 1 / rank)
        records.append({**case, "retrieved": document_ids, "rank": rank})
    if vector is not None:
        await vector.__aexit__(None, None, None)
    summary = {
        "mode": args.mode,
        "cases": len(cases),
        "hit_at_3": round(hits / len(cases), 4),
        "mrr": round(sum(reciprocal_ranks) / len(cases), 4),
        "records": records,
    }
    output = root / "outputs/evaluation/rag"
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{args.mode}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["hit_at_3"] < 0.9 or summary["mrr"] < 0.75:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
