"""BizInsight Leader planning for online AgentScope and deterministic offline use."""

from __future__ import annotations

import re
from pathlib import Path

from agentscope.agent import Agent, InjectionConfig, ReActConfig
from agentscope.message import UserMsg
from agentscope.model import ChatModelBase

from bizinsight.data.provider import BusinessDataProvider
from bizinsight.schemas import AnalysisContext, AnalysisPlan, AnalysisTask, WorkerName
from bizinsight.time_periods import quarter_range, resolve_periods

DOMAIN_CONFIG = {
    WorkerName.FINANCE_SALES: {
        "keywords": (
            "收入",
            "营收",
            "毛利",
            "销售",
            "商机",
            "赢单",
            "输单",
            "回款",
            "合同",
        ),
        "datasets": ["contracts", "opportunities", "payments", "customers"],
        "outputs": ["收入、毛利、赢单与回款异常 Finding"],
    },
    WorkerName.CUSTOMER_PRODUCT: {
        "keywords": (
            "续费",
            "流失",
            "客户",
            "产品",
            "使用",
            "工单",
            "客服",
            "满意度",
            "版本",
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
FILTER_VALUES = {
    "region": ("华东", "华南", "华北", "西南", "华中"),
    "industry": ("制造", "金融", "零售", "医疗", "教育"),
    "size_segment": ("SMB", "Mid-Market", "Enterprise"),
}


def _filters_from_question(question: str) -> dict[str, str]:
    filters: dict[str, str] = {}
    lowered = question.lower()
    for dimension, values in FILTER_VALUES.items():
        for value in values:
            if value.lower() in lowered:
                filters[dimension] = value
                break
    version = re.search(r"(?:v|版本\s*)(\d+(?:\.\d+)+)", question, re.I)
    if version:
        filters["product_version"] = f"v{version.group(1)}"
    return filters


class BizInsightLeader:
    """Create a bounded AnalysisPlan and hand it to the workflow scheduler."""

    def __init__(
        self,
        model: ChatModelBase | None = None,
        provider: BusinessDataProvider | None = None,
    ) -> None:
        self.provider = provider
        self.last_usage = None
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

    def plan_offline(self, question: str) -> AnalysisPlan:
        """Produce a deterministic plan when no online model is requested."""

        question = question.strip()
        if not question:
            raise ValueError("question must not be empty")
        if self.provider is None:
            from bizinsight.data.provider import BusinessDataProvider

            root = Path(__file__).resolve().parents[3]
            self.provider = BusinessDataProvider(
                database_path=root / "data/database/bizinsight.sqlite",
                table_dictionary_path=root / "data/data_dictionary/tables.yaml",
                metric_dictionary_path=root / "data/data_dictionary/metrics.yaml",
            )
        current, comparison, assumed = resolve_periods(question, self.provider)
        filters = _filters_from_question(question)
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
                context=AnalysisContext(
                    current_period=current,
                    comparison_period=comparison,
                    filters=filters,
                ),
            )
            for index, worker in enumerate(targets[:4], start=1)
        ]
        assumptions = []
        if assumed:
            assumptions.append(
                f"问题未指定时间范围，使用数据中的最近完整季度 {current}。"
            )
        assumptions.append("所有关键数字由只读 SQL/Python 工具计算。")
        return AnalysisPlan(
            goal=question,
            current_period=quarter_range(current),
            comparison_period=quarter_range(comparison),
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
        self.last_usage = response.usage
        if response.structured_output is None:
            return self.plan_offline(question)
        plan = AnalysisPlan.model_validate(response.structured_output)
        current = plan.current_period.quarter
        comparison = plan.comparison_period.quarter
        tasks = [
            task
            if task.context is not None
            else task.model_copy(
                update={
                    "context": AnalysisContext(
                        current_period=current,
                        comparison_period=comparison,
                    )
                }
            )
            for task in plan.tasks
        ]
        return plan.model_copy(update={"tasks": tasks})
