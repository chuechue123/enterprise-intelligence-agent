from typing import Any

import pytest
from agentscope.credential import CredentialBase
from agentscope.embedding import EmbeddingModelBase, EmbeddingResponse, EmbeddingUsage
from agentscope.message import TextBlock
from agentscope.rag import Chunk, KnowledgeBase, QdrantStore


class _Credential(CredentialBase):
    pass


class _Embedding(EmbeddingModelBase[str]):
    def __init__(self) -> None:
        super().__init__(
            credential=_Credential(),
            model="deterministic-test-embedding",
            dimensions=3,
            parameters=self.Parameters(),
            context_size=4096,
            batch_size=10,
            max_retries=0,
            retry_delay=0,
        )

    async def _call_api(self, inputs: list[Any], **kwargs: Any) -> EmbeddingResponse:
        del kwargs
        embeddings = [
            [float("验收" in text), float("故障" in text), 1.0] for text in inputs
        ]
        return EmbeddingResponse(
            embeddings=embeddings,
            usage=EmbeddingUsage(tokens=len(inputs), time=0),
        )


@pytest.mark.asyncio
async def test_real_agentscope_knowledge_base_flow_preserves_metadata() -> None:
    store = QdrantStore(location=":memory:")
    async with store:
        knowledge = KnowledgeBase(
            name="test",
            description="test",
            embedding_model=_Embedding(),
            vector_store=store,
            collection="test_collection",
        )
        await knowledge.insert_document(
            [
                Chunk(
                    content=TextBlock(text="验收完成后确认收入"),
                    source="policy.md",
                    chunk_index=0,
                    total_chunks=1,
                    metadata={
                        "chunk_id": "DOC-POLICY-C001",
                        "document_id": "DOC-POLICY",
                        "department": "财务部",
                        "date": "2026-01-01",
                        "relative_path": "policy.md",
                        "line_start": 10,
                        "line_end": 10,
                        "title": "收入确认",
                    },
                )
            ]
        )
        results = await knowledge.search(queries=["验收规则"], top_k=1)
        assert results[0].chunk.metadata["chunk_id"] == "DOC-POLICY-C001"
