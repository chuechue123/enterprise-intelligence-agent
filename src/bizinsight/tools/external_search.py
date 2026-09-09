"""Tavily search adapter with deterministic local-industry fallback."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from pydantic import SecretStr

from bizinsight.schemas import Evidence, EvidenceType
from bizinsight.tools.knowledge import KnowledgeRetriever


class SearchMode(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"


class TavilyClientProtocol(Protocol):
    def search(self, **kwargs: Any) -> dict[str, Any]: ...

    def extract(self, urls: list[str]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ExternalSearchResult:
    query: str
    mode: SearchMode
    evidence: list[Evidence]
    degradation_reason: str | None = None


class ExternalSearchService:
    """Search public sources when available and degrade to local material."""

    def __init__(
        self,
        *,
        fallback_dir: Path,
        api_key: SecretStr | str | None,
        client: TavilyClientProtocol | None = None,
    ) -> None:
        self.fallback_dir = fallback_dir.resolve()
        self._api_key_configured = api_key is not None and bool(
            api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key,
        )
        self._client_error: str | None = None
        self._client = client
        if self._client is None and self._api_key_configured:
            key = (
                api_key.get_secret_value()
                if isinstance(api_key, SecretStr)
                else str(api_key)
            )
            try:
                from tavily import TavilyClient

                self._client = TavilyClient(api_key=key)
            except (ImportError, RuntimeError, ValueError) as exc:
                self._client_error = f"Tavily 初始化失败：{exc}"

        index_path = self.fallback_dir / "index.json"
        if not index_path.is_file():
            raise FileNotFoundError(f"fallback index not found: {index_path}")
        self._fallback_retriever = KnowledgeRetriever.from_index(index_path)

    def health_check(self) -> dict[str, Any]:
        online = self._client is not None
        return {
            "status": "available" if online else "degraded",
            "mode": SearchMode.ONLINE.value if online else SearchMode.OFFLINE.value,
            "api_key_configured": self._api_key_configured,
            "fallback_available": True,
            "detail": self._client_error,
        }

    @staticmethod
    def _web_evidence(
        *,
        title: str,
        url: str,
        summary: str,
        accessed_at: datetime,
    ) -> Evidence:
        digest = hashlib.sha256(f"{url}\0{summary}".encode()).hexdigest()[:16]
        return Evidence(
            evidence_id=f"WEB-{digest}",
            evidence_type=EvidenceType.WEB,
            source=title or url,
            locator=url,
            summary=summary,
            generated_at=accessed_at,
            url=url,
            accessed_at=accessed_at,
        )

    def _fallback(
        self,
        query: str,
        reason: str,
        max_results: int,
    ) -> ExternalSearchResult:
        local = self._fallback_retriever.search(query, top_k=max_results)
        detail = f"未完成实时搜索；已使用本地行业资料。原因：{reason}"
        if local.reason:
            detail += f"；{local.reason}"
        return ExternalSearchResult(
            query=query,
            mode=SearchMode.OFFLINE,
            evidence=local.evidence,
            degradation_reason=detail,
        )

    def search(self, query: str, *, max_results: int = 5) -> ExternalSearchResult:
        query = query.strip()
        if not query:
            raise ValueError("query must not be empty")
        if not 1 <= max_results <= 10:
            raise ValueError("max_results must be between 1 and 10")
        if self._client is None:
            reason = self._client_error or "未配置 TAVILY_API_KEY"
            return self._fallback(query, reason, max_results)

        accessed_at = datetime.now(UTC)
        try:
            payload = self._client.search(
                query=query,
                search_depth="advanced",
                max_results=max_results,
                include_answer=False,
            )
            evidence = [
                self._web_evidence(
                    title=str(item.get("title") or item.get("url") or "网页资料"),
                    url=str(item["url"]),
                    summary=str(
                        item.get("content") or item.get("snippet") or "",
                    ).strip(),
                    accessed_at=accessed_at,
                )
                for item in payload.get("results", [])[:max_results]
                if item.get("url") and (item.get("content") or item.get("snippet"))
            ]
        except Exception as exc:  # external SDK/network boundary
            return self._fallback(query, str(exc), max_results)
        if not evidence:
            return self._fallback(query, "Tavily 未返回可引用结果", max_results)
        return ExternalSearchResult(query, SearchMode.ONLINE, evidence)

    def extract(self, urls: list[str]) -> ExternalSearchResult:
        if not urls:
            raise ValueError("urls must not be empty")
        query = " ".join(urls)
        if self._client is None:
            return self._fallback(query, "未配置或无法初始化 Tavily", 5)
        accessed_at = datetime.now(UTC)
        try:
            payload = self._client.extract(urls=urls)
            evidence = [
                self._web_evidence(
                    title=str(item.get("title") or item.get("url") or "网页资料"),
                    url=str(item["url"]),
                    summary=str(
                        item.get("raw_content") or item.get("content") or "",
                    ).strip(),
                    accessed_at=accessed_at,
                )
                for item in payload.get("results", [])
                if item.get("url") and (item.get("raw_content") or item.get("content"))
            ]
        except Exception as exc:  # external SDK/network boundary
            return self._fallback(query, str(exc), 5)
        if not evidence:
            return self._fallback(query, "Tavily 未返回可引用正文", 5)
        return ExternalSearchResult(query, SearchMode.ONLINE, evidence)
