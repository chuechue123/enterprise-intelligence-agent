"""AgentScope Web UI adapter that delegates every turn to BizInsight."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from agentscope.agent import Agent
from agentscope.message import AssistantMsg, Msg


class BizInsightServiceAgent(Agent):
    """Keep AgentScope's lifecycle while replacing its business reply path."""

    project_root: ClassVar[Path | None] = None

    @classmethod
    def configure(cls, *, project_root: Path) -> None:
        cls.project_root = project_root.resolve()

    def __init__(self, *args, **kwargs) -> None:
        self._service_model = kwargs.get("model")
        super().__init__(*args, **kwargs)

    async def reply(self, inputs=None, structured_schema=None) -> Msg:
        del structured_schema
        if inputs is None:
            return await super().reply(inputs)
        messages = inputs if isinstance(inputs, list) else [inputs]
        question = "\n".join(
            item.get_text_content() for item in messages if isinstance(item, Msg)
        ).strip()
        if not question:
            return AssistantMsg(name=self.name, content="请输入需要分析的经营问题。")
        if self.project_root is None:
            raise RuntimeError("BizInsightServiceAgent is not configured")

        from bizinsight.app import run_analysis

        session_id = getattr(getattr(self, "state", None), "session_id", None) or "web"
        result = await run_analysis(
            question,
            project_root=self.project_root,
            output_dir=self.project_root / "outputs" / session_id,
            session_id=session_id,
            mode="online",
            model_override=self._service_model,
        )
        relative = result.report.html_path.resolve().relative_to(
            (self.project_root / "outputs").resolve()
        )
        report_url = "/bizinsight/reports/" + relative.as_posix()
        content = (
            f"分析完成，共形成 {len(result.findings)} 条证据结论，"
            f"终审状态：{result.review.status.value}。\n\n"
            f"[打开完整经营分析报告]({report_url})\n\n"
            f"运行编号：{result.telemetry.run_id}"
        )
        return AssistantMsg(
            name=self.name,
            content=content,
            metadata={
                "bizinsight_report": report_url,
                "bizinsight_events": str(result.event_path),
                "run_id": result.telemetry.run_id,
            },
        )


__all__ = ["BizInsightServiceAgent"]
