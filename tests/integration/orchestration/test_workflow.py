"""Tests for dependency-aware parallel Worker orchestration."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import pytest

from bizinsight.agents.leader import BizInsightLeader
from bizinsight.orchestration.workflow import AnalysisWorkflow, TaskStatus
from bizinsight.schemas import Evidence, EvidenceType, Finding, WorkerName


def _finding(worker: WorkerName) -> Finding:
    return Finding(
        finding_id=f"FINDING-{worker.value}",
        title=f"{worker.value} 结论",
        fact_statement="确定性测试结论。",
        evidence=[
            Evidence(
                evidence_id=f"DB-{worker.value}",
                evidence_type=EvidenceType.DATABASE,
                source="test.sqlite",
                locator="SQL: SELECT 1",
                summary="测试证据",
                generated_at=datetime.now(UTC),
            ),
        ],
        business_interpretation="用于验证调度。",
        confidence=0.8,
    )


class _Worker:
    def __init__(self, name: WorkerName, *, delay: float = 0, fail: bool = False):
        self.name = name
        self.delay = delay
        self.fail = fail

    async def analyze(self, task):
        del task
        await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("planned worker failure")
        return _finding(self.name)


@pytest.mark.asyncio
async def test_independent_workers_run_in_parallel_and_emit_agentscope_events() -> None:
    plan = BizInsightLeader().plan_offline("综合分析公司经营表现")
    workers = {
        name: _Worker(name, delay=0.05)
        for name in WorkerName
    }
    workflow = AnalysisWorkflow(workers, worker_timeout_seconds=1)

    started = time.monotonic()
    result = await workflow.execute(plan)
    elapsed = time.monotonic() - started

    assert elapsed < 0.16
    assert len(result.findings) == 4
    assert all(item.status is TaskStatus.COMPLETED for item in result.executions)
    event_names = [event.value["event"] for event in result.events]
    assert event_names.count("task_started") == 4
    assert event_names.count("task_completed") == 4
    assert all(event.name == "bizinsight_workflow" for event in result.events)


@pytest.mark.asyncio
async def test_one_worker_failure_does_not_discard_other_results() -> None:
    plan = BizInsightLeader().plan_offline("综合分析公司经营表现")
    workers = {
        name: _Worker(name, fail=name is WorkerName.EXTERNAL_RESEARCH)
        for name in WorkerName
    }

    result = await AnalysisWorkflow(workers).execute(plan)

    assert len(result.findings) == 3
    failed = [item for item in result.executions if item.status is TaskStatus.FAILED]
    assert len(failed) == 1
    assert "planned worker failure" in (failed[0].error or "")


@pytest.mark.asyncio
async def test_worker_timeout_is_isolated() -> None:
    plan = BizInsightLeader().plan_offline("分析收入和项目交付")
    workers = {
        WorkerName.FINANCE_SALES: _Worker(WorkerName.FINANCE_SALES),
        WorkerName.DELIVERY: _Worker(WorkerName.DELIVERY, delay=0.1),
    }

    result = await AnalysisWorkflow(
        workers,
        worker_timeout_seconds=0.01,
    ).execute(plan)

    assert len(result.findings) == 1
    assert {item.status for item in result.executions} == {
        TaskStatus.COMPLETED,
        TaskStatus.TIMED_OUT,
    }
