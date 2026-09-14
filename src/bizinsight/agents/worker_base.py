"""Shared AgentScope 2.0 worker with scoped, read-only business tools."""

from __future__ import annotations

import inspect
from abc import ABC
from collections.abc import Sequence
from pathlib import Path
from typing import Any, ClassVar

from agentscope.agent import Agent, InjectionConfig, ReActConfig
from agentscope.message import ToolResultBlock, Usage, UserMsg
from agentscope.model import ChatModelBase
from agentscope.tool import FunctionTool, Toolkit
from pydantic import BaseModel, Field, ValidationError

from bizinsight.data.provider import (
    BusinessDataProvider,
    DatasetAccessError,
    QueryResult,
)
from bizinsight.observability import aggregate_agent_usage
from bizinsight.schemas import AnalysisTask, Finding, WorkerName
from bizinsight.tools.knowledge import KnowledgeRetriever
from bizinsight.tools.metrics import (
    MetricCalculation,
    calculate_metric,
    compare_periods,
)
from bizinsight.tools.segments import analyze_segments

ScalarParameter = str | int | float | bool | None


class WorkerOutputError(RuntimeError):
    """Raised when a Worker cannot produce a valid Finding after recovery."""


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


class _SegmentInput(BaseModel):
    dataset: str = Field(min_length=1)
    dimension: str = Field(min_length=1)
    period: str = Field(pattern=r"^\d{4}-Q[1-4]$")
    dimension_value: str | None = None


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
        self._model = model
        self._system_prompt = self._load_system_prompt()
        self.last_usage = None
        self.last_output_attempts = 0
        self.last_output_error: str | None = None
        self.toolkit = self._build_toolkit()
        self.tool_names = {
            tool.name for group in self.toolkit.tool_groups for tool in group.tools
        }
        self.agent = self._build_agent()
        self._mcp_connection = None

    def _build_agent(self) -> Agent:
        """Create a Worker agent with a fresh conversation context."""

        return Agent(
            name=self.worker_name.value,
            system_prompt=self._system_prompt,
            model=self._model,
            toolkit=self.toolkit,
            react_config=ReActConfig(
                max_iters=3,
                structured_output_grace_iters=2,
            ),
            injection_config=InjectionConfig(inject_runtime_state=False),
        )

    @staticmethod
    def _merge_usage(*items: Usage | None) -> Usage | None:
        available = [item for item in items if item is not None]
        if not available:
            return None
        return Usage(
            input_tokens=sum(item.input_tokens for item in available),
            output_tokens=sum(item.output_tokens for item in available),
            cache_input_tokens=sum(
                item.cache_input_tokens for item in available
            ),
            cache_creation_input_tokens=sum(
                item.cache_creation_input_tokens for item in available
            ),
        )

    @staticmethod
    def _structured_output_error(agent: Agent) -> str:
        """Return the last safe schema error retained by AgentScope."""

        state = getattr(agent, "state", None)
        context = getattr(state, "context", ())
        for message in reversed(context):
            for block in reversed(getattr(message, "content", ())):
                if not isinstance(block, ToolResultBlock):
                    continue
                if block.name != "GenerateStructuredOutput":
                    continue
                if block.state != "error":
                    continue
                if isinstance(block.output, str):
                    detail = block.output
                else:
                    detail = " ".join(
                        item.text
                        for item in block.output
                        if getattr(item, "type", None) == "text"
                    )
                detail = " ".join(detail.split())
                if detail:
                    return detail[:500]
        return "AgentScope exhausted structured-output iterations"

    async def _request_finding(
        self,
        agent: Agent,
        message: UserMsg,
    ) -> tuple[Finding | None, Usage | None, str | None]:
        """Run one independent AgentScope attempt."""

        response = await agent.reply(message, structured_schema=Finding)
        usage = response.usage or aggregate_agent_usage(agent)
        if response.structured_output is None:
            return None, usage, self._structured_output_error(agent)
        try:
            return Finding.model_validate(response.structured_output), usage, None
        except ValueError as exc:
            if isinstance(exc, ValidationError):
                detail = "; ".join(
                    f"{'.'.join(str(part) for part in item['loc'])}: "
                    f"{item['msg']}"
                    for item in exc.errors()
                )
            else:
                detail = type(exc).__name__
            return None, usage, detail[:500]

    async def attach_business_mcp(self, project_root: Path) -> list[str]:
        """Add scoped MCP tools through AgentScope without changing local logic."""
        from bizinsight.mcp import BusinessMCPConnection

        self._mcp_connection = BusinessMCPConnection.build(
            scope=self.worker_name.value,
            project_root=project_root,
        )
        return await self._mcp_connection.connect_to(self.toolkit)

    async def close(self) -> None:
        if self._mcp_connection is not None:
            await self._mcp_connection.close()

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

        async def retrieve_internal_document(
            query: str,
            top_k: int = 5,
        ) -> dict[str, Any]:
            """Retrieve traceable evidence from the internal document index."""

            result = self.knowledge_retriever.search(query, top_k=top_k)
            if inspect.isawaitable(result):
                result = await result
            return {
                "query": result.query,
                "evidence": [item.model_dump(mode="json") for item in result.evidence],
                "reason": result.reason,
            }

        def analyze_business_segments(
            dataset: str,
            dimension: str,
            period: str,
            dimension_value: str | None = None,
        ) -> dict[str, Any]:
            """Analyze an authorized dataset by a controlled business dimension."""
            self._require_dataset(dataset)
            result = analyze_segments(
                self.provider,
                dataset=dataset,
                dimension=dimension,
                period=period,
                dimension_value=dimension_value,
            )
            return {
                "dataset": result.dataset,
                "dimension": result.dimension,
                "period": result.period,
                "rows": list(result.rows),
                "evidence": result.evidence.model_dump(mode="json"),
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
            FunctionTool(
                analyze_business_segments,
                name="analyze_business_segments",
                input_schema=_SegmentInput,
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

        self.last_usage = None
        self.last_output_attempts = 0
        self.last_output_error = None

        for attempt in range(1, 3):
            if attempt == 2:
                self.agent = self._build_agent()
            recovery_note = (
                "\n这是一次独立恢复重试。请重新核验所需证据，并严格调用 "
                "GenerateStructuredOutput 返回完整 Finding。"
                if attempt == 2
                else ""
            )
            message = UserMsg(
                name="BizInsightLeader",
                content=(
                    "执行以下经营分析任务，并返回一个带可复算证据的 Finding：\n"
                    f"{task.model_dump_json(indent=2)}{recovery_note}"
                ),
            )
            finding, usage, error = await self._request_finding(
                self.agent,
                message,
            )
            self.last_output_attempts = attempt
            self.last_usage = self._merge_usage(self.last_usage, usage)
            self.last_output_error = error
            if finding is not None:
                return finding

        raise WorkerOutputError(
            f"{self.worker_name.value} failed to return a valid Finding "
            f"after {self.last_output_attempts} independent attempts; "
            f"last structured-output error: {self.last_output_error}",
        )


__all__ = ["DatasetAccessError", "WorkerBase", "WorkerOutputError"]
