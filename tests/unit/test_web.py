"""Tests for the self-contained browser workbench adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bizinsight.web import attach_web_workbench


class _FakeMessage:
    def __init__(self, text: str, metadata: dict[str, Any] | None = None) -> None:
        self._text = text
        self.metadata = metadata or {}

    def get_text_content(self) -> str:
        return self._text


class _FakeAgent:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.last_route = "general"
        self.questions: list[str] = []

    async def reply(self, inputs: Any = None, structured_schema: Any = None) -> Any:
        del structured_schema
        text = inputs.get_text_content()
        self.questions.append(text)
        if "报告" in text:
            self.last_route = "business_analysis"
            return _FakeMessage(
                "经营分析已经完成。",
                {
                    "bizinsight_report": "/bizinsight/reports/web/report.html",
                    "run_id": "RUN-001",
                    "review_status": "approved",
                },
            )
        self.last_route = "general"
        return _FakeMessage(f"第{len(self.questions)}轮回答：{text}")


def _client() -> tuple[TestClient, dict[str, _FakeAgent]]:
    agents: dict[str, _FakeAgent] = {}

    def factory(session_id: str) -> _FakeAgent:
        agent = _FakeAgent(session_id)
        agents[session_id] = agent
        return agent

    app = FastAPI()
    attach_web_workbench(
        app,
        project_root=Path(__file__).resolve().parents[2],
        agent_factory=factory,
    )
    return TestClient(app), agents


def _write_knowledge_index(root: Path) -> None:
    knowledge = root / "data" / "knowledge"
    knowledge.mkdir(parents=True)
    (knowledge / "index.json").write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "document_id": "DOC-PRODUCT-RELEASE-202603",
                        "title": "CloudFlow v3.2 发布说明",
                        "date": "2026-03-28",
                        "department": "产品研发部",
                        "relative_path": "cloudflow_v32_release.md",
                    },
                    {
                        "document_id": "DOC-SERVICE-SLA-001",
                        "title": "客户支持服务等级协议（SLA）",
                        "date": "2026-01-20",
                        "department": "客户成功部",
                        "relative_path": "service_sla.md",
                    },
                    {
                        "document_id": "DOC-PRODUCT-RELEASE-202603",
                        "title": "重复数据不会生成第二行",
                        "date": "2025-01-01",
                        "department": "产品研发部",
                        "relative_path": "duplicate.md",
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _knowledge_client(root: Path) -> TestClient:
    app = FastAPI()
    attach_web_workbench(app, project_root=root, agent_factory=_FakeAgent)
    return TestClient(app, raise_server_exceptions=False)


def test_workbench_and_assets_are_served() -> None:
    client, _ = _client()

    page = client.get("/")
    styles = client.get("/bizinsight/assets/styles.css")
    script = client.get("/bizinsight/assets/app.js")

    assert page.status_code == 200
    assert "BizInsight Agent" in page.text
    assert "尚未生成报告" in page.text
    assert page.text.index('id="conversation"') < page.text.index('id="chatForm"')
    assert '<input id="question" type="text"' in page.text
    assert "Ctrl + Enter 快速发送" in page.text
    assert "paperclip" in page.text
    assert "service-pills" not in page.text
    assert "data-question" not in page.text
    assert "<textarea" not in page.text
    assert "agent-node done" not in page.text
    assert page.text.count("本次未调用") == 6
    assert styles.status_code == 200
    assert "--blue: #1268f3" in styles.text
    assert ".message.user" in styles.text
    assert "flex-direction: row-reverse" in styles.text
    assert script.status_code == 200
    assert 'fetch("/bizinsight/chat"' in script.text
    assert "data.execution_flow" in script.text
    assert "已调用 SQL/MCP" not in script.text
    assert 'id="conversationHistoryList"' in page.text
    assert 'id="newConversation"' in page.text
    assert "bizinsight.web.conversations.v1" in script.text
    assert "function switchConversation" in script.text
    assert "localStorage.setItem(CONVERSATIONS_KEY" in script.text
    assert "execution: null" in script.text
    assert "item.execution = currentExecution" in script.text
    assert "function restoreExecution(execution)" in script.text
    assert "restoreExecution(item.execution)" in script.text
    assert "flow: data.execution_flow || null" in script.text


def test_knowledge_page_and_assets_are_served() -> None:
    client, _ = _client()

    page = client.get("/knowledge")
    script = client.get("/bizinsight/assets/knowledge.js")

    assert page.status_code == 200
    assert "知识库 / RAG" in page.text
    assert 'id="knowledgeSearch"' in page.text
    assert 'id="knowledgeRows"' in page.text
    assert 'href="/knowledge"' in page.text
    assert script.status_code == 200
    assert 'fetch(`/bizinsight/knowledge/documents?' in script.text
    assert "setTimeout" in script.text


def test_knowledge_documents_are_deduplicated_sorted_and_typed(
    tmp_path: Path,
) -> None:
    _write_knowledge_index(tmp_path)
    response = _knowledge_client(tmp_path).get(
        "/bizinsight/knowledge/documents?page=1&page_size=10"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["pages"] == 1
    assert [item["document_id"] for item in payload["items"]] == [
        "DOC-PRODUCT-RELEASE-202603",
        "DOC-SERVICE-SLA-001",
    ]
    assert payload["items"][0] == {
        "document_id": "DOC-PRODUCT-RELEASE-202603",
        "title": "CloudFlow v3.2 发布说明",
        "document_type": "产品文档",
        "status": "ready",
        "updated_at": "2026-03-28",
        "source_path": "cloudflow_v32_release.md",
    }
    assert payload["items"][1]["document_type"] == "制度文档"


def test_knowledge_documents_support_search_and_pagination(tmp_path: Path) -> None:
    _write_knowledge_index(tmp_path)
    client = _knowledge_client(tmp_path)

    searched = client.get(
        "/bizinsight/knowledge/documents",
        params={"query": "产品文档", "page": 1, "page_size": 10},
    )
    paged = client.get(
        "/bizinsight/knowledge/documents",
        params={"page": 2, "page_size": 1},
    )

    assert searched.status_code == 200
    assert searched.json()["total"] == 1
    assert searched.json()["items"][0]["title"] == "CloudFlow v3.2 发布说明"
    assert paged.status_code == 200
    assert paged.json()["page"] == 2
    assert paged.json()["pages"] == 2
    assert paged.json()["items"][0]["document_id"] == "DOC-SERVICE-SLA-001"


def test_knowledge_documents_validate_pagination(tmp_path: Path) -> None:
    _write_knowledge_index(tmp_path)
    client = _knowledge_client(tmp_path)

    assert client.get(
        "/bizinsight/knowledge/documents?page=0&page_size=10"
    ).status_code == 422
    assert client.get(
        "/bizinsight/knowledge/documents?page=1&page_size=51"
    ).status_code == 422


def test_knowledge_documents_fail_safely_for_missing_or_invalid_index(
    tmp_path: Path,
) -> None:
    client = _knowledge_client(tmp_path)
    missing = client.get("/bizinsight/knowledge/documents")

    knowledge = tmp_path / "data" / "knowledge"
    knowledge.mkdir(parents=True)
    (knowledge / "index.json").write_text("not-json", encoding="utf-8")
    invalid = client.get("/bizinsight/knowledge/documents")

    assert missing.status_code == 503
    assert invalid.status_code == 503
    assert missing.json()["detail"] == "知识库索引暂不可用"
    assert invalid.json()["detail"] == "知识库索引暂不可用"


def test_chat_reuses_agent_within_session_and_isolates_sessions() -> None:
    client, agents = _client()

    first = client.post(
        "/bizinsight/chat",
        json={"question": "你是谁？", "session_id": "web-one"},
    )
    second = client.post(
        "/bizinsight/chat",
        json={"question": "继续介绍", "session_id": "web-one"},
    )
    isolated = client.post(
        "/bizinsight/chat",
        json={"question": "你好", "session_id": "web-two"},
    )

    assert first.json()["answer"].startswith("第1轮回答")
    assert second.json()["answer"].startswith("第2轮回答")
    assert isolated.json()["answer"].startswith("第1轮回答")
    assert agents["web-one"].questions == ["你是谁？", "继续介绍"]
    assert agents["web-two"].questions == ["你好"]


def test_business_metadata_is_returned_without_changing_agent_result() -> None:
    client, _ = _client()

    response = client.post(
        "/bizinsight/chat",
        json={"question": "请生成经营分析报告", "session_id": "web-report"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == "web-report"
    assert payload["answer"] == "经营分析已经完成。"
    assert payload["route"] == "business_analysis"
    assert payload["report_url"] == "/bizinsight/reports/web/report.html"
    assert payload["run_id"] == "RUN-001"
    assert payload["review_status"] == "approved"
    assert payload["executed_agents"] == []
    assert all(
        node["status"] == "not_called"
        for node in payload["execution_flow"]["nodes"]
    )


def test_business_route_reports_only_agents_recorded_by_workflow_telemetry(
    tmp_path: Path,
) -> None:
    session_id = "web-measured"
    telemetry_dir = tmp_path / "outputs" / session_id
    telemetry_dir.mkdir(parents=True)
    (telemetry_dir / f"{session_id}.telemetry.json").write_text(
        json.dumps(
            {
                "run_id": "RUN-001",
                "duration_ms": 3210.0,
                "agents": [
                    {
                        "agent_name": "FinanceSalesAgent",
                        "duration_ms": 1200.0,
                        "tool_calls": [{"tool_name": "evidence:database"}],
                        "error": None,
                    },
                    {
                        "agent_name": "CustomerProductAgent",
                        "duration_ms": 900.0,
                        "tool_calls": [],
                        "error": "invalid finding",
                    },
                    {"agent_name": "BizInsightLeader", "error": None},
                    {"agent_name": "EvidenceReviewerAgent", "error": None},
                ],
            }
        ),
        encoding="utf-8",
    )
    app = FastAPI()
    attach_web_workbench(
        app,
        project_root=tmp_path,
        agent_factory=_FakeAgent,
    )

    response = TestClient(app).post(
        "/bizinsight/chat",
        json={"question": "请生成经营分析报告", "session_id": session_id},
    )

    payload = response.json()
    assert payload["executed_agents"] == [
        "BizInsightLeader",
        "FinanceSalesAgent",
        "CustomerProductAgent",
        "EvidenceReviewerAgent",
    ]
    nodes = {
        node["key"]: node for node in payload["execution_flow"]["nodes"]
    }
    assert nodes["supervisor"]["status"] == "success"
    assert nodes["supervisor"]["summary"] == "BizInsightLeader"
    assert nodes["finance"]["status"] == "success"
    assert nodes["finance"]["summary"] == "FinanceSalesAgent"
    assert nodes["finance"]["evidence_types"] == ["database"]
    assert nodes["customer"]["status"] == "failed"
    assert nodes["customer"]["summary"] == "CustomerProductAgent（调用失败）"
    assert nodes["delivery"]["status"] == "not_called"
    assert nodes["external"]["status"] == "not_called"
    assert nodes["reviewer"]["status"] == "success"
    assert nodes["reviewer"]["summary"] == "EvidenceReviewerAgent"
    assert payload["execution_flow"]["duration_ms"] == 3210.0
    assert payload["execution_flow"]["phases"] == {
        "planned": True,
        "workers": True,
        "reviewed": True,
        "report": True,
    }


def test_invalid_input_is_rejected_before_agent_creation() -> None:
    client, agents = _client()

    blank = client.post(
        "/bizinsight/chat",
        json={"question": "   ", "session_id": "web-valid"},
    )
    unsafe_session = client.post(
        "/bizinsight/chat",
        json={"question": "你好", "session_id": "../../unsafe"},
    )

    assert blank.status_code == 422
    assert unsafe_session.status_code == 422
    assert not agents


def test_internal_failure_returns_stable_error_without_exception_details() -> None:
    class _FailingAgent(_FakeAgent):
        async def reply(self, inputs: Any = None, structured_schema: Any = None) -> Any:
            del inputs, structured_schema
            raise RuntimeError("secret-key-value")

    app = FastAPI()
    attach_web_workbench(
        app,
        project_root=Path.cwd(),
        agent_factory=_FailingAgent,
    )
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/bizinsight/chat",
        json={"question": "你好", "session_id": "web-error"},
    )

    assert response.status_code == 503
    assert "请检查在线模型配置后重试" in response.text
    assert "secret-key-value" not in response.text
