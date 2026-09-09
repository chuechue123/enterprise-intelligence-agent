"""BizInsight Leader planning for online AgentScope and deterministic offline use."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from agentscope.agent import Agent, InjectionConfig, ReActConfig
from agentscope.message import UserMsg
from agentscope.model import ChatModelBase

from bizinsight.schemas import AnalysisPlan, AnalysisTask, DateRange, WorkerName

QUARTER_DATES = {
    1: ((1, 1), (3, 31)),
    2: ((4, 1), (6, 30)),
    3: ((7, 1), (9, 30)),
    4: ((10, 1), (12, 31)),
}
DOMAIN_CONFIG = {
    WorkerName.FINANCE_SALES: {
        "keywords": (
            "收入", "营收", "毛利", "销售", "商机", "赢单", "输单", "回款", "合同",
        ),
        "datasets": ["contracts", "opportunities", "payments", "customers"],
        "outputs": ["收入、毛利、赢单与回款异常 Finding"],
    },
    WorkerName.CUSTOMER_PRODUCT: {
        "keywords": (
            "续费", "流失", "客户", "产品", "使用", "工单", "客服", "满意度", "版本",
        ),
        "datasets": ["subscriptions", "product_usage", "support_tickets", "customers"],
        "outputs": ["续费、使用与服务质量关联 Finding"],
    },
    WorkerName.DELIVERY: {
        "keywords": ("项目", "交付", "验收", "延期", "工时", "定制", "外包"),
        "datasets": ["projects", "contracts", "customers"],
        "outputs": ["交付、工时与收入递延 Finding"],
    },
    WorkerName.EXTERNAL_RESEARCH: {
        "keywords": ("行业", "市场", "外部", "政策", "竞品", "竞争"),
        "datasets": ["external_information"],
        "outputs": ["带来源且不越过因果边界的行业背景"],
    },
}


def _quarter_range(year: int, quarter: int) -> DateRange:
    start, end = QUARTER_DATES[quarter]
    return DateRange(
        start_date=date(year, *start),
        end_date=date(year, *end),
    )


def _previous_quarter(year: int, quarter: int) -> tuple[int, int]:
    return (year - 1, 4) if quarter == 1 else (year, quarter - 1)


class BizInsightLeader:
    """Create a bounded AnalysisPlan and hand it to the workflow scheduler."""

    def __init__(self, model: ChatModelBase | None = None) -> None:
        self.agent: Agent | None = None
        if model is not None:
            prompt = (
                Path(__file__).resolve().parents[1] / "prompts" / "leader.md"
            ).read_text(encoding="utf-8")
            self.agent = Agent(
                name="BizInsightLeader",
                system_prompt=prompt,
                model=model,
                react_config=ReActConfig(
                    max_iters=1,
                    structured_output_grace_iters=1,
                ),
                injection_config=InjectionConfig(inject_runtime_state=False),
            )

    @staticmethod
    def _period_from_question(question: str) -> tuple[int, int, bool]:
        match = re.search(
            r"(20\d{2})\s*年?\s*(?:第?\s*([一二三四1234])\s*季度|Q([1-4]))",
            question,
            flags=re.IGNORECASE,
        )
        if not match:
            return 2026, 2, True
        quarter_token = match.group(2) or match.group(3)
        quarter = (
            int(quarter_token)
            if quarter_token.isdigit()
            else {"一": 1, "二": 2, "三": 3, "四": 4}[quarter_token]
        )
        return int(match.group(1)), quarter, False

    def plan_offline(self, question: str) -> AnalysisPlan:
        """Produce a deterministic plan when no online model is requested."""

        question = question.strip()
        if not question:
            raise ValueError("question must not be empty")
        year, quarter, assumed = self._period_from_question(question)
        previous_year, previous_quarter = _previous_quarter(year, quarter)
        comprehensive = any(
            keyword in question
            for keyword in ("综合", "经营表现", "主要原因", "经营异常")
        )
        targets = [
            worker
            for worker, config in DOMAIN_CONFIG.items()
            if comprehensive
            or any(keyword in question for keyword in config["keywords"])
        ]
        if not targets:
            targets = [WorkerName.FINANCE_SALES]
        if comprehensive and WorkerName.EXTERNAL_RESEARCH not in targets:
            targets.append(WorkerName.EXTERNAL_RESEARCH)

        tasks = [
            AnalysisTask(
                task_id=f"TASK-{index:02d}-{worker.value}",
                target_agent=worker,
                question=question,
                required_datasets=list(DOMAIN_CONFIG[worker]["datasets"]),
                expected_outputs=list(DOMAIN_CONFIG[worker]["outputs"]),
            )
            for index, worker in enumerate(targets[:4], start=1)
        ]
        assumptions = []
        if assumed:
            assumptions.append("问题未指定时间范围，使用数据中的最近完整季度 2026-Q2。")
        assumptions.append("所有关键数字由只读 SQL/Python 工具计算。")
        return AnalysisPlan(
            goal=question,
            current_period=_quarter_range(year, quarter),
            comparison_period=_quarter_range(previous_year, previous_quarter),
            assumptions=assumptions,
            tasks=tasks,
        )

    async def plan(self, question: str) -> AnalysisPlan:
        """Use AgentScope online when configured, otherwise deterministic routing."""

        if self.agent is None:
            return self.plan_offline(question)
        response = await self.agent.reply(
            UserMsg(name="user", content=question),
            structured_schema=AnalysisPlan,
        )
        if response.structured_output is None:
            return self.plan_offline(question)
        return AnalysisPlan.model_validate(response.structured_output)
