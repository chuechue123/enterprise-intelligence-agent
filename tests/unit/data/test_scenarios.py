"""Tests for the five injected business anomaly scenarios."""

from __future__ import annotations

import pandas as pd

from bizinsight.data.generator import DEFAULT_SEED, generate_dataset


def _quarter(frame: pd.DataFrame, column: str, quarter: str) -> pd.DataFrame:
    return frame.loc[frame[column] == quarter]


def test_four_large_projects_defer_three_million_revenue() -> None:
    dataset = generate_dataset(DEFAULT_SEED)
    scenario = dataset.ground_truth["scenarios"]["delayed_acceptance"]
    projects = dataset.tables["projects"]
    delayed = projects.loc[projects["project_id"].isin(scenario["project_ids"])]

    assert len(delayed) == 4
    assert delayed["actual_acceptance_date"].isna().all()
    assert delayed["planned_acceptance_quarter"].eq("2026-Q2").all()
    assert delayed["deferred_revenue"].sum() == 3_000_000


def test_q2_customization_and_cost_overrun_are_higher_than_q1() -> None:
    projects = generate_dataset(DEFAULT_SEED).tables["projects"]
    q1 = _quarter(projects, "planned_acceptance_quarter", "2026-Q1")
    q2 = _quarter(projects, "planned_acceptance_quarter", "2026-Q2")

    q1_high_custom = q1["customization_level"].eq("high").mean()
    q2_high_custom = q2["customization_level"].eq("high").mean()
    q1_overrun = (q1["actual_hours"] / q1["planned_hours"]).mean()
    q2_overrun = (q2["actual_hours"] / q2["planned_hours"]).mean()

    assert q2_high_custom > q1_high_custom
    assert q2_overrun > q1_overrun
    assert q2["outsourcing_cost"].mean() > q1["outsourcing_cost"].mean()


def test_v32_cohort_links_tickets_usage_and_renewal_decline() -> None:
    dataset = generate_dataset(DEFAULT_SEED)
    scenario = dataset.ground_truth["scenarios"]["v32_stability"]
    customer_ids = scenario["customer_ids"]

    usage = dataset.tables["product_usage"]
    affected_usage = usage.loc[usage["customer_id"].isin(customer_ids)]
    q1_usage = _quarter(affected_usage, "quarter", "2026-Q1")
    q2_usage = _quarter(affected_usage, "quarter", "2026-Q2")

    tickets = dataset.tables["support_tickets"]
    affected_tickets = tickets.loc[tickets["customer_id"].isin(customer_ids)]
    q1_severe = _quarter(affected_tickets, "quarter", "2026-Q1")[
        "severity"
    ].isin(["high", "critical"]).mean()
    q2_severe = _quarter(affected_tickets, "quarter", "2026-Q2")[
        "severity"
    ].isin(["high", "critical"]).mean()

    subscriptions = dataset.tables["subscriptions"]
    affected_due = subscriptions.loc[
        subscriptions["customer_id"].isin(customer_ids)
        & subscriptions["due_for_renewal"]
    ]
    q1_renewal = _quarter(affected_due, "quarter", "2026-Q1")[
        "renewal_status"
    ].eq("renewed").mean()
    q2_renewal = _quarter(affected_due, "quarter", "2026-Q2")[
        "renewal_status"
    ].eq("renewed").mean()

    assert q2_usage["core_feature_uses"].mean() < q1_usage[
        "core_feature_uses"
    ].mean()
    assert q2_severe > q1_severe
    assert q2_renewal < q1_renewal


def test_sales_volume_is_stable_but_east_smb_win_rate_falls() -> None:
    opportunities = generate_dataset(DEFAULT_SEED).tables["opportunities"]
    q1 = _quarter(opportunities, "close_quarter", "2026-Q1")
    q2 = _quarter(opportunities, "close_quarter", "2026-Q2")
    q1_segment = q1.loc[(q1["region"] == "华东") & (q1["size_segment"] == "SMB")]
    q2_segment = q2.loc[(q2["region"] == "华东") & (q2["size_segment"] == "SMB")]

    assert len(q1) == len(q2) == 200
    assert q2_segment["outcome"].eq("won").mean() < q1_segment[
        "outcome"
    ].eq("won").mean()


def test_competitor_price_losses_increase_in_q2() -> None:
    opportunities = generate_dataset(DEFAULT_SEED).tables["opportunities"]
    q1_lost = opportunities.loc[
        (opportunities["close_quarter"] == "2026-Q1")
        & (opportunities["outcome"] == "lost")
    ]
    q2_lost = opportunities.loc[
        (opportunities["close_quarter"] == "2026-Q2")
        & (opportunities["outcome"] == "lost")
    ]

    assert q2_lost["loss_reason"].eq("competitor_price").mean() > q1_lost[
        "loss_reason"
    ].eq("competitor_price").mean()
