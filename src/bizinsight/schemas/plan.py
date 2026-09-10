"""Structured contracts for business-analysis planning."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class WorkerName(StrEnum):
    """Workers that may receive an analysis task from the Leader."""

    FINANCE_SALES = "FinanceSalesAgent"
    CUSTOMER_PRODUCT = "CustomerProductAgent"
    DELIVERY = "DeliveryAgent"
    EXTERNAL_RESEARCH = "ExternalResearchAgent"


class DateRange(BaseModel):
    """Inclusive calendar range used by an analysis plan."""

    model_config = ConfigDict(extra="forbid")

    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_order(self) -> DateRange:
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self

    @property
    def quarter(self) -> str:
        """Return the canonical quarter represented by this range."""
        return f"{self.start_date.year}-Q{((self.start_date.month - 1) // 3) + 1}"


class AnalysisContext(BaseModel):
    """Immutable period and segmentation context shared with a Worker."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    current_period: str = Field(pattern=r"^\d{4}-Q[1-4]$")
    comparison_period: str = Field(pattern=r"^\d{4}-Q[1-4]$")
    filters: dict[str, NonEmptyStr] = Field(default_factory=dict)


class AnalysisTask(BaseModel):
    """One typed unit of work assigned to a domain Worker."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(pattern=r"^TASK-[A-Za-z0-9][A-Za-z0-9_-]*$")
    target_agent: WorkerName
    question: NonEmptyStr
    required_datasets: list[NonEmptyStr] = Field(min_length=1)
    expected_outputs: list[NonEmptyStr] = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)
    context: AnalysisContext | None = None

    @model_validator(mode="after")
    def validate_unique_lists(self) -> AnalysisTask:
        for name in ("required_datasets", "expected_outputs", "depends_on"):
            values = getattr(self, name)
            if len(values) != len(set(values)):
                raise ValueError(f"{name} values must be unique")
        return self


class AnalysisPlan(BaseModel):
    """Leader output describing a bounded, executable analysis plan."""

    model_config = ConfigDict(extra="forbid")

    goal: NonEmptyStr
    current_period: DateRange
    comparison_period: DateRange
    assumptions: list[NonEmptyStr] = Field(default_factory=list)
    tasks: list[AnalysisTask] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_task_graph(self) -> AnalysisPlan:
        task_ids = [task.task_id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("task_id values must be unique")

        known_ids = set(task_ids)
        dependencies = {task.task_id: task.depends_on for task in self.tasks}
        for task_id, required_ids in dependencies.items():
            unknown = set(required_ids) - known_ids
            if unknown:
                unknown_list = ", ".join(sorted(unknown))
                raise ValueError(
                    f"task {task_id} depends on unknown task: {unknown_list}",
                )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise ValueError("task dependency cycle detected")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency_id in dependencies[task_id]:
                visit(dependency_id)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in task_ids:
            visit(task_id)
        return self
