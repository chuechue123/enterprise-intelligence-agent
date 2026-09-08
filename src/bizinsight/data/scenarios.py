"""Deterministic anomaly injection for the synthetic company dataset."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

SCENARIO_TARGETS: dict[str, Any] = {
    "delayed_project_count": 4,
    "deferred_revenue": 3_000_000,
    "q1_revenue": 18_700_000,
    "q2_revenue": 16_400_000,
    "q1_gross_margin": 0.468,
    "q2_gross_margin": 0.389,
    "q1_due_customers": 65,
    "q1_renewed_customers": 55,
    "q2_due_customers": 81,
    "q2_renewed_customers": 59,
    "q1_closed_opportunities": 200,
    "q1_won_opportunities": 62,
    "q2_closed_opportunities": 200,
    "q2_won_opportunities": 44,
    "q1_planned_projects": 36,
    "q1_on_time_projects": 31,
    "q2_planned_projects": 36,
    "q2_on_time_projects": 23,
}


def select_stability_cohort(
    customer_ids: list[str],
    rng: np.random.Generator,
    size: int = 48,
) -> list[str]:
    """Select a stable customer cohort affected by the v3.2 incident."""
    if len(customer_ids) < size:
        raise ValueError("not enough customers for the stability cohort")
    return list(rng.permutation(customer_ids)[:size])


def apply_sales_scenario(
    opportunities: pd.DataFrame,
    rng: np.random.Generator,
) -> None:
    """Inject lower Q2 win rates and stronger competitor-price pressure."""
    win_targets = {
        "2025-Q3": 90,
        "2025-Q4": 90,
        "2026-Q1": SCENARIO_TARGETS["q1_won_opportunities"],
        "2026-Q2": SCENARIO_TARGETS["q2_won_opportunities"],
    }
    segment_win_targets = {"2026-Q1": 20, "2026-Q2": 5}
    price_loss_shares = {
        "2025-Q3": 0.18,
        "2025-Q4": 0.20,
        "2026-Q1": 0.15,
        "2026-Q2": 0.45,
    }

    opportunities["outcome"] = "lost"
    opportunities["stage"] = "closed_lost"
    opportunities["loss_reason"] = "other"

    for quarter, total_wins in win_targets.items():
        quarter_idx = opportunities.index[
            opportunities["close_quarter"].eq(quarter)
        ].to_numpy()
        segment_idx = opportunities.index[
            opportunities["close_quarter"].eq(quarter)
            & opportunities["region"].eq("华东")
            & opportunities["size_segment"].eq("SMB")
        ].to_numpy()

        if quarter in segment_win_targets:
            segment_wins = segment_win_targets[quarter]
            selected_segment = rng.permutation(segment_idx)[:segment_wins]
            non_segment_idx = np.setdiff1d(quarter_idx, segment_idx)
            selected_other = rng.permutation(non_segment_idx)[
                : total_wins - segment_wins
            ]
            win_idx = np.concatenate([selected_segment, selected_other])
        else:
            win_idx = rng.permutation(quarter_idx)[:total_wins]

        opportunities.loc[win_idx, "outcome"] = "won"
        opportunities.loc[win_idx, "stage"] = "closed_won"
        opportunities.loc[win_idx, "loss_reason"] = None

        lost_idx = opportunities.index[
            opportunities["close_quarter"].eq(quarter)
            & opportunities["outcome"].eq("lost")
        ].to_numpy()
        price_count = round(len(lost_idx) * price_loss_shares[quarter])
        price_idx = rng.permutation(lost_idx)[:price_count]
        other_idx = np.setdiff1d(lost_idx, price_idx)
        opportunities.loc[price_idx, "loss_reason"] = "competitor_price"
        opportunities.loc[other_idx, "loss_reason"] = rng.choice(
            ["product_fit", "budget_frozen", "timing", "other"],
            size=len(other_idx),
        )


def apply_renewal_scenario(
    subscriptions: pd.DataFrame,
    customer_ids: list[str],
    affected_customer_ids: list[str],
    rng: np.random.Generator,
) -> dict[str, list[str]]:
    """Inject exact Q1/Q2 renewal cohorts and a weaker v3.2 cohort result."""
    q1_affected = affected_customer_ids[:24]
    q2_affected = affected_customer_ids[24:48]
    unaffected = [item for item in customer_ids if item not in affected_customer_ids]
    unaffected = list(rng.permutation(unaffected))

    q1_other = unaffected[:41]
    q2_other = unaffected[41:98]
    q1_due = q1_affected + q1_other
    q2_due = q2_affected + q2_other
    q1_renewed = set(q1_affected[:22] + q1_other[:33])
    q2_renewed = set(q2_affected[:12] + q2_other[:47])

    subscriptions["due_for_renewal"] = False
    subscriptions["renewal_status"] = "not_due"

    for due_ids, renewed_ids, months in (
        (q1_due, q1_renewed, ["2026-01", "2026-02", "2026-03"]),
        (q2_due, q2_renewed, ["2026-04", "2026-05", "2026-06"]),
    ):
        for index, customer_id in enumerate(due_ids):
            month = months[index % len(months)]
            row_mask = subscriptions["customer_id"].eq(customer_id) & subscriptions[
                "month"
            ].eq(month)
            subscriptions.loc[row_mask, "due_for_renewal"] = True
            subscriptions.loc[row_mask, "renewal_status"] = (
                "renewed" if customer_id in renewed_ids else "churned"
            )

    return {
        "q1_due_customer_ids": q1_due,
        "q1_renewed_customer_ids": sorted(q1_renewed),
        "q2_due_customer_ids": q2_due,
        "q2_renewed_customer_ids": sorted(q2_renewed),
    }


def apply_usage_scenario(
    product_usage: pd.DataFrame,
    affected_customer_ids: list[str],
) -> None:
    """Lower Q2 engagement for customers exposed to CloudFlow v3.2."""
    affected_q2 = product_usage["customer_id"].isin(
        affected_customer_ids,
    ) & product_usage["quarter"].eq("2026-Q2")
    product_usage.loc[affected_q2, "product_version"] = "CloudFlow v3.2"
    for column, factor in {
        "active_users": 0.78,
        "login_count": 0.68,
        "workflow_runs": 0.62,
        "core_feature_uses": 0.55,
    }.items():
        product_usage.loc[affected_q2, column] = (
            product_usage.loc[affected_q2, column] * factor
        ).round().astype(int)


def apply_ticket_scenario(
    support_tickets: pd.DataFrame,
    affected_customer_ids: list[str],
    rng: np.random.Generator,
) -> None:
    """Raise Q2 severe v3.2 tickets and worsen service outcomes."""
    affected = support_tickets["customer_id"].isin(affected_customer_ids)
    for quarter, severe_share in (
        ("2026-Q1", 0.20),
        ("2026-Q2", 0.58),
    ):
        cohort_idx = support_tickets.index[
            affected & support_tickets["quarter"].eq(quarter)
        ].to_numpy()
        severe_count = round(len(cohort_idx) * severe_share)
        severe_idx = rng.permutation(cohort_idx)[:severe_count]
        normal_idx = np.setdiff1d(cohort_idx, severe_idx)
        support_tickets.loc[severe_idx, "severity"] = rng.choice(
            ["high", "critical"],
            size=len(severe_idx),
            p=[0.7, 0.3],
        )
        support_tickets.loc[normal_idx, "severity"] = rng.choice(
            ["low", "medium"],
            size=len(normal_idx),
        )

    q2_affected = affected & support_tickets["quarter"].eq("2026-Q2")
    support_tickets.loc[q2_affected, "product_version"] = "CloudFlow v3.2"
    support_tickets.loc[q2_affected, "category"] = rng.choice(
        ["stability", "performance", "workflow_failure"],
        size=int(q2_affected.sum()),
        p=[0.5, 0.3, 0.2],
    )

    severe = support_tickets["severity"].isin(["high", "critical"])
    support_tickets.loc[severe, "first_response_hours"] *= 1.8
    support_tickets.loc[severe, "resolution_hours"] *= 1.7
    support_tickets.loc[severe, "satisfaction_score"] = np.minimum(
        support_tickets.loc[severe, "satisfaction_score"],
        2.8,
    )
    support_tickets["first_response_hours"] = support_tickets[
        "first_response_hours"
    ].round(2)
    support_tickets["resolution_hours"] = support_tickets[
        "resolution_hours"
    ].round(2)


def apply_delivery_scenario(
    projects: pd.DataFrame,
    deferred_contract_ids: list[str],
    rng: np.random.Generator,
) -> list[str]:
    """Inject delivery delays, customization growth, and cost overruns."""
    projects["customization_level"] = "medium"
    projects["on_time"] = False
    projects["deferred_revenue"] = 0

    for quarter, high_count in (
        ("2026-Q1", 6),
        ("2026-Q2", 20),
    ):
        quarter_idx = projects.index[
            projects["planned_acceptance_quarter"].eq(quarter)
        ].to_numpy()
        high_idx = rng.permutation(quarter_idx)[:high_count]
        projects.loc[high_idx, "customization_level"] = "high"

    q2_idx = projects.index[
        projects["planned_acceptance_quarter"].eq("2026-Q2")
    ].to_numpy()
    delayed_idx = projects.index[
        projects["contract_id"].isin(deferred_contract_ids)
    ].to_numpy()
    q2_eligible = np.setdiff1d(q2_idx, delayed_idx)

    q1_idx = projects.index[
        projects["planned_acceptance_quarter"].eq("2026-Q1")
    ].to_numpy()
    on_time_q1 = rng.permutation(q1_idx)[
        : SCENARIO_TARGETS["q1_on_time_projects"]
    ]
    on_time_q2 = rng.permutation(q2_eligible)[
        : SCENARIO_TARGETS["q2_on_time_projects"]
    ]
    projects.loc[np.concatenate([on_time_q1, on_time_q2]), "on_time"] = True

    for row_index, row in projects.iterrows():
        planned = date.fromisoformat(row["planned_acceptance_date"])
        if row["contract_id"] in deferred_contract_ids:
            projects.at[row_index, "actual_acceptance_date"] = None
            projects.at[row_index, "deferred_revenue"] = 750_000
        elif row["on_time"]:
            projects.at[row_index, "actual_acceptance_date"] = (
                planned - timedelta(days=int(rng.integers(0, 6)))
            ).isoformat()
        else:
            projects.at[row_index, "actual_acceptance_date"] = (
                planned + timedelta(days=int(rng.integers(7, 22)))
            ).isoformat()

        quarter = row["planned_acceptance_quarter"]
        high_custom = projects.at[row_index, "customization_level"] == "high"
        if quarter == "2026-Q2":
            multiplier = (
                rng.uniform(1.32, 1.55)
                if high_custom
                else rng.uniform(1.12, 1.28)
            )
            outsourcing_rate = (
                rng.uniform(0.20, 0.32)
                if high_custom
                else rng.uniform(0.10, 0.18)
            )
        elif quarter == "2026-Q1":
            multiplier = (
                rng.uniform(1.08, 1.20)
                if high_custom
                else rng.uniform(0.98, 1.10)
            )
            outsourcing_rate = (
                rng.uniform(0.10, 0.18)
                if high_custom
                else rng.uniform(0.03, 0.09)
            )
        else:
            multiplier = rng.uniform(0.98, 1.15)
            outsourcing_rate = rng.uniform(0.04, 0.12)
        projects.at[row_index, "actual_hours"] = round(
            row["planned_hours"] * multiplier,
        )
        projects.at[row_index, "outsourcing_cost"] = round(
            row["planned_hours"] * 550 * outsourcing_rate,
        )

    return projects.loc[delayed_idx, "project_id"].tolist()
