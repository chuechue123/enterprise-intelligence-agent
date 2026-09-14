"""Regression tests for MCP cleanup surviving anyio cancel-scope noise."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from bizinsight.mcp.client import BusinessMCPConnection


class _ClientWithCancellingClose:
    """Stand-in AgentScope MCPClient whose close raises CancelledError.

    Mirrors the observed anyio stdio task-group unwind: the internal cancel
    scope fires even though no external cancellation is pending.
    """

    name = "bizinsight-test"

    async def close(self) -> None:
        raise asyncio.CancelledError


class _ClientWithRealClose:
    name = "bizinsight-test"

    async def close(self) -> None:
        return None


def _wrap(client: Any) -> BusinessMCPConnection:
    return BusinessMCPConnection(client=client)


@pytest.mark.asyncio
async def test_close_swallows_internal_cancelled_error() -> None:
    """CancelledError without external cancellation must not propagate."""

    connection = _wrap(_ClientWithCancellingClose())
    await connection.close()


@pytest.mark.asyncio
async def test_close_resets_side_effect_cancellation() -> None:
    """The anyio side effect cancels the host task; cleanup must reset it
    so the caller can finish without an orphaned cancellation."""

    connection = _wrap(_ClientWithCancellingClose())
    task = asyncio.current_task()
    assert task is not None
    task.cancel()  # simulates the anyio worker-thread stop side effect
    await connection.close()
    assert task.cancelling() == 0


@pytest.mark.asyncio
async def test_close_happy_path_unchanged() -> None:
    connection = _wrap(_ClientWithRealClose())
    await connection.close()
