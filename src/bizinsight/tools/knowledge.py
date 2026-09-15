"""Offline, deterministic retrieval over synthetic enterprise documents."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from bizinsight.rag.bm25 import BM25Index
from bizinsight.schemas import Evidence, EvidenceType

DOCUMENT_ID_PATTERN = re.compile(r"^DOC-[A-Z0-9]+(?:-[A-Z0-9]+)*$")
LATIN_TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:\.[a-z0-9]+)*")
CJK_SEQUENCE_PATTERN = re.compile(r"[\u3400-\u9fff]+")
NO_MATCH_REASON = "未找到与查询相关的内部文档"


@dataclass(frozen=True)
class KnowledgeDocument:
    """One validated Markdown source document."""

    document_id: str
    title: str
    date: str
    department: str
    relative_path: str
    body: str
    body_start_line: int


@dataclass(frozen=True)
class KnowledgeSearchResult:
    """Evidence matches plus an explicit explanation when none are found."""

    query: str
    evidence: list[Evidence]
    reason: str | None = None


def _normalise_metadata_date(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    text = str(value).strip()
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("document date must use YYYY-MM-DD") from exc
    return text


def load_knowledge_document(path: Path, *, root: Path) -> KnowledgeDocument:
    """Load a Markdown document with required YAML front matter."""

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if len(lines) < 4 or lines[0].strip() != "---":
        raise ValueError(f"{path.name} must start with YAML front matter")

    try:
        closing_index = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        )
    except StopIteration as exc:
        raise ValueError(f"{path.name} has unclosed YAML front matter") from exc

    metadata = yaml.safe_load("\n".join(lines[1:closing_index]))
    if not isinstance(metadata, dict):
        raise ValueError(f"{path.name} front matter must be a mapping")

    required = ("document_id", "title", "date", "department")
    missing = [field for field in required if not metadata.get(field)]
    if missing:
        raise ValueError(f"{path.name} missing metadata: {', '.join(missing)}")

    document_id = str(metadata["document_id"]).strip()
    if not DOCUMENT_ID_PATTERN.fullmatch(document_id):
        raise ValueError("document_id must start with DOC- and use uppercase segments")

    body_lines = lines[closing_index + 1 :]
    body = "\n".join(body_lines).strip()
    if not body:
        raise ValueError(f"{path.name} must contain a document body")

    return KnowledgeDocument(
        document_id=document_id,
        title=str(metadata["title"]).strip(),
        date=_normalise_metadata_date(metadata["date"]),
        department=str(metadata["department"]).strip(),
        relative_path=path.relative_to(root).as_posix(),
        body=body,
        body_start_line=closing_index + 2,
    )


def _tokenize(text: str) -> list[str]:
    lowered = text.lower()
    tokens = LATIN_TOKEN_PATTERN.findall(lowered)
    for sequence in CJK_SEQUENCE_PATTERN.findall(lowered):
        if len(sequence) == 1:
            tokens.append(sequence)
            continue
        for width in (2, 3):
            tokens.extend(
                sequence[index : index + width]
                for index in range(len(sequence) - width + 1)
            )
    return tokens


def _chunk_document(document: KnowledgeDocument) -> list[dict[str, Any]]:
    lines = document.body.splitlines()
    chunks: list[dict[str, Any]] = []
    current_heading = document.title
    paragraph: list[tuple[int, str]] = []

    def flush() -> None:
        if not paragraph:
            return
        content = " ".join(line.strip() for _, line in paragraph).strip()
        if content:
            chunk_number = len(chunks) + 1
            chunks.append(
                {
                    "chunk_id": f"{document.document_id}-C{chunk_number:03d}",
                    "document_id": document.document_id,
                    "title": document.title,
                    "department": document.department,
                    "date": document.date,
                    "relative_path": document.relative_path,
                    "heading": current_heading,
                    "line_start": paragraph[0][0],
                    "line_end": paragraph[-1][0],
                    "content": content,
                    "terms": sorted(
                        set(_tokenize(f"{document.title} {current_heading} {content}")),
                    ),
                    "title_terms": sorted(
                        set(_tokenize(f"{document.title} {current_heading}")),
                    ),
                },
            )
        paragraph.clear()

    for offset, line in enumerate(lines):
        line_number = document.body_start_line + offset
        stripped = line.strip()
        if stripped.startswith("#"):
            flush()
            current_heading = stripped.lstrip("#").strip() or document.title
        elif not stripped:
            flush()
        else:
            paragraph.append((line_number, line))
    flush()
    return chunks


def build_knowledge_index(knowledge_dir: Path, output_path: Path) -> dict[str, Any]:
    """Validate Markdown sources and write a deterministic JSON index.

    Tolerant of individual file errors: files that fail to parse are skipped
    with a warning; duplicate document_ids are auto-suffixed so the build
    never fails from stale data left behind by earlier experiments.
    """

    knowledge_dir = knowledge_dir.resolve()
    source_paths = sorted(
        path
        for path in knowledge_dir.rglob("*.md")
        if knowledge_dir.name == "external_fallback"
        or "external_fallback" not in path.parts
    )
    if not source_paths:
        raise ValueError(f"no Markdown knowledge documents found in {knowledge_dir}")

    documents: list[KnowledgeDocument] = []
    seen_ids: dict[str, int] = {}
    for path in source_paths:
        try:
            doc = load_knowledge_document(path, root=knowledge_dir)
        except Exception as exc:
            import warnings

            warnings.warn(f"skipping {path.name}: {exc}")
            continue
        # Auto-resolve duplicate document_ids with a numbered suffix
        base_id = doc.document_id
        if base_id in seen_ids:
            seen_ids[base_id] += 1
            new_id = f"{base_id}-DUP{seen_ids[base_id]}"
            # Rewrite the front-matter on disk so future loads stay consistent
            try:
                text = path.read_text(encoding="utf-8")
                lines = text.splitlines()
                closing = next(
                    i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"
                )
                meta = yaml.safe_load("\n".join(lines[1:closing])) or {}
                meta["document_id"] = new_id
                new_text = (
                    "---\n"
                    + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
                    + "---\n"
                    + "\n".join(lines[closing + 1 :])
                )
                path.write_text(new_text, encoding="utf-8")
                doc = KnowledgeDocument(
                    document_id=new_id,
                    title=doc.title,
                    date=doc.date,
                    department=doc.department,
                    relative_path=doc.relative_path,
                    body=doc.body,
                    body_start_line=doc.body_start_line,
                )
            except Exception:
                pass  # if we can't rewrite, just use the suffixed id in the index
        else:
            seen_ids[base_id] = 0
        documents.append(doc)

    if not documents:
        raise ValueError("no valid knowledge documents after tolerance filter")

    chunks = [chunk for document in documents for chunk in _chunk_document(document)]
    source_hash = hashlib.sha256(
        "".join(
            f"{document.relative_path}\0{document.body}\0" for document in documents
        ).encode("utf-8"),
    ).hexdigest()
    index: dict[str, Any] = {
        "schema_version": 1,
        "document_count": len(documents),
        "chunk_count": len(chunks),
        "source_hash": source_hash,
        "documents": [
            {
                "document_id": document.document_id,
                "title": document.title,
                "date": document.date,
                "department": document.department,
                "relative_path": document.relative_path,
            }
            for document in documents
        ],
        "chunks": chunks,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return index


class KnowledgeRetriever:
    """Rank indexed chunks without a network service or embedding model."""

    def __init__(self, index: dict[str, Any]) -> None:
        self._chunks = list(index.get("chunks", []))
        if not self._chunks:
            raise ValueError("knowledge index contains no chunks")
        self._bm25 = BM25Index(self._chunks, tokenizer=_tokenize)

    @classmethod
    def from_index(cls, index_path: Path) -> KnowledgeRetriever:
        return cls(json.loads(index_path.read_text(encoding="utf-8")))

    def search(self, query: str, *, top_k: int = 5) -> KnowledgeSearchResult:
        """Return ranked document evidence, or an explicit empty result."""

        query = query.strip()
        if not query:
            raise ValueError("query must not be empty")
        if not 1 <= top_k <= 20:
            raise ValueError("top_k must be between 1 and 20")

        query_terms = set(_tokenize(query))
        candidates = self._bm25.search(query, top_k=min(len(self._chunks), top_k * 5))
        selected = sorted(
            candidates,
            key=lambda item: (
                -(
                    item[0]
                    + len(query_terms & set(item[1]["terms"]))
                    + 4 * len(query_terms & set(item[1]["title_terms"]))
                ),
                item[1]["document_id"],
                item[1]["chunk_id"],
            ),
        )[:top_k]
        if not selected:
            return KnowledgeSearchResult(
                query=query,
                evidence=[],
                reason=NO_MATCH_REASON,
            )

        generated_at = datetime.now(UTC)
        evidence = [
            Evidence(
                evidence_id=chunk["chunk_id"],
                evidence_type=EvidenceType.DOCUMENT,
                source=f"{chunk['document_id']}｜{chunk['title']}",
                locator=(
                    f"{chunk['relative_path']}:L{chunk['line_start']}"
                    f"-L{chunk['line_end']}"
                ),
                summary=chunk["content"],
                generated_at=generated_at,
            )
            for _, chunk in selected
        ]
        return KnowledgeSearchResult(query=query, evidence=evidence)
