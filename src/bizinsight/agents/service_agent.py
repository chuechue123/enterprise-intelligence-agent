"""AgentScope Web UI adapter backed by the general SupervisorAgent."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from bizinsight.agents.supervisor import SupervisorAgent


class BizInsightServiceAgent(SupervisorAgent):
    """Bind the general Supervisor to the configured project root."""

    project_root: ClassVar[Path | None] = None

    @classmethod
    def configure(cls, *, project_root: Path) -> None:
        cls.project_root = project_root.resolve()

    def __init__(self, *args, **kwargs) -> None:
        if self.project_root is None:
            raise RuntimeError("BizInsightServiceAgent is not configured")
        super().__init__(
            *args,
            project_root=self.project_root,
            **kwargs,
        )


__all__ = ["BizInsightServiceAgent"]
