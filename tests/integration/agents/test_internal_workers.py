"""Integration tests for scoped AgentScope internal-analysis workers."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest
from agentscope.credential import CredentialBase
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import ToolCallBlock
from agentscope.model import ChatModelBase, ChatResponse
from pydantic import BaseModel

from bizinsight.agents.customer_product import CustomerProductAgent
from bizinsight.agents.delivery import DeliveryAgent
from bizinsight.agents.finance_sales import FinanceSalesAgent
from bizinsight.agents.worker_base import (
    DatasetAccessError,
    WorkerOutputError,
)
from bizinsight.data.generator import generate_dataset, write_dataset
from bizinsight.data.provider import BusinessDataProvider
from bizinsight.schemas import AnalysisTask, Finding, WorkerName
from bizinsight.tools.knowledge import KnowledgeRetriever

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _finding_payload(finding_id: str = "FINDING-MOCK-001") -> dict[str, Any]:
    return {
        "finding_id": finding_id,
        "title": "经过工具验证的经营异常",
        "fact_statement": "确定性工具返回的指标较对比期下降。",
        "metrics": [],
        "evidence": [
            {
                "evidence_id": "DB-mock001",
                "evidence_type": "database",
                "source": "bizinsight.sqlite",
                "locator": "SQL: SELECT verified_metric FROM allowed_table",
                "summary": "只读查询返回已验证的经营指标。",
                "generated_at": "2026-09-09T09:00:00+08:00",
            },
        ],
        "business_interpretation": "该变化值得结合领域证据进一步解释。",
        "causal_assessment": "当前证据支持相关性，不足以单独证明因果关系。",
        "confidence": 0.8,
        "limitations": ["Mock 模型仅验证 AgentScope 结构化输出流程。"],
        "is_key": True,
    }


class _WorkerMockCredential(CredentialBase):
    @classmethod
    def get_chat_model_class(cls) -> type[ChatModelBase]:
        return _WorkerMockModel


class _WorkerMockModel(ChatModelBase):
    """Return scripted structured-output calls without network access."""

    class Parameters(BaseModel):
        pass

    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        super().__init__(
            credential=_WorkerMockCredential(),
            model="bizinsight-worker-mock",
            parameters=self.Parameters(),
            stream=False,
            context_size=8_192,
        )
        self.formatter = OpenAIChatFormatter()
        self.payloads = payloads
        self.call_count = 0

    async def _call_api(self, *args: Any, **kwargs: Any) -> ChatResponse:
        del args, kwargs
        index = min(self.call_count, len(self.payloads) - 1)
        payload = self.payloads[index]
        self.call_count += 1
        return ChatResponse(
            content=[
                ToolCallBlock(
                    id=f"worker-structured-{self.call_count}",
                    name="GenerateStructuredOutput",
                    input=json.dumps(payload, ensure_ascii=False),
                ),
            ],
            is_last=True,
        )


class _ToolThenFindingMockModel(_WorkerMockModel):
    """Call one real Worker tool, then provide the final Finding."""

    async def _call_api(self, *args: Any, **kwargs: Any) -> ChatResponse:
        if self.call_count == 0:
            self.call_count += 1
            return ChatResponse(
                content=[
                    ToolCallBlock(
                        id="worker-metric-call",
                        name="calculate_metric",
                        input=json.dumps(
                            {
                                "metric_name": "revenue",
                                "period": "2026-Q2",
                            },
                        ),
                    ),
                ],
                is_last=True,
            )
        return await super()._call_api(*args, **kwargs)


@pytest.fixture(scope="module")
def provider(tmp_path_factory: pytest.TempPathFactory) -> BusinessDataProvider:
    generated_root = tmp_path_factory.mktemp("worker-business-data")
    database_path = write_dataset(
        generate_dataset(),
        generated_root,
    ).database_path
    return BusinessDataProvider(
        database_path=database_path,
        table_dictionary_path=(
            PROJECT_ROOT / "data" / "data_dictionary" / "tables.yaml"
        ),
        metric_dictionary_path=(
            PROJECT_ROOT / "data" / "data_dictionary" / "metrics.yaml"
        ),
    )


@pytest.fixture(scope="module")
def retriever() -> KnowledgeRetriever:
    return KnowledgeRetriever.from_index(
        PROJECT_ROOT / "data" / "knowledge" / "index.json",
    )


def _task(target: WorkerName, datasets: list[str]) -> AnalysisTask:
    return AnalysisTask(
        task_id=f"TASK-{target.value}",
        target_agent=target,
        question="分析 2026 年第二季度相对第一季度的主要经营异常。",
        required_datasets=datasets,
        expected_outputs=["返回带证据的 Finding"],
    )


def test_finance_sales_agent_cannot_access_support_details(
    provider: BusinessDataProvider,
    retriever: KnowledgeRetriever,
) -> None:
    worker = FinanceSalesAgent(
        model=_WorkerMockModel([_finding_payload()]),
        provider=provider,
        knowledge_retriever=retriever,
    )

    with pytest.raises(DatasetAccessError, match="support_tickets"):
        worker.execute_sql("SELECT * FROM support_tickets LIMIT 1")


def test_customer_product_agent_can_join_subscription_usage_and_tickets(
    provider: BusinessDataProvider,
    retriever: KnowledgeRetriever,
) -> None:
    worker = CustomerProductAgent(
        model=_WorkerMockModel([_finding_payload()]),
        provider=provider,
        knowledge_retriever=retriever,
    )

    result = worker.execute_sql(
        """
        SELECT
            s.customer_id,
            MAX(s.renewal_status) AS renewal_status,
            SUM(u.workflow_runs) AS workflow_runs,
            COUNT(t.ticket_id) AS ticket_count
        FROM subscriptions AS s
        JOIN product_usage AS u
            ON u.customer_id = s.customer_id AND u.quarter = s.quarter
        JOIN support_tickets AS t
            ON t.customer_id = s.customer_id AND t.quarter = s.quarter
        WHERE s.quarter = '2026-Q2'
        GROUP BY s.customer_id
        ORDER BY ticket_count DESC
        LIMIT 1
        """,
    )

    assert result.rows
    assert set(result.columns) == {
        "customer_id",
        "renewal_status",
        "workflow_runs",
        "ticket_count",
    }


def test_delivery_agent_identifies_delay_and_overrun_signals(
    provider: BusinessDataProvider,
    retriever: KnowledgeRetriever,
) -> None:
    worker = DeliveryAgent(
        model=_WorkerMockModel([_finding_payload()]),
        provider=provider,
        knowledge_retriever=retriever,
    )

    result = worker.execute_sql(
        """
        SELECT
            SUM(CASE WHEN deferred_revenue > 0 THEN 1 ELSE 0 END)
                AS deferred_project_count,
            SUM(deferred_revenue) AS deferred_revenue,
            SUM(CASE WHEN actual_hours > planned_hours THEN 1 ELSE 0 END)
                AS overrun_project_count,
            SUM(outsourcing_cost) AS outsourcing_cost
        FROM projects
        WHERE planned_acceptance_quarter = '2026-Q2'
        """,
    )

    row = result.rows[0]
    assert row["deferred_project_count"] == 4
    assert row["deferred_revenue"] == 3_000_000
    assert row["overrun_project_count"] > 0
    assert row["outsourcing_cost"] > 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("worker_class", "target", "datasets"),
    [
        (
            FinanceSalesAgent,
            WorkerName.FINANCE_SALES,
            ["contracts", "opportunities"],
        ),
        (
            CustomerProductAgent,
            WorkerName.CUSTOMER_PRODUCT,
            ["subscriptions", "product_usage", "support_tickets"],
        ),
        (DeliveryAgent, WorkerName.DELIVERY, ["projects", "contracts"]),
    ],
)
async def test_each_worker_returns_a_validated_finding_through_agentscope(
    worker_class: type,
    target: WorkerName,
    datasets: list[str],
    provider: BusinessDataProvider,
    retriever: KnowledgeRetriever,
) -> None:
    model = _WorkerMockModel([_finding_payload(f"FINDING-{target.value}")])
    worker = worker_class(
        model=model,
        provider=provider,
        knowledge_retriever=retriever,
    )

    finding = await worker.analyze(_task(target, datasets))

    assert isinstance(finding, Finding)
    assert finding.evidence
    assert model.call_count == 1


@pytest.mark.asyncio
async def test_agentscope_executes_scoped_tool_before_structured_finding(
    provider: BusinessDataProvider,
    retriever: KnowledgeRetriever,
) -> None:
    model = _ToolThenFindingMockModel([_finding_payload()])
    worker = FinanceSalesAgent(
        model=model,
        provider=provider,
        knowledge_retriever=retriever,
    )
    calculate_spy = Mock(wraps=worker.calculate)
    worker.calculate = calculate_spy

    finding = await worker.analyze(
        _task(WorkerName.FINANCE_SALES, ["contracts"]),
    )

    assert finding.finding_id == "FINDING-MOCK-001"
    calculate_spy.assert_called_once_with("revenue", "2026-Q2")
    assert model.call_count == 2


@pytest.mark.asyncio
async def test_invalid_structured_output_gets_only_one_correction_attempt(
    provider: BusinessDataProvider,
    retriever: KnowledgeRetriever,
) -> None:
    model = _WorkerMockModel(
        [
            {"finding_id": "invalid"},
            _finding_payload("FINDING-CORRECTED-001"),
        ],
    )
    worker = FinanceSalesAgent(
        model=model,
        provider=provider,
        knowledge_retriever=retriever,
    )

    finding = await worker.analyze(
        _task(WorkerName.FINANCE_SALES, ["contracts"]),
    )

    assert finding.finding_id == "FINDING-CORRECTED-001"
    assert model.call_count == 2
    assert worker.agent.react_config.structured_output_grace_iters == 1


@pytest.mark.asyncio
async def test_worker_rejects_unassigned_dataset_before_model_call(
    provider: BusinessDataProvider,
    retriever: KnowledgeRetriever,
) -> None:
    model = _WorkerMockModel([_finding_payload()])
    worker = FinanceSalesAgent(
        model=model,
        provider=provider,
        knowledge_retriever=retriever,
    )

    with pytest.raises(DatasetAccessError, match="support_tickets"):
        await worker.analyze(
            _task(
                WorkerName.FINANCE_SALES,
                ["contracts", "support_tickets"],
            ),
        )

    assert model.call_count == 0


def test_workers_expose_no_general_file_or_ground_truth_tool(
    provider: BusinessDataProvider,
    retriever: KnowledgeRetriever,
) -> None:
    workers = [
        FinanceSalesAgent(
            model=_WorkerMockModel([_finding_payload()]),
            provider=provider,
            knowledge_retriever=retriever,
        ),
        CustomerProductAgent(
            model=_WorkerMockModel([_finding_payload()]),
            provider=provider,
            knowledge_retriever=retriever,
        ),
        DeliveryAgent(
            model=_WorkerMockModel([_finding_payload()]),
            provider=provider,
            knowledge_retriever=retriever,
        ),
    ]

    for worker in workers:
        assert worker.tool_names == {
            "calculate_metric",
            "compare_periods",
            "describe_dataset",
            "execute_readonly_sql",
            "retrieve_internal_document",
        }
        assert "ground_truth" not in inspect.getsource(worker.__class__)
        assert not {"read", "write", "bash", "powershell"} & worker.tool_names


@pytest.mark.asyncio
async def test_worker_raises_when_both_structured_attempts_are_invalid(
    provider: BusinessDataProvider,
    retriever: KnowledgeRetriever,
) -> None:
    model = _WorkerMockModel([{"finding_id": "invalid"}])
    worker = FinanceSalesAgent(
        model=model,
        provider=provider,
        knowledge_retriever=retriever,
    )

    with pytest.raises(WorkerOutputError):
        await worker.analyze(
            _task(WorkerName.FINANCE_SALES, ["contracts"]),
        )

    assert model.call_count == 2
