"""Reproducible synthetic business dataset generation."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from bizinsight.data.scenarios import (
    SCENARIO_TARGETS,
    apply_delivery_scenario,
    apply_renewal_scenario,
    apply_sales_scenario,
    apply_ticket_scenario,
    apply_usage_scenario,
    select_stability_cohort,
)

DEFAULT_SEED = 20_260_908
DATA_START = date(2025, 7, 1)
DATA_END = date(2026, 6, 30)
QUARTERS: dict[str, tuple[date, date]] = {
    "2025-Q3": (date(2025, 7, 1), date(2025, 9, 30)),
    "2025-Q4": (date(2025, 10, 1), date(2025, 12, 31)),
    "2026-Q1": (date(2026, 1, 1), date(2026, 3, 31)),
    "2026-Q2": (date(2026, 4, 1), date(2026, 6, 30)),
}
MONTHS = [
    "2025-07",
    "2025-08",
    "2025-09",
    "2025-10",
    "2025-11",
    "2025-12",
    "2026-01",
    "2026-02",
    "2026-03",
    "2026-04",
    "2026-05",
    "2026-06",
]
TABLE_ROW_TARGETS = {
    "customers": 240,
    "opportunities": 800,
    "contracts": 350,
    "subscriptions": 2_500,
    "product_usage": 2_880,
    "projects": 120,
    "support_tickets": 1_800,
    "payments": 600,
}


@dataclass(frozen=True)
class SyntheticDataset:
    """In-memory generated tables plus non-runtime validation metadata."""

    seed: int
    tables: dict[str, pd.DataFrame]
    ground_truth: dict[str, Any]
    quality_summary: dict[str, Any]


@dataclass(frozen=True)
class GeneratedPaths:
    """Paths created by :func:`write_dataset`."""

    raw_dir: Path
    database_path: Path
    quality_summary_path: Path
    runtime_manifest_path: Path
    ground_truth_path: Path

    @property
    def runtime_inputs(self) -> tuple[Path, ...]:
        """Inputs that may be registered with Agent runtime tools."""
        return (
            self.raw_dir,
            self.database_path,
            self.runtime_manifest_path,
        )


def _random_date(
    rng: np.random.Generator,
    start: date,
    end: date,
) -> date:
    offset = int(rng.integers(0, (end - start).days + 1))
    return start + timedelta(days=offset)


def _quarter_for_month(month: str) -> str:
    year, month_number = (int(item) for item in month.split("-"))
    quarter = (month_number - 1) // 3 + 1
    return f"{year}-Q{quarter}"


def _allocate_total(total: int, weights: np.ndarray) -> np.ndarray:
    """Allocate an integer total proportionally without rounding drift."""
    raw = weights / weights.sum() * total
    values = np.floor(raw).astype(int)
    remainder = total - int(values.sum())
    if remainder:
        order = np.argsort(-(raw - values))
        values[order[:remainder]] += 1
    return values


def _generate_customers(rng: np.random.Generator) -> pd.DataFrame:
    regions = np.array(
        ["华东"] * 60 + ["华南"] * 45 + ["华北"] * 45 + ["西南"] * 45 + ["华中"] * 45,
        dtype=object,
    )
    sizes = np.array(
        ["SMB"] * 108 + ["Mid-Market"] * 84 + ["Enterprise"] * 48,
        dtype=object,
    )
    rng.shuffle(regions)
    rng.shuffle(sizes)
    industries = rng.choice(
        ["制造", "零售", "专业服务", "医药", "物流", "教育"],
        size=TABLE_ROW_TARGETS["customers"],
    )
    rows = []
    for index in range(TABLE_ROW_TARGETS["customers"]):
        rows.append(
            {
                "customer_id": f"CUST-{index + 1:04d}",
                "customer_name": f"云衡合成客户{index + 1:04d}",
                "region": regions[index],
                "industry": industries[index],
                "size_segment": sizes[index],
                "customer_since": _random_date(
                    rng,
                    date(2023, 1, 1),
                    date(2025, 6, 30),
                ).isoformat(),
            },
        )
    return pd.DataFrame(rows)


def _generate_opportunities(
    customers: pd.DataFrame,
    rng: np.random.Generator,
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    all_records = customers.to_dict("records")
    east_smb = [
        item
        for item in all_records
        if item["region"] == "华东" and item["size_segment"] == "SMB"
    ]
    non_east_smb = [item for item in all_records if item not in east_smb]

    opportunity_number = 1
    for quarter, (start, end) in QUARTERS.items():
        selected_segment = [east_smb[i % len(east_smb)] for i in range(50)]
        selected_other = [
            non_east_smb[int(rng.integers(0, len(non_east_smb)))] for _ in range(150)
        ]
        selected_customers = selected_segment + selected_other
        rng.shuffle(selected_customers)

        for customer in selected_customers:
            close_date = _random_date(rng, start, end)
            created_date = max(
                DATA_START,
                close_date - timedelta(days=int(rng.integers(14, 91))),
            )
            size_multiplier = {
                "SMB": 0.65,
                "Mid-Market": 1.0,
                "Enterprise": 1.8,
            }[customer["size_segment"]]
            records.append(
                {
                    "opportunity_id": f"OPP-{opportunity_number:04d}",
                    "customer_id": customer["customer_id"],
                    "created_date": created_date.isoformat(),
                    "close_date": close_date.isoformat(),
                    "close_quarter": quarter,
                    "region": customer["region"],
                    "size_segment": customer["size_segment"],
                    "product": rng.choice(
                        ["CloudFlow", "DataCanvas", "OpsPilot"],
                        p=[0.55, 0.25, 0.20],
                    ),
                    "amount": round(
                        rng.uniform(80_000, 420_000) * size_multiplier,
                    ),
                    "stage": "closed_lost",
                    "outcome": "lost",
                    "loss_reason": "other",
                },
            )
            opportunity_number += 1

    opportunities = pd.DataFrame(records)
    apply_sales_scenario(opportunities, rng)
    return opportunities


def _generate_contracts(
    customers: pd.DataFrame,
    opportunities: pd.DataFrame,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, list[str]]:
    customer_ids = customers["customer_id"].tolist()
    contract_customers = customer_ids + list(rng.choice(customer_ids, size=110))
    recognition_quarters = (
        ["2025-Q3"] * 80
        + ["2025-Q4"] * 85
        + ["2026-Q1"] * 90
        + ["2026-Q2"] * 91
        + ["deferred"] * 4
    )
    rng.shuffle(recognition_quarters)

    won_by_customer: dict[str, list[str]] = {}
    for row in opportunities.loc[opportunities["outcome"].eq("won")].itertuples():
        won_by_customer.setdefault(row.customer_id, []).append(row.opportunity_id)

    rows: list[dict[str, Any]] = []
    for index, (customer_id, recognition_quarter) in enumerate(
        zip(contract_customers, recognition_quarters, strict=True),
    ):
        if recognition_quarter == "deferred":
            planned_recognition = _random_date(rng, *QUARTERS["2026-Q2"])
            recognition_date = None
        else:
            planned_recognition = _random_date(
                rng,
                *QUARTERS[recognition_quarter],
            )
            recognition_date = planned_recognition.isoformat()
        signed_date = max(
            DATA_START,
            planned_recognition - timedelta(days=int(rng.integers(7, 46))),
        )
        possible_opportunities = won_by_customer.get(customer_id, [])
        opportunity_id = (
            rng.choice(possible_opportunities) if possible_opportunities else None
        )
        rows.append(
            {
                "contract_id": f"CONTRACT-{index + 1:04d}",
                "customer_id": customer_id,
                "opportunity_id": opportunity_id,
                "signed_date": signed_date.isoformat(),
                "contract_start_date": signed_date.isoformat(),
                "contract_end_date": (signed_date + timedelta(days=364)).isoformat(),
                "product": rng.choice(
                    ["CloudFlow", "DataCanvas", "OpsPilot"],
                    p=[0.58, 0.24, 0.18],
                ),
                "recognition_quarter": recognition_quarter,
                "recognition_date": recognition_date,
                "recognized_revenue": 0,
                "recognized_cost": 0,
                "contract_value": 750_000 if recognition_quarter == "deferred" else 0,
            },
        )

    contracts = pd.DataFrame(rows)
    revenue_totals = {
        "2025-Q3": 17_200_000,
        "2025-Q4": 18_100_000,
        "2026-Q1": SCENARIO_TARGETS["q1_revenue"],
        "2026-Q2": SCENARIO_TARGETS["q2_revenue"],
    }
    margin_targets = {
        "2025-Q3": 0.45,
        "2025-Q4": 0.46,
        "2026-Q1": SCENARIO_TARGETS["q1_gross_margin"],
        "2026-Q2": SCENARIO_TARGETS["q2_gross_margin"],
    }
    for quarter, revenue_total in revenue_totals.items():
        idx = contracts.index[contracts["recognition_quarter"].eq(quarter)]
        revenue = _allocate_total(
            revenue_total,
            rng.lognormal(mean=0.0, sigma=0.45, size=len(idx)),
        )
        contracts.loc[idx, "recognized_revenue"] = revenue
        contracts.loc[idx, "contract_value"] = revenue

        risk = rng.uniform(0.9, 1.1, size=len(idx))
        if quarter == "2026-Q2":
            risk[: round(len(idx) * 0.45)] *= 1.25
        total_cost = round(revenue_total * (1 - margin_targets[quarter]))
        costs = _allocate_total(total_cost, revenue * risk)
        contracts.loc[idx, "recognized_cost"] = costs

    deferred_ids = contracts.loc[
        contracts["recognition_quarter"].eq("deferred"),
        "contract_id",
    ].tolist()
    return contracts, deferred_ids


def _primary_contracts(contracts: pd.DataFrame) -> dict[str, str]:
    return (
        contracts.drop_duplicates("customer_id")
        .set_index("customer_id")["contract_id"]
        .to_dict()
    )


def _generate_subscriptions(
    customers: pd.DataFrame,
    contracts: pd.DataFrame,
    affected_customer_ids: list[str],
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    primary_contract = _primary_contracts(contracts)
    customer_ids = customers["customer_id"].tolist()
    rows: list[dict[str, Any]] = []
    record_number = 1
    for index, customer_id in enumerate(customer_ids):
        active_months = MONTHS[1:] if index < 100 else MONTHS[2:]
        contract_id = primary_contract[customer_id]
        contract_value = int(
            contracts.loc[
                contracts["contract_id"].eq(contract_id),
                "contract_value",
            ].iloc[0],
        )
        for month in active_months:
            rows.append(
                {
                    "subscription_id": f"SUB-{record_number:05d}",
                    "contract_id": contract_id,
                    "customer_id": customer_id,
                    "month": month,
                    "quarter": _quarter_for_month(month),
                    "status": "active",
                    "due_for_renewal": False,
                    "renewal_status": "not_due",
                    "mrr": round(contract_value / 12),
                },
            )
            record_number += 1
    subscriptions = pd.DataFrame(rows)
    renewal_metadata = apply_renewal_scenario(
        subscriptions,
        customer_ids,
        affected_customer_ids,
        rng,
    )
    return subscriptions, renewal_metadata


def _generate_product_usage(
    customers: pd.DataFrame,
    contracts: pd.DataFrame,
    affected_customer_ids: list[str],
    rng: np.random.Generator,
) -> pd.DataFrame:
    primary_contract = _primary_contracts(contracts)
    rows: list[dict[str, Any]] = []
    record_number = 1
    size_base = {"SMB": 24, "Mid-Market": 65, "Enterprise": 150}
    for customer in customers.itertuples():
        for month in MONTHS:
            active_users = max(
                3,
                round(size_base[customer.size_segment] * rng.uniform(0.85, 1.15)),
            )
            rows.append(
                {
                    "usage_id": f"USAGE-{record_number:05d}",
                    "customer_id": customer.customer_id,
                    "contract_id": primary_contract[customer.customer_id],
                    "month": month,
                    "quarter": _quarter_for_month(month),
                    "product_version": "CloudFlow v3.1"
                    if month < "2026-04"
                    else "CloudFlow v3.2",
                    "active_users": active_users,
                    "login_count": round(active_users * rng.uniform(10, 16)),
                    "workflow_runs": round(active_users * rng.uniform(18, 30)),
                    "core_feature_uses": round(active_users * rng.uniform(7, 12)),
                },
            )
            record_number += 1
    product_usage = pd.DataFrame(rows)
    apply_usage_scenario(product_usage, affected_customer_ids)
    return product_usage


def _generate_projects(
    contracts: pd.DataFrame,
    deferred_contract_ids: list[str],
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, list[str]]:
    quarter_counts = {
        "2025-Q3": 24,
        "2025-Q4": 24,
        "2026-Q1": SCENARIO_TARGETS["q1_planned_projects"],
        "2026-Q2": SCENARIO_TARGETS["q2_planned_projects"],
    }
    rows: list[dict[str, Any]] = []
    project_number = 1
    for quarter, count in quarter_counts.items():
        candidates = contracts.loc[
            contracts["recognition_quarter"].eq(quarter),
            "contract_id",
        ].tolist()
        if quarter == "2026-Q2":
            selected_contracts = list(
                rng.choice(candidates, size=count - 4, replace=False),
            )
            selected_contracts += deferred_contract_ids
        else:
            selected_contracts = list(rng.choice(candidates, size=count, replace=False))
        start, end = QUARTERS[quarter]
        planned_end = end - timedelta(days=24)
        for contract_id in selected_contracts:
            contract = contracts.loc[contracts["contract_id"].eq(contract_id)].iloc[0]
            planned_date = _random_date(rng, start + timedelta(days=15), planned_end)
            rows.append(
                {
                    "project_id": f"PROJECT-{project_number:04d}",
                    "contract_id": contract_id,
                    "customer_id": contract["customer_id"],
                    "planned_acceptance_date": planned_date.isoformat(),
                    "actual_acceptance_date": planned_date.isoformat(),
                    "planned_acceptance_quarter": quarter,
                    "on_time": False,
                    "planned_hours": int(rng.integers(450, 1_600)),
                    "actual_hours": 0,
                    "customization_level": "medium",
                    "outsourcing_cost": 0,
                    "deferred_revenue": 0,
                },
            )
            project_number += 1
    projects = pd.DataFrame(rows)
    delayed_project_ids = apply_delivery_scenario(
        projects,
        deferred_contract_ids,
        rng,
    )
    return projects, delayed_project_ids


def _generate_support_tickets(
    customers: pd.DataFrame,
    contracts: pd.DataFrame,
    affected_customer_ids: list[str],
    rng: np.random.Generator,
) -> pd.DataFrame:
    primary_contract = _primary_contracts(contracts)
    all_customer_ids = customers["customer_id"].tolist()
    unaffected = [
        item for item in all_customer_ids if item not in affected_customer_ids
    ]
    affected_counts = {
        "2025-Q3": 80,
        "2025-Q4": 90,
        "2026-Q1": 120,
        "2026-Q2": 240,
    }
    rows: list[dict[str, Any]] = []
    ticket_number = 1
    for quarter, (start, end) in QUARTERS.items():
        affected_count = affected_counts[quarter]
        selected = list(
            rng.choice(affected_customer_ids, size=affected_count, replace=True),
        )
        selected += list(
            rng.choice(
                unaffected,
                size=450 - affected_count,
                replace=True,
            ),
        )
        rng.shuffle(selected)
        for customer_id in selected:
            severity = rng.choice(
                ["low", "medium", "high", "critical"],
                p=[0.46, 0.40, 0.11, 0.03],
            )
            rows.append(
                {
                    "ticket_id": f"TICKET-{ticket_number:05d}",
                    "customer_id": customer_id,
                    "contract_id": primary_contract[customer_id],
                    "created_date": _random_date(rng, start, end).isoformat(),
                    "quarter": quarter,
                    "category": rng.choice(
                        ["how_to", "integration", "performance", "billing"],
                    ),
                    "severity": severity,
                    "first_response_hours": round(rng.uniform(0.4, 8.0), 2),
                    "resolution_hours": round(rng.uniform(2.0, 48.0), 2),
                    "satisfaction_score": round(rng.uniform(3.2, 5.0), 1),
                    "product_version": "CloudFlow v3.1"
                    if quarter != "2026-Q2"
                    else "CloudFlow v3.2",
                },
            )
            ticket_number += 1
    support_tickets = pd.DataFrame(rows)
    apply_ticket_scenario(support_tickets, affected_customer_ids, rng)
    return support_tickets


def _generate_payments(
    contracts: pd.DataFrame,
    rng: np.random.Generator,
) -> pd.DataFrame:
    selected_contracts = rng.choice(
        contracts["contract_id"].to_numpy(),
        size=TABLE_ROW_TARGETS["payments"],
        replace=True,
    )
    rows: list[dict[str, Any]] = []
    for index, contract_id in enumerate(selected_contracts):
        contract = contracts.loc[contracts["contract_id"].eq(contract_id)].iloc[0]
        payment_date = _random_date(rng, DATA_START, DATA_END)
        overdue_probability = 0.16 if payment_date >= date(2026, 4, 1) else 0.08
        rows.append(
            {
                "payment_id": f"PAYMENT-{index + 1:04d}",
                "contract_id": contract_id,
                "customer_id": contract["customer_id"],
                "payment_date": payment_date.isoformat(),
                "amount": round(
                    max(10_000, contract["contract_value"] * rng.uniform(0.2, 0.6)),
                ),
                "status": "overdue" if rng.random() < overdue_probability else "paid",
            },
        )
    return pd.DataFrame(rows)


def calculate_core_metrics(
    tables: dict[str, pd.DataFrame],
) -> dict[str, dict[str, float | int]]:
    """Calculate deterministic acceptance metrics for Q1 and Q2."""
    results: dict[str, dict[str, float | int]] = {}
    for quarter in ("2026-Q1", "2026-Q2"):
        contracts = tables["contracts"].loc[
            tables["contracts"]["recognition_quarter"].eq(quarter)
        ]
        revenue = int(contracts["recognized_revenue"].sum())
        cost = int(contracts["recognized_cost"].sum())

        due = tables["subscriptions"].loc[
            tables["subscriptions"]["quarter"].eq(quarter)
            & tables["subscriptions"]["due_for_renewal"]
        ]
        renewed = int(due["renewal_status"].eq("renewed").sum())

        projects = tables["projects"].loc[
            tables["projects"]["planned_acceptance_quarter"].eq(quarter)
        ]
        opportunities = tables["opportunities"].loc[
            tables["opportunities"]["close_quarter"].eq(quarter)
        ]
        results[quarter] = {
            "revenue": revenue,
            "gross_margin": round((revenue - cost) / revenue, 6),
            "renewal_rate": round(renewed / len(due), 6),
            "on_time_acceptance_rate": round(
                float(projects["on_time"].mean()),
                6,
            ),
            "win_rate": round(
                float(opportunities["outcome"].eq("won").mean()),
                6,
            ),
        }
    return results


def _orphan_count(
    child: pd.DataFrame,
    child_column: str,
    parent: pd.DataFrame,
    parent_column: str,
) -> int:
    values = child[child_column].dropna()
    values = values.loc[values.astype(str).ne("")]
    return int((~values.isin(parent[parent_column])).sum())


def _quality_summary(
    tables: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    relationships = {
        "opportunities.customer_id": (
            "opportunities",
            "customer_id",
            "customers",
            "customer_id",
        ),
        "contracts.customer_id": (
            "contracts",
            "customer_id",
            "customers",
            "customer_id",
        ),
        "contracts.opportunity_id": (
            "contracts",
            "opportunity_id",
            "opportunities",
            "opportunity_id",
        ),
        "subscriptions.contract_id": (
            "subscriptions",
            "contract_id",
            "contracts",
            "contract_id",
        ),
        "subscriptions.customer_id": (
            "subscriptions",
            "customer_id",
            "customers",
            "customer_id",
        ),
        "product_usage.contract_id": (
            "product_usage",
            "contract_id",
            "contracts",
            "contract_id",
        ),
        "product_usage.customer_id": (
            "product_usage",
            "customer_id",
            "customers",
            "customer_id",
        ),
        "projects.contract_id": (
            "projects",
            "contract_id",
            "contracts",
            "contract_id",
        ),
        "projects.customer_id": (
            "projects",
            "customer_id",
            "customers",
            "customer_id",
        ),
        "support_tickets.contract_id": (
            "support_tickets",
            "contract_id",
            "contracts",
            "contract_id",
        ),
        "support_tickets.customer_id": (
            "support_tickets",
            "customer_id",
            "customers",
            "customer_id",
        ),
        "payments.contract_id": (
            "payments",
            "contract_id",
            "contracts",
            "contract_id",
        ),
        "payments.customer_id": (
            "payments",
            "customer_id",
            "customers",
            "customer_id",
        ),
    }
    orphan_counts = {
        name: _orphan_count(
            tables[child_table],
            child_column,
            tables[parent_table],
            parent_column,
        )
        for name, (
            child_table,
            child_column,
            parent_table,
            parent_column,
        ) in relationships.items()
    }
    return {
        "record_counts": {name: len(frame) for name, frame in tables.items()},
        "missing_rates": {
            name: {
                column: round(float(rate), 6)
                for column, rate in frame.isna().mean().items()
            }
            for name, frame in tables.items()
        },
        "orphan_counts": orphan_counts,
        "foreign_key_integrity": 1.0 if sum(orphan_counts.values()) == 0 else 0.0,
        "core_metrics": calculate_core_metrics(tables),
    }


def generate_dataset(seed: int = DEFAULT_SEED) -> SyntheticDataset:
    """Generate all synthetic tables and their evaluation-only truth."""
    rng = np.random.default_rng(seed)
    customers = _generate_customers(rng)
    affected_customer_ids = select_stability_cohort(
        customers["customer_id"].tolist(),
        rng,
    )
    opportunities = _generate_opportunities(customers, rng)
    contracts, deferred_contract_ids = _generate_contracts(
        customers,
        opportunities,
        rng,
    )
    subscriptions, renewal_metadata = _generate_subscriptions(
        customers,
        contracts,
        affected_customer_ids,
        rng,
    )
    product_usage = _generate_product_usage(
        customers,
        contracts,
        affected_customer_ids,
        rng,
    )
    projects, delayed_project_ids = _generate_projects(
        contracts,
        deferred_contract_ids,
        rng,
    )
    support_tickets = _generate_support_tickets(
        customers,
        contracts,
        affected_customer_ids,
        rng,
    )
    payments = _generate_payments(contracts, rng)

    tables = {
        "customers": customers,
        "opportunities": opportunities,
        "contracts": contracts,
        "subscriptions": subscriptions,
        "product_usage": product_usage,
        "projects": projects,
        "support_tickets": support_tickets,
        "payments": payments,
    }
    metrics = calculate_core_metrics(tables)
    ground_truth = {
        "schema_version": 1,
        "seed": seed,
        "scenario_targets": SCENARIO_TARGETS,
        "core_metrics": metrics,
        "scenarios": {
            "delayed_acceptance": {
                "project_ids": delayed_project_ids,
                "contract_ids": deferred_contract_ids,
                "deferred_revenue": SCENARIO_TARGETS["deferred_revenue"],
            },
            "margin_erosion": {
                "description": (
                    "Q2 high-customization share, hours and outsourcing cost rise."
                ),
            },
            "v32_stability": {
                "customer_ids": affected_customer_ids,
                **renewal_metadata,
            },
            "sales_conversion": {
                "segment": {"region": "华东", "size_segment": "SMB"},
            },
            "competitor_pricing": {
                "loss_reason": "competitor_price",
            },
        },
    }
    return SyntheticDataset(
        seed=seed,
        tables=tables,
        ground_truth=ground_truth,
        quality_summary=_quality_summary(tables),
    )


def dataset_fingerprint(dataset: SyntheticDataset) -> str:
    """Hash canonical table contents for repeatability checks."""
    digest = hashlib.sha256()
    for table_name in sorted(dataset.tables):
        frame = dataset.tables[table_name]
        canonical = frame.sort_values(frame.columns[0]).to_csv(
            index=False,
            lineterminator="\n",
        )
        digest.update(table_name.encode("utf-8"))
        digest.update(canonical.encode("utf-8"))
    return digest.hexdigest()


def write_dataset(
    dataset: SyntheticDataset,
    project_root: str | Path,
) -> GeneratedPaths:
    """Write CSV, SQLite, quality metadata, and isolated ground truth."""
    root = Path(project_root).resolve()
    raw_dir = root / "data" / "raw"
    database_dir = root / "data" / "database"
    ground_truth_dir = root / "evaluations" / "ground_truth"
    raw_dir.mkdir(parents=True, exist_ok=True)
    database_dir.mkdir(parents=True, exist_ok=True)
    ground_truth_dir.mkdir(parents=True, exist_ok=True)

    database_path = database_dir / "bizinsight.sqlite"
    if database_path.exists():
        database_path.unlink()

    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for table_name, frame in dataset.tables.items():
            frame.to_csv(
                raw_dir / f"{table_name}.csv",
                index=False,
                lineterminator="\n",
            )
            frame.to_sql(table_name, connection, index=False, if_exists="replace")

    quality_summary_path = root / "data" / "data_quality_summary.json"
    quality_summary_path.write_text(
        json.dumps(dataset.quality_summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    ground_truth_path = ground_truth_dir / "golden_case.json"
    ground_truth_path.write_text(
        json.dumps(dataset.ground_truth, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    runtime_manifest_path = root / "data" / "runtime_manifest.json"
    runtime_manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "seed": dataset.seed,
                "csv_directory": "data/raw",
                "sqlite_database": "data/database/bizinsight.sqlite",
                "data_dictionary": "data/data_dictionary",
                "knowledge_index": "data/knowledge/index.json",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return GeneratedPaths(
        raw_dir=raw_dir,
        database_path=database_path,
        quality_summary_path=quality_summary_path,
        runtime_manifest_path=runtime_manifest_path,
        ground_truth_path=ground_truth_path,
    )
