"""AgentScope KnowledgeBase/Qdrant adapter for internal documents."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentscope.credential import DashScopeCredential
from agentscope.embedding import DashScopeEmbeddingModel
from agentscope.message import TextBlock
from agentscope.rag import Chunk, KnowledgeBase, QdrantStore

from bizinsight.config import BizInsightSettings


class AgentScopeVectorIndex:
    """Own the public AgentScope RAG lifecycle and persistent manifest."""

    def __init__(self, *, store: QdrantStore, knowledge_base: KnowledgeBase) -> None:
        self.store = store
        self.knowledge_base = knowledge_base

    @classmethod
    def from_settings(
        cls, *, settings: BizInsightSettings, index_dir: Path
    ) -> AgentScopeVectorIndex:
        settings.require_online_embedding()
        assert settings.dashscope_api_key is not None
        embedding = DashScopeEmbeddingModel(
            credential=DashScopeCredential(api_key=settings.dashscope_api_key),
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
        )
        store = QdrantStore(path=str((index_dir / "qdrant").resolve()))
        knowledge = KnowledgeBase(
            name="bizinsight-internal",
            description="Traceable internal business documents",
            embedding_model=embedding,
            vector_store=store,
            collection="bizinsight_internal_v1",
        )
        return cls(store=store, knowledge_base=knowledge)

    async def __aenter__(self) -> AgentScopeVectorIndex:
        await self.store.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.store.__aexit__(exc_type, exc, traceback)

    async def build_from_json(
        self,
        *,
        lexical_index_path: Path,
        manifest_path: Path,
        settings: BizInsightSettings,
    ) -> dict[str, Any]:
        index = json.loads(lexical_index_path.read_text(encoding="utf-8"))
        chunks = list(index["chunks"])
        for position, item in enumerate(chunks):
            metadata = {
                key: item[key]
                for key in (
                    "chunk_id",
                    "document_id",
                    "department",
                    "date",
                    "relative_path",
                    "line_start",
                    "line_end",
                    "title",
                )
            }
            await self.knowledge_base.insert_document(
                [
                    Chunk(
                        content=TextBlock(text=item["content"]),
                        source=item["relative_path"],
                        chunk_index=position,
                        total_chunks=len(chunks),
                        metadata=metadata,
                    )
                ],
                document_metadata={"document_id": item["document_id"]},
            )
        manifest = {
            "source_hash": index["source_hash"],
            "model": settings.embedding_model,
            "dimensions": settings.embedding_dimensions,
            "collection": "bizinsight_internal_v1",
            "built_at": datetime.now(UTC).isoformat(),
            "chunk_count": len(chunks),
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return manifest

    @staticmethod
    def fingerprint(index_path: Path) -> str:
        return hashlib.sha256(index_path.read_bytes()).hexdigest()
