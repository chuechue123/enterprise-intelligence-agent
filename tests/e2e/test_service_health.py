"""Service health does not expose environment secrets."""

from pathlib import Path

from bizinsight.app import health_status
from bizinsight.config import BizInsightSettings


def test_health_reports_components_without_secret_values(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("DASHSCOPE_API_KEY", "super-secret-model-key")
    monkeypatch.setenv("BIZINSIGHT_MODEL_NAME", "qwen-test")
    monkeypatch.setenv("TAVILY_API_KEY", "super-secret-search-key")
    status = health_status(root, BizInsightSettings())
    text = str(status)
    assert "configured" in text
    assert "super-secret" not in text
    assert status["service_storage"] == "sqlite"
    assert status["redis"] == "not_required"
