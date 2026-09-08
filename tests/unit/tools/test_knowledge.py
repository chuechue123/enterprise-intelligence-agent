"""Unit tests for the deterministic local knowledge index."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bizinsight.schemas import EvidenceType
from bizinsight.tools.knowledge import (
    KnowledgeRetriever,
    build_knowledge_index,
    load_knowledge_document,
)


def _write_document(path: Path, *, document_id: str, body: str) -> None:
    path.write_text(
        "\n".join(
            [
                "---",
                f"document_id: {document_id}",
                "title: 测试服务制度",
                "date: 2026-01-15",
                "department: 客户成功部",
                "---",
                "",
                "# 测试服务制度",
                "",
                body,
                "",
            ],
        ),
        encoding="utf-8",
    )


def test_load_document_requires_stable_metadata(tmp_path: Path) -> None:
    document_path = tmp_path / "sla.md"
    _write_document(
        document_path,
        document_id="DOC-TEST-SLA-001",
        body="P1 严重故障需要在 30 分钟内首次响应。",
    )

    document = load_knowledge_document(document_path, root=tmp_path)

    assert document.document_id == "DOC-TEST-SLA-001"
    assert document.title == "测试服务制度"
    assert document.department == "客户成功部"
    assert document.relative_path == "sla.md"


def test_build_index_is_deterministic_and_has_line_locations(
    tmp_path: Path,
) -> None:
    _write_document(
        tmp_path / "release.md",
        document_id="DOC-TEST-RELEASE-001",
        body="CloudFlow v3.2 发布了新的流程编排能力。",
    )
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"

    first = build_knowledge_index(tmp_path, first_path)
    second = build_knowledge_index(tmp_path, second_path)

    assert first == second
    assert json.loads(first_path.read_text(encoding="utf-8")) == first
    assert first["chunks"][0]["line_start"] <= first["chunks"][0]["line_end"]


def test_retrieval_returns_document_evidence_with_source_location(
    tmp_path: Path,
) -> None:
    _write_document(
        tmp_path / "sla.md",
        document_id="DOC-TEST-SLA-001",
        body="P1 严重故障需要在 30 分钟内首次响应。",
    )
    index_path = tmp_path / "index.json"
    build_knowledge_index(tmp_path, index_path)
    retriever = KnowledgeRetriever.from_index(index_path)

    result = retriever.search("P1 严重故障首次响应时间", top_k=3)

    assert result.reason is None
    assert len(result.evidence) == 1
    evidence = result.evidence[0]
    assert evidence.evidence_type is EvidenceType.DOCUMENT
    assert evidence.evidence_id.startswith("DOC-TEST-SLA-001-")
    assert evidence.source == "DOC-TEST-SLA-001｜测试服务制度"
    assert evidence.locator.startswith("sla.md:L")
    assert "30 分钟" in evidence.summary


def test_no_match_returns_empty_result_with_reason(tmp_path: Path) -> None:
    _write_document(
        tmp_path / "sla.md",
        document_id="DOC-TEST-SLA-001",
        body="P1 严重故障需要在 30 分钟内首次响应。",
    )
    index_path = tmp_path / "index.json"
    build_knowledge_index(tmp_path, index_path)
    retriever = KnowledgeRetriever.from_index(index_path)

    result = retriever.search("量子农业火星基地", top_k=3)

    assert result.evidence == []
    assert result.reason == "未找到与查询相关的内部文档"


def test_invalid_document_id_is_rejected(tmp_path: Path) -> None:
    document_path = tmp_path / "invalid.md"
    _write_document(
        document_path,
        document_id="INVALID-001",
        body="无效文档。",
    )

    with pytest.raises(ValueError, match="document_id"):
        load_knowledge_document(document_path, root=tmp_path)
