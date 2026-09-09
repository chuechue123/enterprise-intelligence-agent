"""Tests for deterministic Leader routing and time normalization."""

from bizinsight.agents.leader import BizInsightLeader
from bizinsight.schemas import WorkerName


def _targets(question: str) -> set[WorkerName]:
    plan = BizInsightLeader().plan_offline(question)
    return {task.target_agent for task in plan.tasks}


def test_comprehensive_question_routes_to_four_workers() -> None:
    plan = BizInsightLeader().plan_offline(
        "分析公司2026年第二季度经营表现下降的主要原因，结合销售、续费、产品、客服和项目交付，并参考行业信息。",
    )

    assert {task.target_agent for task in plan.tasks} == set(WorkerName)
    assert plan.current_period.start_date.isoformat() == "2026-04-01"
    assert plan.current_period.end_date.isoformat() == "2026-06-30"
    assert plan.comparison_period.start_date.isoformat() == "2026-01-01"


def test_specialist_questions_only_route_to_needed_worker() -> None:
    assert _targets("分析2026年第二季度收入、毛利和赢单率") == {
        WorkerName.FINANCE_SALES,
    }
    assert _targets("分析2026年第二季度续费、产品使用和客服工单") == {
        WorkerName.CUSTOMER_PRODUCT,
    }
    assert _targets("分析2026年第二季度项目延期和验收") == {
        WorkerName.DELIVERY,
    }


def test_missing_period_uses_latest_complete_quarter_and_states_assumption() -> None:
    plan = BizInsightLeader().plan_offline("分析公司的续费表现")

    assert plan.current_period.end_date.isoformat() == "2026-06-30"
    assert any("最近完整季度" in item for item in plan.assumptions)


def test_plan_has_at_most_four_unique_tasks() -> None:
    plan = BizInsightLeader().plan_offline("综合分析公司经营表现")

    assert 1 <= len(plan.tasks) <= 4
    assert len({task.task_id for task in plan.tasks}) == len(plan.tasks)
