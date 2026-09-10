"""Rank fusion between lexical BM25 and AgentScope KnowledgeBase search."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from agentscope.message import TextBlock

from bizinsight.rag.bm25 import BM25Index
from bizinsight.schemas import Evidence, EvidenceType
from bizinsight.tools.knowledge import KnowledgeSearchResult


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]], *, k: int = 60
) -> list[str]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, identity in enumerate(ranking, start=1):
            scores[identity] = scores.get(identity, 0) + 1 / (k + rank)
    return sorted(scores, key=lambda identity: (-scores[identity], identity))


class HybridKnowledgeRetriever:
    def __init__(
        self, *, chunks: list[dict[str, Any]], tokenizer, knowledge_base
    ) -> None:
        self.chunks = {item["chunk_id"]: item for item in chunks}
        self.bm25 = BM25Index(chunks, tokenizer=tokenizer)
        self.knowledge_base = knowledge_base
        self.last_degradation: str | None = None

    async def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        metadata_filter: dict[str, str] | None = None,
        max_context_chars: int = 6000,
    ) -> KnowledgeSearchResult:
        lexical = self.bm25.search(query, top_k=max(top_k * 2, 10))
        lexical_ids = [item[1]["chunk_id"] for item in lexical]
        vector_ids: list[str] = []
        vector_chunks: dict[str, dict[str, Any]] = {}
        try:
            for result in await self.knowledge_base.search(
                queries=[query], top_k=max(top_k * 2, 10)
            ):
                metadata = dict(result.chunk.metadata)
                identity = str(metadata["chunk_id"])
                vector_ids.append(identity)
                vector_chunks[identity] = {
                    **metadata,
                    "content": result.chunk.content.text
                    if isinstance(result.chunk.content, TextBlock)
                    else "",
                }
        except Exception as exc:
            self.last_degradation = f"rag_vector_degraded: {type(exc).__name__}"
        fused = reciprocal_rank_fusion([lexical_ids, vector_ids])
        generated_at = datetime.now(UTC)
        evidence = []
        used_chars = 0
        for identity in fused:
            chunk = self.chunks.get(identity) or vector_chunks[identity]
            if metadata_filter and any(
                str(chunk.get(key)) != value for key, value in metadata_filter.items()
            ):
                continue
            content = str(chunk["content"])
            if evidence and used_chars + len(content) > max_context_chars:
                continue
            evidence.append(
                Evidence(
                    evidence_id=identity,
                    evidence_type=EvidenceType.DOCUMENT,
                    source=f"{chunk['document_id']}｜{chunk['title']}",
                    locator=(
                        f"{chunk['relative_path']}:L{chunk['line_start']}"
                        f"-L{chunk['line_end']}"
                    ),
                    summary=content,
                    generated_at=generated_at,
                )
            )
            used_chars += len(content)
            if len(evidence) >= top_k:
                break
        return KnowledgeSearchResult(
            query=query,
            evidence=evidence,
            reason=None if evidence else "未找到与查询相关的内部文档",
        )
