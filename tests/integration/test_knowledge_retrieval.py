"""Integration tests against the synthetic enterprise knowledge corpus."""

from __future__ import annotations

from pathlib import Path

import pytest

from bizinsight.tools.knowledge import (
    KnowledgeRetriever,
    build_knowledge_index,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = PROJECT_ROOT / "data" / "knowledge"


@pytest.fixture(scope="module")
def retriever(tmp_path_factory: pytest.TempPathFactory) -> KnowledgeRetriever:
    index_path = tmp_path_factory.mktemp("knowledge") / "index.json"
    index = build_knowledge_index(KNOWLEDGE_DIR, index_path)
    assert 10 <= index["document_count"] <= 15
    return KnowledgeRetriever.from_index(index_path)


@pytest.mark.parametrize(
    ("query", "expected_document_id", "expected_excerpt"),
    [
        (
            "CloudFlow v3.2 发布说明和灰度策略",
            "DOC-PRODUCT-RELEASE-202603",
            "10%",
        ),
        (
            "CloudFlow v3.2 稳定性故障复盘连接池根因",
            "DOC-INCIDENT-202604",
            "连接池",
        ),
        (
            "P1 客服工单首次响应 SLA",
            "DOC-SERVICE-SLA-001",
            "30 分钟",
        ),
        (
            "项目验收与收入确认规则",
            "DOC-FINANCE-REVREC-001",
            "验收",
        ),
        (
            "华东中小客户输单和竞品低价套餐",
            "DOC-SALES-WINLOSS-2026Q2",
            "低价",
        ),
    ],
)
def test_required_business_topics_are_retrievable(
    retriever: KnowledgeRetriever,
    query: str,
    expected_document_id: str,
    expected_excerpt: str,
) -> None:
    result = retriever.search(query, top_k=3)

    assert result.reason is None
    assert result.evidence
    top_evidence = result.evidence[0]
    assert top_evidence.evidence_id.startswith(f"{expected_document_id}-")
    assert expected_excerpt in top_evidence.summary
    assert ":L" in top_evidence.locator
