"""Shared AgentScope 2.0 worker with scoped, read-only business tools."""

from __future__ import annotations

from abc import ABC
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar

from agentscope.agent import Agent, InjectionConfig, ReActConfig
from agentscope.message import UserMsg
from agentscope.model import ChatModelBase
from agentscope.tool import FunctionTool, Toolkit
from pydantic import BaseModel, Field

from bizinsight.data.provider import (
    BusinessDataProvider,
    DatasetAccessError,
    QueryResult,
)
from bizinsight.schemas import AnalysisTask, Finding, WorkerName
from bizinsight.tools.knowledge import KnowledgeRetriever
from bizinsight.tools.metrics import (
    MetricCalculation,
    calculate_metric,
    compare_periods,
)

ScalarParameter = str | int | float | bool | None


class WorkerOutputError(RuntimeError):
    """Raised when a Worker cannot produce a valid Finding in two iterations."""


class _DatasetInput(BaseModel):
    dataset: str = Field(min_length=1)


class _SqlInput(BaseModel):
    sql: str = Field(min_length=1)
    parameters: list[ScalarParameter] = Field(default_factory=list)
    max_rows: int = Field(default=200, ge=1, le=500)


class _MetricInput(BaseModel):
    metric_name: str = Field(min_length=1)
    period: str = Field(pattern=r"^\d{4}-Q[1-4]$")


class _ComparisonInput(BaseModel):
    metric_name: str = Field(min_length=1)
    current_period: str = Field(pattern=r"^\d{4}-Q[1-4]$")
    comparison_period: str = Field(pattern=r"^\d{4}-Q[1-4]$")


class _RetrievalInput(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=10)


def _query_result_payload(result: QueryResult) -> dict[str, Any]:
    return {
        "columns": list(result.columns),
        "rows": list(result.rows),
        "truncated": result.truncated,
        "evidence": result.evidence.model_dump(mode="json"),
    }


def _metric_payload(result: MetricCalculation) -> dict[str, Any]:
    return {
        "metric": result.metric.model_dump(mode="json"),
        "numerator": str(result.numerator),
        "denominator": (
            None if result.denominator is None else str(result.denominator)
        ),
        "evidence": [item.model_dump(mode="json") for item in result.evidence],
    }


class WorkerBase(ABC):
    """Compose an AgentScope Agent with a strict domain data allowlist."""

    worker_name: ClassVar[WorkerName]
    allowed_datasets: ClassVar[frozenset[str]]
    allowed_metrics: ClassVar[frozenset[str]]
    domain_prompt_filename: ClassVar[str]

    def __init__(
        self,
        *,
        model: ChatModelBase,
        provider: BusinessDataProvider,
        knowledge_retriever: KnowledgeRetriever,
    ) -> None:
        self.provider = provider
        self.knowledge_retriever = knowledge_retriever
        self.toolkit = self._build_toolkit()
        self.tool_names = {
            tool.name for group in self.toolkit.tool_groups for tool in group.tools
        }
        self.agent = Agent(
            name=self.worker_name.value,
            system_prompt=self._load_system_prompt(),
            model=model,
            toolkit=self.toolkit,
            react_config=ReActConfig(
                max_iters=1,
                structured_output_grace_iters=1,
            ),
            injection_config=InjectionConfig(inject_runtime_state=False),
        )

    def _load_system_prompt(self) -> str:
        prompt_dir = Path(__file__).resolve().parents[1] / "prompts"
        common = (prompt_dir / "internal_worker.md").read_text(encoding="utf-8")
        domain = (prompt_dir / self.domain_prompt_filename).read_text(
            encoding="utf-8",
        )
        datasets = ", ".join(sorted(self.allowed_datasets))
        metrics = ", ".join(sorted(self.allowed_metrics))
        return (
            f"{common.strip()}\n\n{domain.strip()}\n\n"
            f"授权数据集：{datasets}\n授权指标：{metrics}"
        )

    def _require_dataset(self, dataset: str) -> None:
        if dataset not in self.allowed_datasets:
            raise DatasetAccessError(
                f"{self.worker_name.value} cannot access dataset {dataset!r}",
            )

    def _require_metric(self, metric_name: str) -> None:
        if metric_name not in self.allowed_metrics:
            raise DatasetAccessError(
                f"{self.worker_name.value} cannot calculate metric {metric_name!r}",
            )

    def execute_sql(
        self,
        sql: str,
        *,
        parameters: Sequence[ScalarParameter] = (),
        max_rows: int = 200,
    ) -> QueryResult:
        """Execute SQL while SQLite enforces this Worker's table scope."""

        return self.provider.execute_readonly_query(
            sql,
            parameters=parameters,
            max_rows=max_rows,
            allowed_datasets=tuple(self.allowed_datasets),
        )

    def calculate(self, metric_name: str, period: str) -> MetricCalculation:
        """Calculate one metric explicitly assigned to this domain."""

        self._require_metric(metric_name)
        return calculate_metric(self.provider, metric_name, period)

    def _build_toolkit(self) -> Toolkit:
        def describe_dataset(dataset: str) -> dict[str, Any]:
            """Describe one dataset authorized for this business domain."""

            self._require_dataset(dataset)
            return self.provider.describe_schema(dataset)

        def execute_readonly_sql(
            sql: str,
            parameters: list[ScalarParameter] | None = None,
            max_rows: int = 200,
        ) -> dict[str, Any]:
            """Run one bounded read-only SQL query over authorized datasets."""

            result = self.execute_sql(
                sql,
                parameters=parameters or (),
                max_rows=max_rows,
            )
            return _query_result_payload(result)

        def calculate_metric(metric_name: str, period: str) -> dict[str, Any]:
            """Calculate an authorized deterministic business metric."""

            return _metric_payload(self.calculate(metric_name, period))

        def compare_metric_periods(
            metric_name: str,
            current_period: str,
            comparison_period: str,
        ) -> dict[str, Any]:
            """Compare an authorized metric between two calendar quarters."""

            self._require_metric(metric_name)
            result = compare_periods(
                self.provider,
                metric_name,
                current_period=current_period,
                comparison_period=comparison_period,
            )
            return {
                "metric_name": metric_name,
                "current": _metric_payload(result.current),
                "comparison": _metric_payload(result.comparison),
                "absolute_change": str(result.absolute_change),
                "relative_change": (
                    None
                    if result.relative_change is None
                    else str(result.relative_change)
                ),
            }

        def retrieve_internal_document(
            query: str,
            top_k: int = 5,
        ) -> dict[str, Any]:
            """Retrieve traceable evidence from the internal document index."""

            result = self.knowledge_retriever.search(query, top_k=top_k)
            return {
                "query": result.query,
                "evidence": [item.model_dump(mode="json") for item in result.evidence],
                "reason": result.reason,
            }

        tools = [
            FunctionTool(
                describe_dataset,
                name="describe_dataset",
                input_schema=_DatasetInput,
                is_read_only=True,
            ),
            FunctionTool(
                execute_readonly_sql,
                name="execute_readonly_sql",
                input_schema=_SqlInput,
                is_read_only=True,
            ),
            FunctionTool(
                calculate_metric,
                name="calculate_metric",
                input_schema=_MetricInput,
                is_read_only=True,
            ),
            FunctionTool(
                compare_metric_periods,
                name="compare_periods",
                input_schema=_ComparisonInput,
                is_read_only=True,
            ),
            FunctionTool(
                retrieve_internal_document,
                name="retrieve_internal_document",
                input_schema=_RetrievalInput,
                is_read_only=True,
            ),
        ]
        return Toolkit(tools=tools)

    async def analyze(self, task: AnalysisTask) -> Finding:
        """Execute an assigned task and return one validated Finding."""

        if task.target_agent is not self.worker_name:
            raise ValueError(
                f"task targets {task.target_agent.value}, not {self.worker_name.value}",
            )
        forbidden = set(task.required_datasets) - self.allowed_datasets
        if forbidden:
            names = ", ".join(sorted(forbidden))
            raise DatasetAccessError(
                f"{self.worker_name.value} cannot access required datasets: {names}",
            )

        message = UserMsg(
            name="BizInsightLeader",
            content=(
                "执行以下经营分析任务，并返回一个带可复算证据的 Finding：\n"
                f"{task.model_dump_json(indent=2)}"
            ),
        )
        response = await self.agent.reply(message, structured_schema=Finding)
        if response.structured_output is None:
            raise WorkerOutputError(
                f"{self.worker_name.value} failed to return a valid Finding "
                "after one correction opportunity",
            )
        try:
            return Finding.model_validate(response.structured_output)
        except ValueError as exc:
            raise WorkerOutputError(
                f"{self.worker_name.value} returned an invalid Finding",
            ) from exc


__all__ = ["DatasetAccessError", "WorkerBase", "WorkerOutputError"]
