"""Dependency-aware asynchronous execution with AgentScope custom events."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from agentscope.event import CustomEvent

from bizinsight.schemas import AnalysisPlan, AnalysisTask, Finding, WorkerName


class WorkerProtocol(Protocol):
    async def analyze(self, task: AnalysisTask) -> Finding: ...


class TaskStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class TaskExecution:
    task: AnalysisTask
    status: TaskStatus
    duration_ms: float
    finding: Finding | None = None
    error: str | None = None


@dataclass(frozen=True)
class WorkflowResult:
    plan: AnalysisPlan
    executions: tuple[TaskExecution, ...]
    events: tuple[CustomEvent, ...]

    @property
    def findings(self) -> list[Finding]:
        return [item.finding for item in self.executions if item.finding is not None]

    @property
    def errors(self) -> list[str]:
        return [item.error for item in self.executions if item.error is not None]


EventSink = Callable[[CustomEvent], Awaitable[None] | None]


class AnalysisWorkflow:
    """Execute ready tasks concurrently and isolate failures per Worker."""

    def __init__(
        self,
        workers: Mapping[WorkerName, WorkerProtocol],
        *,
        worker_timeout_seconds: float = 30,
        event_sink: EventSink | None = None,
    ) -> None:
        if worker_timeout_seconds <= 0:
            raise ValueError("worker_timeout_seconds must be positive")
        self.workers = dict(workers)
        self.worker_timeout_seconds = worker_timeout_seconds
        self.event_sink = event_sink
        self._events: list[CustomEvent] = []

    async def _emit(
        self,
        event: str,
        task: AnalysisTask | None = None,
        **detail,
    ) -> None:
        value = {"event": event, **detail}
        if task is not None:
            value.update(
                {
                    "task_id": task.task_id,
                    "worker": task.target_agent.value,
                },
            )
        item = CustomEvent(name="bizinsight_workflow", value=value)
        self._events.append(item)
        if self.event_sink is not None:
            result = self.event_sink(item)
            if inspect.isawaitable(result):
                await result

    async def _run_task(self, task: AnalysisTask) -> TaskExecution:
        worker = self.workers.get(task.target_agent)
        if worker is None:
            return TaskExecution(
                task,
                TaskStatus.FAILED,
                0,
                error=f"worker unavailable: {task.target_agent.value}",
            )
        await self._emit("task_started", task)
        started = time.monotonic()
        try:
            finding = await asyncio.wait_for(
                worker.analyze(task),
                timeout=self.worker_timeout_seconds,
            )
        except TimeoutError:
            duration = (time.monotonic() - started) * 1_000
            await self._emit("task_timed_out", task, duration_ms=duration)
            return TaskExecution(
                task,
                TaskStatus.TIMED_OUT,
                duration,
                error="worker timeout",
            )
        except Exception as exc:
            duration = (time.monotonic() - started) * 1_000
            await self._emit("task_failed", task, duration_ms=duration, error=str(exc))
            return TaskExecution(task, TaskStatus.FAILED, duration, error=str(exc))
        duration = (time.monotonic() - started) * 1_000
        await self._emit("task_completed", task, duration_ms=duration)
        return TaskExecution(task, TaskStatus.COMPLETED, duration, finding=finding)

    async def execute(self, plan: AnalysisPlan) -> WorkflowResult:
        self._events = []
        await self._emit("plan_created", task_count=len(plan.tasks))
        pending = {task.task_id: task for task in plan.tasks}
        completed: dict[str, TaskExecution] = {}

        while pending:
            skipped: list[str] = []
            for task_id, task in pending.items():
                failed_dependencies = [
                    dependency
                    for dependency in task.depends_on
                    if dependency in completed
                    and completed[dependency].status is not TaskStatus.COMPLETED
                ]
                if failed_dependencies:
                    execution = TaskExecution(
                        task,
                        TaskStatus.SKIPPED,
                        0,
                        error="failed dependency: " + ", ".join(failed_dependencies),
                    )
                    completed[task_id] = execution
                    skipped.append(task_id)
                    await self._emit("task_skipped", task, error=execution.error)
            for task_id in skipped:
                pending.pop(task_id)

            ready = [
                task
                for task in pending.values()
                if all(dependency in completed for dependency in task.depends_on)
            ]
            if not ready and pending:
                raise RuntimeError("workflow has unresolved task dependencies")
            results = await asyncio.gather(*(self._run_task(task) for task in ready))
            for result in results:
                completed[result.task.task_id] = result
                pending.pop(result.task.task_id)

        executions = tuple(completed[task.task_id] for task in plan.tasks)
        await self._emit(
            "workflow_completed",
            completed=sum(item.status is TaskStatus.COMPLETED for item in executions),
            failed=sum(item.status is not TaskStatus.COMPLETED for item in executions),
        )
        return WorkflowResult(plan, executions, tuple(self._events))
