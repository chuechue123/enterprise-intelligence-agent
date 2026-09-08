"""Tests for analysis planning contracts."""

from datetime import date

import pytest
from pydantic import ValidationError

from bizinsight.schemas.plan import (
    AnalysisPlan,
    AnalysisTask,
    DateRange,
    WorkerName,
)


def _task(
    number: int,
    *,
    depends_on: list[str] | None = None,
) -> AnalysisTask:
    return AnalysisTask(
        task_id=f"TASK-{number}",
        target_agent=WorkerName.FINANCE_SALES,
        question=f"分析任务 {number}",
        required_datasets=["contracts"],
        expected_outputs=["收入指标"],
        depends_on=depends_on or [],
    )


def _plan(tasks: list[AnalysisTask]) -> AnalysisPlan:
    return AnalysisPlan(
        goal="诊断 2026 年第二季度经营下降原因",
        current_period=DateRange(
            start_date=date(2026, 4, 1),
            end_date=date(2026, 6, 30),
        ),
        comparison_period=DateRange(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
        ),
        assumptions=["使用自然季度口径"],
        tasks=tasks,
    )


def test_plan_accepts_at_most_four_unique_tasks() -> None:
    plan = _plan([_task(i) for i in range(1, 5)])

    assert len(plan.tasks) == 4


def test_plan_rejects_more_than_four_tasks() -> None:
    with pytest.raises(ValidationError, match="at most 4"):
        _plan([_task(i) for i in range(1, 6)])


def test_date_range_rejects_reverse_order() -> None:
    with pytest.raises(ValidationError, match="start_date"):
        DateRange(
            start_date=date(2026, 6, 30),
            end_date=date(2026, 4, 1),
        )


def test_plan_rejects_duplicate_or_unknown_task_dependencies() -> None:
    with pytest.raises(ValidationError, match="unique"):
        _plan([_task(1), _task(1)])

    with pytest.raises(ValidationError, match="unknown task"):
        _plan([_task(1, depends_on=["TASK-404"])])


def test_plan_rejects_dependency_cycles() -> None:
    with pytest.raises(ValidationError, match="cycle"):
        _plan(
            [
                _task(1, depends_on=["TASK-2"]),
                _task(2, depends_on=["TASK-1"]),
            ],
        )
