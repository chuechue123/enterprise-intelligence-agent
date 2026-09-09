"""Tests for online external search and local fallback behavior."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bizinsight.schemas import EvidenceType
from bizinsight.tools.external_search import ExternalSearchService, SearchMode

FALLBACK_DIR = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "knowledge"
    / "external_fallback"
)


class _MockTavilyClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def search(self, **kwargs: Any) -> dict[str, Any]:
        if self.fail:
            raise TimeoutError("mock timeout")
        assert kwargs["query"]
        return {
            "results": [
                {
                    "title": "Enterprise software buyers prioritize value",
                    "url": "https://example.com/enterprise-software-value",
                    "content": "Buyers compare price, reliability and service.",
                },
            ],
        }

    def extract(self, urls: list[str]) -> dict[str, Any]:
        return {
            "results": [
                {
                    "url": urls[0],
                    "raw_content": "Extracted market context.",
                },
            ],
        }


def test_mock_online_search_produces_valid_web_evidence() -> None:
    service = ExternalSearchService(
        fallback_dir=FALLBACK_DIR,
        api_key="mock-key",
        client=_MockTavilyClient(),
    )

    result = service.search("enterprise software pricing", max_results=3)

    assert result.mode is SearchMode.ONLINE
    assert result.degradation_reason is None
    assert result.evidence[0].evidence_type is EvidenceType.WEB
    assert str(result.evidence[0].url).startswith("https://example.com/")
    assert result.evidence[0].accessed_at is not None


def test_extract_returns_web_evidence() -> None:
    service = ExternalSearchService(
        fallback_dir=FALLBACK_DIR,
        api_key="mock-key",
        client=_MockTavilyClient(),
    )

    result = service.extract(["https://example.com/source"])

    assert result.mode is SearchMode.ONLINE
    assert "Extracted market context" in result.evidence[0].summary


def test_missing_key_uses_local_fallback_with_explicit_notice() -> None:
    service = ExternalSearchService(fallback_dir=FALLBACK_DIR, api_key=None)

    result = service.search("企业软件价格竞争与续费", max_results=3)

    assert result.mode is SearchMode.OFFLINE
    assert result.evidence
    assert all(
        item.evidence_type is EvidenceType.DOCUMENT for item in result.evidence
    )
    assert "未完成实时搜索" in result.degradation_reason


def test_online_failure_falls_back_instead_of_blocking_analysis() -> None:
    service = ExternalSearchService(
        fallback_dir=FALLBACK_DIR,
        api_key="mock-key",
        client=_MockTavilyClient(fail=True),
    )

    result = service.search("企业软件稳定性与客户留存")

    assert result.mode is SearchMode.OFFLINE
    assert result.evidence
    assert "mock timeout" in result.degradation_reason


def test_health_check_never_contains_api_key() -> None:
    service = ExternalSearchService(
        fallback_dir=FALLBACK_DIR,
        api_key="super-secret",
        client=_MockTavilyClient(),
    )

    status = service.health_check()

    assert status["mode"] == "online"
    assert "super-secret" not in str(status)
