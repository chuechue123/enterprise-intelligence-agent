"""Deterministic Workers for the reproducible, zero-network MVP path."""

from __future__ import annotations

from dataclasses import dataclass

from bizinsight.data.provider import BusinessDataProvider
from bizinsight.schemas import AnalysisTask, Evidence, Finding, WorkerName
from bizinsight.tools.external_search import ExternalSearchService
from bizinsight.tools.knowledge import KnowledgeRetriever
from bizinsight.tools.metrics import MetricComparison, compare_periods
from bizinsight.tools.segments import analyze_segments

WORKER_METRICS = {
    WorkerName.FINANCE_SALES: ("revenue", "gross_margin", "win_rate"),
    WorkerName.CUSTOMER_PRODUCT: ("renewal_rate",),
    WorkerName.DELIVERY: ("on_time_acceptance_rate",),
}
TITLES = {
    WorkerName.FINANCE_SALES: "收入、毛利率与赢单率同步下降",
    WorkerName.CUSTOMER_PRODUCT: "续费率下降并伴随产品与服务压力",
    WorkerName.DELIVERY: "按时验收率下降导致交付风险上升",
}
INTERPRETATIONS = {
    WorkerName.FINANCE_SALES: (
        "销售转化和项目成本同时承压，需要优先复盘重点输单与低毛利合同。"
    ),
    WorkerName.CUSTOMER_PRODUCT: (
        "留存风险值得关注，应联合核查版本使用、工单升级与续费客户反馈。"
    ),
    WorkerName.DELIVERY: "延期验收可能影响收入确认节奏，应检查高定制项目的资源投入。",
}


def _unique_evidence(comparisons: list[MetricComparison]) -> list[Evidence]:
    indexed: dict[str, Evidence] = {}
    for comparison in comparisons:
        for calculation in (comparison.comparison, comparison.current):
            for item in calculation.evidence:
                indexed.setdefault(item.evidence_id, item)
    return list(indexed.values())


@dataclass
class DeterministicDomainWorker:
    """Keep Worker responsibilities while replacing model judgment with rules."""

    worker_name: WorkerName
    provider: BusinessDataProvider
    retriever: KnowledgeRetriever

    async def analyze(self, task: AnalysisTask) -> Finding:
        if task.target_agent is not self.worker_name:
            raise ValueError(f"task is not assigned to {self.worker_name.value}")
        if task.context is None:
            raise ValueError("analysis task is missing period context")
        current = task.context.current_period
        comparison = task.context.comparison_period
        comparisons = [
            compare_periods(
                self.provider,
                name,
                current_period=current,
                comparison_period=comparison,
            )
            for name in WORKER_METRICS[self.worker_name]
        ]
        query = {
            WorkerName.FINANCE_SALES: f"{current} 销售 输单 价格竞争 毛利",
            WorkerName.CUSTOMER_PRODUCT: "CloudFlow 3.2 续费 产品故障 工单 客户反馈",
            WorkerName.DELIVERY: "项目延期 验收 定制 工时 收入确认",
        }[self.worker_name]
        document_result = self.retriever.search(query, top_k=2)
        evidence = _unique_evidence(comparisons)
        evidence.extend(
            item
            for item in document_result.evidence
            if item.evidence_id not in {existing.evidence_id for existing in evidence}
        )
        metrics = [
            calculation.metric
            for item in comparisons
            for calculation in (item.comparison, item.current)
        ]
        changes = "；".join(
            f"{item.current.metric.metric_name} 从 {item.comparison.metric.value} "
            f"变为 {item.current.metric.value}"
            for item in comparisons
        )
        limitations = [] if document_result.evidence else [str(document_result.reason)]
        segment_note = ""
        if task.context.filters:
            dimension, value = next(iter(task.context.filters.items()))
            dataset = {
                WorkerName.FINANCE_SALES: "contracts",
                WorkerName.CUSTOMER_PRODUCT: (
                    "product_usage"
                    if dimension == "product_version"
                    else "subscriptions"
                ),
                WorkerName.DELIVERY: "projects",
            }[self.worker_name]
            try:
                segment = analyze_segments(
                    self.provider,
                    dataset=dataset,
                    dimension=dimension,
                    period=current,
                    dimension_value=value,
                )
                evidence.append(segment.evidence)
                segment_note = (
                    f"；已按 {dimension}={value} 查询 {len(segment.rows)} 个细分结果"
                )
            except ValueError as exc:
                limitations.append(str(exc))
        return Finding(
            finding_id=f"FINDING-{self.worker_name.value.replace('Agent', '').lower()}",
            title=TITLES[self.worker_name],
            fact_statement=f"{comparison} 到 {current}：{changes}{segment_note}。",
            metrics=metrics,
            evidence=evidence,
            business_interpretation=INTERPRETATIONS[self.worker_name],
            causal_assessment="当前数据说明关联，具体因果仍需业务访谈或更细粒度数据验证。",
            confidence=0.9,
            limitations=limitations,
        )


@dataclass
class DeterministicExternalWorker:
    """Convert online or fallback research into a non-causal context Finding."""

    service: ExternalSearchService

    async def analyze(self, task: AnalysisTask) -> Finding:
        result = self.service.search(
            "企业低代码市场 价格竞争 客户留存 可靠性", max_results=3
        )
        limitations = [result.degradation_reason] if result.degradation_reason else []
        return Finding(
            finding_id="FINDING-externalresearch",
            title="外部行业竞争与客户留存背景",
            fact_statement=(
                "公开或本地行业资料显示，价格竞争、产品可靠性和价值实现是企业软件留存的重要背景。"
            ),
            evidence=result.evidence,
            business_interpretation="该信息用于补充背景，不能替代公司内部数据诊断。",
            causal_assessment="外部趋势与内部异常可能相关，但尚未验证内部因果。",
            confidence=0.6,
            limitations=[item for item in limitations if item],
            is_key=False,
        )
